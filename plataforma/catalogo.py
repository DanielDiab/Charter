"""Lectura de los catálogos curados (modelos, herramientas, colecciones,
arquetipos, plantillas).

Los catálogos son YAML versionado y no tablas editables desde una pantalla a
propósito: cambiar qué modelo hay detrás de un alias o qué puede escribir una
herramienta es una decisión que debe pasar por revisión de código, igual que
un cambio de infraestructura.

Además de leerlos, este módulo calcula la "huella" de cada pieza. Es lo que
permite la re-certificación automática: si la huella de algo de lo que depende
un agente publicado cambia, el agente vuelve a evaluación (registro.py).
"""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import yaml

from plataforma.config import CATALOGOS, CONOCIMIENTO

NIVELES_CLASIFICACION = ["publica", "interna", "confidencial", "restringida"]


def nivel(clasificacion: str) -> int:
    return NIVELES_CLASIFICACION.index(clasificacion)


def _leer(nombre: str) -> dict:
    return yaml.safe_load((CATALOGOS / nombre).read_text(encoding="utf-8"))


@lru_cache
def modelos() -> dict:
    return _leer("modelos.yaml")


@lru_cache
def herramientas() -> dict:
    return _leer("herramientas.yaml")


@lru_cache
def colecciones() -> dict:
    return _leer("colecciones.yaml")["colecciones"]


@lru_cache
def arquetipos() -> dict:
    return _leer("arquetipos.yaml")["arquetipos"]


def recargar() -> None:
    """Olvida lo leído. Lo usa la API para ver cambios sin reiniciar."""
    for f in (modelos, herramientas, colecciones, arquetipos):
        f.cache_clear()


def alias(nombre: str) -> dict:
    try:
        return modelos()["alias"][nombre]
    except KeyError:
        raise KeyError(f"El alias '{nombre}' no existe en el catálogo de modelos") from None


def herramienta(ref: str) -> dict:
    try:
        return herramientas()["herramientas"][ref]
    except KeyError:
        raise KeyError(f"La herramienta '{ref}' no está en el catálogo") from None


def servidor_de(ref: str) -> dict:
    return herramientas()["servidores"][ref.split("/", 1)[0]]


def plantilla(ref: str) -> str:
    ruta = CATALOGOS / "plantillas" / f"{ref}.md"
    if not ruta.exists():
        raise KeyError(f"La plantilla '{ref}' no existe en catalogos/plantillas/")
    return ruta.read_text(encoding="utf-8")


def politicas() -> str:
    return (CATALOGOS / "politicas.md").read_text(encoding="utf-8")


# ── Huellas para re-certificación ────────────────────────────────────────


def huella(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def _huella_coleccion(nombre: str) -> str:
    # Una colección cambia cuando cambia cualquiera de sus documentos.
    carpeta: Path = CONOCIMIENTO / nombre
    contenido = {p.name: p.read_text(encoding="utf-8") for p in sorted(carpeta.glob("*.md"))}
    return huella({"meta": colecciones().get(nombre), "docs": contenido})


def huella_dependencias(m) -> dict[str, str]:
    """Todo lo externo al manifiesto de lo que depende el comportamiento del
    agente: el modelo detrás de su alias (y del fallback), cada herramienta, cada
    colección, su plantilla y las políticas heredadas."""
    huellas = {f"alias:{m.spec.model.alias}": huella(alias(m.spec.model.alias))}
    if m.spec.model.fallback:
        huellas[f"alias:{m.spec.model.fallback}"] = huella(alias(m.spec.model.fallback))
    for t in m.spec.tools:
        huellas[f"herramienta:{t.mcp}"] = huella(herramienta(t.mcp))
    for c in m.spec.knowledge:
        huellas[f"coleccion:{c}"] = _huella_coleccion(c)
    huellas[f"plantilla:{m.spec.instructions.template}"] = huella(plantilla(m.spec.instructions.template))
    huellas["politicas"] = huella(politicas())
    return huellas
