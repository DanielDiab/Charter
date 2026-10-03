"""Conexiones a los servidores MCP.

Uso el cliente MCP directo y no `langchain-mcp-adapters` (que usé en el curso)
por una razón: el runtime necesita controlar cada llamada (ocultar parámetros
al modelo, inyectarlos desde la sesión, retener escrituras hasta que el
usuario confirme, envolver el resultado como dato no confiable). Con el
adaptador, la herramienta ya llega empaquetada y esas reglas quedarían
repartidas en envoltorios. Aquí el runtime ve el esquema crudo y decide.

Las sesiones quedan abiertas mientras viva el proceso (CLI o API): lanzar un
subproceso por llamada costaba ~0,5 s por herramienta.
"""

import json
import os
import sys
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from plataforma import catalogo
from plataforma.config import RAIZ, config


class ErrorHerramienta(Exception):
    pass


class Conexiones:
    def __init__(self):
        self._pila = AsyncExitStack()
        self._sesiones: dict[str, ClientSession] = {}
        self._herramientas: dict[str, dict] = {}

    async def __aenter__(self):
        await self._pila.__aenter__()
        return self

    async def __aexit__(self, *exc):
        await self._pila.__aexit__(*exc)

    async def abrir(self, servidor: str) -> None:
        if servidor in self._sesiones:
            return
        modulo = catalogo.herramientas()["servidores"][servidor]["modulo"]
        parametros = StdioServerParameters(
            command=sys.executable,
            args=["-m", modulo],
            # El SDK de MCP arranca el subproceso con un entorno casi vacío
            # (solo HOME y PATH). En el curso eso dejó a un servidor sin sus
            # variables dentro del contenedor; aquí se pasa el entorno completo.
            env={**os.environ, "PYTHONWARNINGS": "ignore"},
            cwd=str(RAIZ),
        )
        # El stderr de los servidores va a un archivo: en la terminal solo debe
        # verse la conversación.
        log = self._pila.enter_context(open(config().estado_dir / "mcp.log", "a"))
        leer, escribir = await self._pila.enter_async_context(stdio_client(parametros, errlog=log))
        sesion = await self._pila.enter_async_context(ClientSession(leer, escribir))
        await sesion.initialize()
        self._sesiones[servidor] = sesion
        for t in (await sesion.list_tools()).tools:
            self._herramientas[f"{servidor}/{t.name}"] = {
                "nombre": t.name,
                "descripcion": t.description or "",
                "esquema": t.inputSchema,
            }

    def definicion(self, ref: str) -> dict:
        if ref not in self._herramientas:
            raise ErrorHerramienta(f"El servidor no expone '{ref}'.")
        return self._herramientas[ref]

    async def llamar(self, ref: str, argumentos: dict) -> str:
        servidor, nombre = ref.split("/", 1)
        resultado = await self._sesiones[servidor].call_tool(nombre, argumentos)
        texto = "\n".join(getattr(c, "text", "") for c in resultado.content)
        if resultado.isError:
            raise ErrorHerramienta(texto)
        try:
            # Compacto: menos tokens de entrada en la siguiente llamada al modelo.
            return json.dumps(json.loads(texto), ensure_ascii=False, separators=(",", ":"))
        except (json.JSONDecodeError, TypeError):
            return texto
