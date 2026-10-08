"""Conocimiento: ingesta y búsqueda híbrida con vigencia (figuras 11 y 12).

Qué va por RAG y qué no (figura 11), aplicado en este repo:
  - Datos de un cliente (factura, consumo)  → herramienta, nunca RAG.
  - Cálculos (desglose, escenarios)         → herramienta determinista.
  - Reglas que siempre aplican              → políticas heredadas / guards.
  - Explicaciones, procedimientos, FAQ      → aquí.
Por eso las cifras tarifarias NO están en la colección tarifas-metodologia: la
colección explica qué es cada componente; cuánto vale lo dice
`tarifas/calcular_desglose`. Una tarifa vencida no es "menos relevante", es
incorrecta.

Decisiones:
  - Vigencia obligatoria en cada documento, y el filtro va ANTES de buscar. Un
    documento vencido nunca compite por relevancia: no está en el universo.
  - Troceo por tipo: procedimientos y explicaciones por sección; FAQ por par
    pregunta/respuesta. Partir una FAQ por tamaño separa la pregunta de su
    respuesta.
  - Híbrida (BM25 + vectores) con fusión RRF: BM25 encuentra códigos y
    términos exactos ("componente R", "CU"); los vectores, preguntas
    conceptuales ("por qué me cobran por la red"). RRF combina rankings sin
    tener que calibrar escalas de puntaje distintas.
  - Top-5: pocos fragmentos precisos rinden más que muchos.

En el prototipo el índice es un JSON en .estado/; en producción, pgvector y un
índice de texto completo en la misma PostgreSQL.
"""

import json
import math
import re
import unicodedata
from collections import Counter

import yaml

from plataforma import catalogo
from plataforma.config import CONOCIMIENTO, config, hoy

RRF_K = 60
TOP_K = 5
CANDIDATOS = 20

_STOP = set(
    "a al algo como con cual cuales cuando de del donde el ella en es esta este esto la las le les lo los "
    "me mi mis no o para pero por que qué se si sin sobre su sus te tu tus un una uno y ya hay son ser "
    "cómo cuál qué es está están fue han".split()
)


