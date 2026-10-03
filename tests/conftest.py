"""Las pruebas corren sin Ollama: el gateway recibe un modelo falso con
respuestas guionadas. Todo lo demás es real (manifiestos, catálogos, registro,
servidores MCP, guards, trazas), así que lo que se prueba es la plataforma y no
el modelo. La calidad del modelo la mide la compuerta (`bia evaluar`).
"""

import os
import tempfile

_ESTADO = tempfile.mkdtemp(prefix="bia-pruebas-")
os.environ["BIA_ESTADO_DIR"] = _ESTADO
os.environ["BIA_GUARD_ALCANCE"] = "0"
os.environ["BIA_EMBEDDINGS"] = "0"
os.environ["BIA_HOY"] = "2026-10-03"

import asyncio  # noqa: E402

import pytest  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402

from plataforma import conocimiento, gateway  # noqa: E402


class ModeloGuionado:
    """Devuelve, en orden, las respuestas que le dé la prueba. Registra lo que recibió."""

    def __init__(self, respuestas: list[AIMessage]):
        self.respuestas = list(respuestas)
        self.recibido: list = []
        self.herramientas: list = []

    def bind_tools(self, herramientas):
        self.herramientas = herramientas
        return self

    async def ainvoke(self, mensajes):
        self.recibido.append(mensajes)
        r = self.respuestas.pop(0)
        r.usage_metadata = {"input_tokens": 1000, "output_tokens": 100, "total_tokens": 1100}
        return r


def llamada(nombre: str, args: dict) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": nombre, "args": args, "id": f"c-{nombre}"}])


@pytest.fixture
def guion():
    """Instala un gateway cuyo modelo responde lo que la prueba diga."""

    def instalar(*respuestas):
        modelo = ModeloGuionado(list(respuestas))
        gateway.usar(gateway.Gateway(fabrica=lambda alias, a: modelo))
        return modelo

    yield instalar
    gateway.usar(gateway.Gateway())


@pytest.fixture(scope="session", autouse=True)
def indice():
    asyncio.run(conocimiento.ingestar(None))
