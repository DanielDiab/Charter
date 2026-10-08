"""MCP de conocimiento: búsqueda híbrida sobre las colecciones del agente.

`colecciones` lo inyecta el runtime desde el manifiesto; el modelo no lo ve en
el esquema y no puede pedir otras. `traza` también lo inyecta el runtime para
que el costo de los embeddings de la consulta quede atribuido al agente.
"""

from mcp.server.fastmcp import FastMCP

import mcp_servers._datos  # noqa: F401 — agrega la raíz del repo al path
from plataforma import conocimiento
from plataforma.gateway import gateway

mcp = FastMCP("conocimiento", log_level="WARNING")


@mcp.tool()
async def buscar_conocimiento(consulta: str, colecciones: list[str], traza: dict | None = None) -> dict:
    """Busca en la documentación vigente de la empresa (tarifas, procedimientos,
    preguntas frecuentes). Devuelve hasta 5 fragmentos, cada uno con su cita."""
    fragmentos = await conocimiento.buscar(consulta, colecciones, gateway=gateway(), ctx=traza or {})
    if not fragmentos:
        return {"fragmentos": [], "nota": "No se encontró nada en la documentación vigente."}
    return {"fragmentos": fragmentos}


if __name__ == "__main__":
    mcp.run()