def _sin_tildes(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def tokenizar(texto: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", _sin_tildes(texto.lower())) if t not in _STOP and len(t) > 1]


def slug(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _sin_tildes(t.lower())).strip("-")[:50]


# ── Ingesta ──────────────────────────────────────────────────────────────


def _leer_documento(ruta) -> tuple[dict, str]:
    texto = ruta.read_text(encoding="utf-8")
    if not texto.startswith("---"):
        raise ValueError(f"{ruta}: falta el encabezado con vigencia y dueño. Sin vigencia no se indexa.")
    _, meta, cuerpo = texto.split("---", 2)
    meta = yaml.safe_load(meta)
    for campo in ("titulo", "vigente_desde"):
        if campo not in meta:
            raise ValueError(f"{ruta}: falta '{campo}' en el encabezado.")
    return meta, cuerpo


def trocear(coleccion: str, nombre_doc: str, meta: dict, cuerpo: str) -> list[dict]:
    tipo = catalogo.colecciones()[coleccion]["troceo"]
    partes = re.split(r"^## +(.+)$", cuerpo, flags=re.MULTILINE)
    # partes = [intro, titulo1, cuerpo1, titulo2, cuerpo2, ...]
    fragmentos = []
    for titulo, texto in zip(partes[1::2], partes[2::2]):
        texto = texto.strip()
        if not texto:
            continue
        if tipo == "pregunta":
            contenido = f"Pregunta: {titulo.strip()}\nRespuesta: {texto}"
        else:
            contenido = f"{meta['titulo']} — {titulo.strip()}\n{texto}"
        fragmentos.append({
            "id": f"{coleccion}/{nombre_doc}#{slug(titulo)}",
            "coleccion": coleccion,
            "documento": nombre_doc,
            "titulo": titulo.strip(),
            "texto": contenido,
            "vigente_desde": str(meta["vigente_desde"]),
            "vigente_hasta": str(meta.get("vigente_hasta") or ""),
            "dueno": meta.get("dueno") or catalogo.colecciones()[coleccion]["dueno"],
        })
    return fragmentos


async def ingestar(gateway=None) -> dict:
    """Recorre conocimiento/<coleccion>/*.md, trocea, calcula embeddings y
    guarda el índice. Devuelve un resumen por colección."""
    fragmentos = []
    for coleccion in catalogo.colecciones():
        for ruta in sorted((CONOCIMIENTO / coleccion).glob("*.md")):
            meta, cuerpo = _leer_documento(ruta)
            fragmentos += trocear(coleccion, ruta.stem, meta, cuerpo)

    embeddings_ok = False
    if config().embeddings and gateway is not None:
        ctx = {"agente": "plataforma-ingesta", "area": "equipo-ia", "entorno": "plataforma", "conversacion": "ingesta"}
        try:
            for i in range(0, len(fragmentos), 32):
                lote = fragmentos[i:i + 32]
                vectores = await gateway.embeber(ctx, [f["texto"] for f in lote])
                for f, v in zip(lote, vectores):
                    f["vector"] = v
            embeddings_ok = True
        except Exception as exc:  # noqa: BLE001 — sin embeddings la búsqueda degrada a BM25, no se cae
            for f in fragmentos:
                f.pop("vector", None)
            print(f"[conocimiento] sin embeddings ({exc}); la búsqueda usará solo BM25")

    (config().estado_dir / "indice.json").write_text(json.dumps(fragmentos, ensure_ascii=False), encoding="utf-8")
    resumen = Counter(f["coleccion"] for f in fragmentos)
    return {"fragmentos": len(fragmentos), "por_coleccion": dict(resumen), "embeddings": embeddings_ok}


def cargar_indice() -> list[dict]:
    ruta = config().estado_dir / "indice.json"
    if not ruta.exists():
        raise FileNotFoundError("No hay índice de conocimiento. Corre `charter iniciar`.")
    return json.loads(ruta.read_text(encoding="utf-8"))


# ── Consulta ─────────────────────────────────────────────────────────────


def vigente(f: dict, fecha: str) -> bool:
    return f["vigente_desde"] <= fecha and (not f["vigente_hasta"] or fecha <= f["vigente_hasta"])


def _bm25(consulta: list[str], docs: list[dict], k1: float = 1.5, b: float = 0.75) -> list[tuple[float, dict]]:
    tokens_docs = [tokenizar(d["texto"]) for d in docs]
    n = len(docs)
    promedio = sum(map(len, tokens_docs)) / max(n, 1)
    df = Counter(t for toks in tokens_docs for t in set(toks))
    puntajes = []
    for d, toks in zip(docs, tokens_docs):
        tf = Counter(toks)
        s = 0.0
        for q in consulta:
            if q not in tf:
                continue
            idf = math.log(1 + (n - df[q] + 0.5) / (df[q] + 0.5))
            s += idf * tf[q] * (k1 + 1) / (tf[q] + k1 * (1 - b + b * len(toks) / promedio))
        if s > 0:
            puntajes.append((s, d))
    return sorted(puntajes, key=lambda x: -x[0])


def _coseno(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    den = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return num / den if den else 0.0


def rrf(*rankings: list[dict]) -> list[dict]:
    puntaje: dict[str, float] = {}
    por_id = {}
    for ranking in rankings:
        for pos, d in enumerate(ranking):
            puntaje[d["id"]] = puntaje.get(d["id"], 0) + 1 / (RRF_K + pos + 1)
            por_id[d["id"]] = d
    return [por_id[i] for i in sorted(puntaje, key=lambda i: -puntaje[i])]


async def buscar(consulta: str, colecciones: list[str], *, fecha: str | None = None,
                 gateway=None, ctx: dict | None = None, indice: list[dict] | None = None) -> list[dict]:
    fecha = fecha or hoy()
    indice = indice if indice is not None else cargar_indice()
    # Permisos y vigencia ANTES de buscar.
    universo = [f for f in indice if f["coleccion"] in colecciones and vigente(f, fecha)]
    if not universo:
        return []

    por_palabras = [d for _, d in _bm25(tokenizar(consulta), universo)[:CANDIDATOS]]
    rankings = [por_palabras]
    if gateway is not None and config().embeddings and all("vector" in f for f in universo):
        try:
            (q,) = await gateway.embeber(ctx or {}, [consulta])
            semanticos = sorted(universo, key=lambda f: -_coseno(q, f["vector"]))[:CANDIDATOS]
            rankings.append(semanticos)
        except Exception:  # noqa: BLE001 — degradar a BM25
            pass
    return [
        {"cita": f["id"], "texto": f["texto"], "vigente_desde": f["vigente_desde"],
         "vigente_hasta": f["vigente_hasta"] or None}
        for f in rrf(*rankings)[:TOP_K]
    ]
