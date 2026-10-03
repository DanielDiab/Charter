"""Acceso a los datos sintéticos (datos/*.json). Hace las veces de las API de
facturación, medición y tarifas que Bia tendría que exponer (uno de los cinco
supuestos a validar la primera semana, sección 8)."""

import json
import sys
from functools import lru_cache
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

DATOS = RAIZ / "datos"


@lru_cache
def cargar(nombre: str):
    return json.loads((DATOS / f"{nombre}.json").read_text(encoding="utf-8"))


def periodos_de(cliente_id: str) -> list[str]:
    return [f["periodo"] for f in cargar("facturas").get(cliente_id, [])]


def resolver_periodo(cliente_id: str, periodo: str | None) -> str:
    disponibles = periodos_de(cliente_id)
    if not disponibles:
        raise ValueError("No hay información para el cliente de esta sesión.")
    if not periodo:
        return disponibles[-1]
    if periodo not in disponibles:
        raise ValueError(f"No hay factura del periodo {periodo}. Periodos disponibles: {', '.join(disponibles)}.")
    return periodo


def periodo_anterior(cliente_id: str, periodo: str) -> str | None:
    disponibles = periodos_de(cliente_id)
    i = disponibles.index(periodo)
    return disponibles[i - 1] if i > 0 else None


def pct(nuevo: float, viejo: float) -> float:
    return round((nuevo - viejo) / viejo * 100, 1)


MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def mes(periodo: str) -> str:
    anio, m = periodo.split("-")
    return f"{MESES[int(m) - 1]} de {anio}"


def pesos(valor: float) -> str:
    """5369752 → "5.369.752". Los resúmenes van con formato colombiano para que
    el modelo los copie tal cual y no tenga que reformatear (ni inventar)."""
    return f"{valor:,.0f}".replace(",", ".")


def num(valor: float) -> str:
    """25.8 → "25,8"."""
    return f"{valor:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
