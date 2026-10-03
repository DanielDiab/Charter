"""Rutas y configuración del prototipo.

Todo lo que cambia entre máquinas se lee del entorno (con `.env` opcional). Lo
que define el comportamiento de la plataforma NO está aquí: está en los
catálogos y en los manifiestos, que son archivos versionados y revisables.
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]
load_dotenv(RAIZ / ".env")

CATALOGOS = RAIZ / "catalogos"
MANIFIESTOS = RAIZ / "manifiestos"
EVALS = RAIZ / "evals"
CONOCIMIENTO = RAIZ / "conocimiento"
DATOS = RAIZ / "datos"


@dataclass(frozen=True)
class Config:
    ollama_base_url: str
    # Estado local (registro, trazas, índice, casos). En producción todo esto
    # es una sola base PostgreSQL con pgvector (sección 2.4); en el prototipo
    # son archivos SQLite/JSON en una carpeta que se puede borrar sin miedo.
    estado_dir: Path
    # "Hoy" de la plataforma. La vigencia de los documentos se evalúa contra
    # esta fecha; fijarla permite reproducir la evaluación de un día concreto.
    hoy: str | None
    embeddings: bool
    # Clasificador de alcance del guard de entrada. Se puede apagar para
    # pruebas offline; en uso normal va encendido.
    guard_alcance: bool


@lru_cache
def config() -> Config:
    estado = Path(os.getenv("BIA_ESTADO_DIR", RAIZ / ".estado"))
    estado.mkdir(parents=True, exist_ok=True)
    return Config(
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        estado_dir=estado,
        hoy=os.getenv("BIA_HOY") or None,
        embeddings=os.getenv("BIA_EMBEDDINGS", "1") != "0",
        guard_alcance=os.getenv("BIA_GUARD_ALCANCE", "1") != "0",
    )


def hoy() -> str:
    from datetime import date

    return config().hoy or date.today().isoformat()
