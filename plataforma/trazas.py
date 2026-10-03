"""Trazas y costos por agente (la capa transversal de observabilidad).

En la propuesta esto es Langfuse autohospedado con las convenciones GenAI de
OpenTelemetry. En el prototipo es una tabla SQLite con los mismos campos que
tendría cada span (agente, versión, área, modelo, tokens, costo, latencia), para
no pedirle a quien lo evalúe que levante un servicio más. Cambiar el destino
es reemplazar `registrar_span`; quien lo llama no se entera.

Dos decisiones que sí se mantienen del diseño:

- La PII se enmascara ANTES de persistir. Si el agente es `restringido` no se
  guarda contenido, solo metadatos (figura 8).
- "¿Cuánto cuesta cada agente?" es una consulta, no un reporte que alguien
  arma a mano: ver `costos_por_agente`.
"""

import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager

from plataforma.config import config

_PATRONES_PII = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "<correo>"),
    (re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-\d\b"), "<nit>"),
    (re.compile(r"\b3\d{9}\b"), "<telefono>"),
    (re.compile(r"\b\d{6,10}\b"), "<numero>"),
]


def enmascarar(texto: str) -> str:
    for patron, reemplazo in _PATRONES_PII:
        texto = patron.sub(reemplazo, texto)
    return texto


def _conexion() -> sqlite3.Connection:
    con = sqlite3.connect(config().estado_dir / "trazas.db")
    con.execute(
        """CREATE TABLE IF NOT EXISTS spans (
            id TEXT PRIMARY KEY, ts REAL, conversacion TEXT, agente TEXT, version TEXT,
            area TEXT, entorno TEXT, tipo TEXT, nombre TEXT, alias TEXT, modelo TEXT,
            tokens_entrada INTEGER, tokens_salida INTEGER, costo_usd REAL,
            latencia_ms INTEGER, estado TEXT, detalle TEXT)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS retroalimentacion (
            ts REAL, conversacion TEXT, agente TEXT, util INTEGER, comentario TEXT)"""
    )
    return con


def registrar_span(ctx: dict, tipo: str, nombre: str, *, estado: str = "ok", detalle: dict | None = None,
                   alias: str = "", modelo: str = "", tokens_entrada: int = 0, tokens_salida: int = 0,
                   costo_usd: float = 0.0, latencia_ms: int = 0) -> None:
    """`ctx` es el contexto de la conversación que arma el runtime: agente,
    versión, área, entorno (sandbox, evaluacion, produccion), clasificación."""
    detalle = detalle or {}
    if ctx.get("clasificacion") == "restringida":
        detalle = {"omitido": "agente restringido: solo metadatos"}
    elif ctx.get("enmascarar", True):
        detalle = json.loads(enmascarar(json.dumps(detalle, ensure_ascii=False)))
    with _conexion() as con:
        con.execute(
            "INSERT INTO spans VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, time.time(), ctx.get("conversacion", ""), ctx.get("agente", ""),
             ctx.get("version", ""), ctx.get("area", ""), ctx.get("entorno", ""), tipo, nombre, alias,
             modelo, tokens_entrada, tokens_salida, costo_usd, latencia_ms, estado,
             json.dumps(detalle, ensure_ascii=False)),
        )


@contextmanager
def medir(ctx: dict, tipo: str, nombre: str, **extra):
    """Span con latencia para lo que no es una llamada a modelo (herramientas, guards)."""
    inicio = time.perf_counter()
    resultado = {"estado": "ok", "detalle": {}}
    try:
        yield resultado
    except Exception as exc:
        resultado["estado"] = "error"
        resultado["detalle"]["error"] = str(exc)
        raise
    finally:
        registrar_span(ctx, tipo, nombre, estado=resultado["estado"], detalle=resultado["detalle"],
                       latencia_ms=int((time.perf_counter() - inicio) * 1000), **extra)


def costo_conversacion(conversacion: str) -> float:
    with _conexion() as con:
        (total,) = con.execute("SELECT COALESCE(SUM(costo_usd),0) FROM spans WHERE conversacion=?", (conversacion,)).fetchone()
    return total


def costo_mes(agente: str, mes: str) -> float:
    """`mes` como AAAA-MM. Solo cuenta producción: lo que se gasta probando en
    sandbox o en la compuerta no consume el tope mensual del área."""
    with _conexion() as con:
        (total,) = con.execute(
            "SELECT COALESCE(SUM(costo_usd),0) FROM spans WHERE agente=? AND entorno='produccion' "
            "AND strftime('%Y-%m', ts, 'unixepoch', 'localtime')=?",
            (agente, mes),
        ).fetchone()
    return total


def costos_por_agente() -> list[dict]:
    with _conexion() as con:
        filas = con.execute(
            """SELECT agente, area, entorno, COUNT(DISTINCT conversacion),
                      SUM(CASE WHEN tipo='llm' THEN 1 ELSE 0 END),
                      SUM(tokens_entrada), SUM(tokens_salida), ROUND(SUM(costo_usd), 5)
               FROM spans GROUP BY agente, area, entorno ORDER BY agente, entorno"""
        ).fetchall()
    campos = ["agente", "area", "entorno", "conversaciones", "llamadas_llm", "tokens_entrada", "tokens_salida", "costo_usd"]
    return [dict(zip(campos, f)) for f in filas]


def spans(conversacion: str | None = None, agente: str | None = None, limite: int = 200) -> list[dict]:
    consulta, args = "SELECT * FROM spans WHERE 1=1", []
    if conversacion:
        consulta += " AND conversacion=?"
        args.append(conversacion)
    if agente:
        consulta += " AND agente=?"
        args.append(agente)
    consulta += " ORDER BY ts DESC LIMIT ?"
    args.append(limite)
    with _conexion() as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(consulta, args).fetchall()]


def registrar_retroalimentacion(conversacion: str, agente: str, util: bool, comentario: str = "") -> None:
    with _conexion() as con:
        con.execute("INSERT INTO retroalimentacion VALUES (?,?,?,?,?)",
                    (time.time(), conversacion, agente, int(util), enmascarar(comentario)))


def retroalimentacion(agente: str) -> list[dict]:
    with _conexion() as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute("SELECT * FROM retroalimentacion WHERE agente=?", (agente,))]
