"""MCP de soporte: la única herramienta de ESCRITURA del asistente de facturación.

Este servidor no pide confirmación: eso lo garantiza el runtime, que no llama
a una herramienta con `requiere_confirmacion` hasta que el usuario dice que sí.
Separar las dos cosas es deliberado: el sistema de casos no tiene por qué
saber de agentes, y la regla de confirmación vale igual para todo sistema.
"""

import json
import os
import time
from pathlib import Path
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from mcp_servers._datos import RAIZ

mcp = FastMCP("soporte", log_level="WARNING")


def _archivo() -> Path:
    estado = Path(os.getenv("BIA_ESTADO_DIR", RAIZ / ".estado"))
    estado.mkdir(parents=True, exist_ok=True)
    return estado / "casos.json"


@mcp.tool()
def crear_caso(
    cliente_id: str,
    motivo: Annotated[str, Field(description="Motivo en pocas palabras, p. ej. 'solicitud de acuerdo de pago'.")],
    resumen: Annotated[str, Field(description="Resumen de la conversación para que el asesor no tenga que preguntar de nuevo.")],
    prioridad: Literal["normal", "alta"] = "normal",
) -> dict:
    """Abre un caso para que un asesor humano lo atienda."""
    ruta = _archivo()
    casos = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else []
    caso = {
        "caso_id": f"CASO-{len(casos) + 1001}",
        "cliente_id": cliente_id,
        "motivo": motivo,
        "resumen": resumen,
        "prioridad": prioridad,
        "estado": "abierto",
        "creado": time.strftime("%Y-%m-%d %H:%M"),
    }
    casos.append(caso)
    ruta.write_text(json.dumps(casos, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        # Medido en la compuerta: sin esta frase, el modelo a veces confirmaba
        # el caso sin darle el número al usuario.
        "resumen": (f"Caso {caso['caso_id']} abierto en la cola de asesores de servicio al cliente; "
                    "responden en un día hábil. Dale este número al usuario."),
        "caso_id": caso["caso_id"], "estado": "abierto", "cola": "asesores de servicio al cliente",
        "tiempo_de_respuesta": "un día hábil",
    }


if __name__ == "__main__":
    mcp.run()
