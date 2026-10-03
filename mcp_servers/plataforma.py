"""MCP de la plataforma: las herramientas de consulta del Arquitecto.

Expone el registro y los catálogos como herramientas de solo lectura. Crear un
agente NO es una herramienta del modelo: es el flujo determinista de
`plataforma/arquitecto.py`, que llama a `plataforma/constructor.py` directamente.
"""

from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

import mcp_servers._datos  # noqa: F401 — agrega la raíz del repo al path
from plataforma import constructor, inventario

mcp = FastMCP("plataforma", log_level="WARNING")


@mcp.tool()
def consultar_catalogo(tipo: Literal["modelos", "herramientas", "colecciones", "arquetipos"]) -> dict:
    """Lo que está disponible hoy en un catálogo curado de la plataforma."""
    return constructor.resumen_catalogo(tipo)


@mcp.tool()
def consultar_inventario() -> dict:
    """Agentes registrados: estado, dueño, área, alias de modelo, riesgo y costo acumulado."""
    return {"agentes": inventario.agentes()}


@mcp.tool()
def recomendar_tier(
    datos: Annotated[Literal["publicos", "internos", "clientes", "restringidos"], Field(description="Qué datos verá el agente.")],
    tarea: Annotated[Literal["estrecha", "conversacion", "razonamiento"], Field(description="estrecha = clasificar, extraer o resumir.")],
) -> dict:
    """Aplica el árbol de decisión de modelos: primero el dato, después la tarea."""
    return constructor.recomendar_tier(datos, tarea)


if __name__ == "__main__":
    mcp.run()
