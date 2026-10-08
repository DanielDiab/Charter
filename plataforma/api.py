"""API de agentes, compatible con OpenAI (decisión 2.2).

Cada agente publicado aparece como un "modelo". Cualquier canal (chat interno,
Slack, la app de clientes) se conecta con un cliente de OpenAI cambiando la URL y
la llave, sin integración a la medida:

    curl localhost:8000/v1/chat/completions \\
      -H "Authorization: Bearer tok-espiga" \\
      -d '{"model": "sac-asistente-facturacion", "messages": [{"role": "user", "content": "¿Cuánto debo?"}]}'

Tres reglas que la API impone:
  - Solo sirve agentes `publicados`. Un borrador no existe para los canales.
  - El token identifica la sesión (SSO simulado en datos/sesiones.json) y de
    ahí sale el cliente. El cuerpo de la petición no puede cambiarlo.
  - La conversación se identifica con el encabezado `X-Charter-Conversacion`; si
    no llega, cada petición es una conversación nueva. De los `messages` que
    manda el cliente solo se toma el último del usuario: el historial
    autoritativo es el del runtime, no el que el canal dice que hubo.

Además expone los tres inventarios, los costos y la retroalimentación, que
alimentan la consola interna (aquí, el CLI).
"""

import json
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from plataforma import catalogo, inventario, monitoreo, registro, runtime, trazas
from plataforma.config import DATOS
from plataforma.mcp import Conexiones

_estado: dict = {}


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    cambios = registro.verificar_recertificacion()
    for c in cambios:
        print(f"[re-certificación] {c['agente']} v{c['version']} vuelve a evaluación: {', '.join(c['cambios'])}")
    async with Conexiones() as conexiones:
        _estado["conexiones"] = conexiones
        _estado["agentes"] = {}
        yield


app = FastAPI(title="Charter: plataforma de agentes", version="0.1.0", lifespan=ciclo_de_vida)


def _sesion(authorization: str | None) -> dict:
    sesiones = json.loads((DATOS / "sesiones.json").read_text(encoding="utf-8"))
    token = (authorization or "").removeprefix("Bearer ").strip()
    if token not in sesiones:
        raise HTTPException(401, "Token inválido. En el prototipo los tokens están en datos/sesiones.json.")
    return sesiones[token]


async def _agente(id_agente: str) -> runtime.Agente:
    try:
        m = registro.obtener_publicado(id_agente)
    except registro.ErrorRegistro:
        raise HTTPException(404, f"'{id_agente}' no es un agente publicado.") from None
    cache = _estado["agentes"]
    clave = (m.id, m.version)
    if clave not in cache:
        cache[clave] = await runtime.Agente(m, _estado["conexiones"], "produccion").preparar()
    return cache[clave]


class Mensaje(BaseModel):
    role: str
    content: str


class PeticionChat(BaseModel):
    model: str
    messages: list[Mensaje]
    stream: bool = False


@app.get("/v1/models")
def modelos():
    return {"object": "list", "data": [
        {"id": a["id"], "object": "model", "owned_by": a["area"], "version": a["version"]}
        for a in inventario.agentes() if a["estado"] == "publicado"
    ]}


@app.post("/v1/chat/completions")
async def chat(p: PeticionChat, authorization: str | None = Header(None),
               x_charter_conversacion: str | None = Header(None)):
    sesion = _sesion(authorization)
    agente = await _agente(p.model)
    texto = next((x.content for x in reversed(p.messages) if x.role == "user"), "")
    if not texto:
        raise HTTPException(422, "Falta un mensaje del usuario.")
    conversacion = x_charter_conversacion or uuid.uuid4().hex
    creado = int(time.time())

    if not p.stream:
        r = await agente.turno(texto, sesion, conversacion)
        return {
            "id": f"chatcmpl-{conversacion}", "object": "chat.completion", "created": creado, "model": p.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": r.respuesta}, "finish_reason": "stop"}],
            "charter": {"conversacion": conversacion, "herramientas": r.herramientas, "pendiente_confirmacion": r.pendiente,
                    "costo_usd": trazas.costo_conversacion(conversacion), "version_agente": agente.m.version},
        }

    async def eventos():
        # Cada chunk es un bloque YA validado por el guard de salida.
        primero = True
        async for ev in agente.responder(texto, sesion, conversacion):
            if ev["tipo"] != "bloque":
                continue
            contenido = ("" if primero else "\n\n") + ev["texto"]
            primero = False
            chunk = {"id": f"chatcmpl-{conversacion}", "object": "chat.completion.chunk", "created": creado,
                     "model": p.model, "choices": [{"index": 0, "delta": {"content": contenido}, "finish_reason": None}]}
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(eventos(), media_type="text/event-stream", headers={"X-Charter-Conversacion": conversacion})


class Retro(BaseModel):
    conversacion: str
    agente: str
    util: bool
    comentario: str = ""


@app.post("/v1/retroalimentacion")
def retroalimentacion(r: Retro):
    trazas.registrar_retroalimentacion(r.conversacion, r.agente, r.util, r.comentario)
    return {"ok": True}


@app.get("/inventario/agentes")
def inv_agentes():
    return inventario.agentes()


@app.get("/inventario/modelos")
def inv_modelos():
    return inventario.modelos()


@app.get("/inventario/orquestacion")
def inv_orquestacion():
    return inventario.orquestacion()


@app.get("/costos")
def costos():
    return trazas.costos_por_agente()


@app.get("/metricas/{id_agente}")
def metricas(id_agente: str):
    return monitoreo.metricas(id_agente)


@app.post("/catalogo/recargar")
def recargar():
    """Después de editar un catálogo: recarga y dispara la re-certificación."""
    catalogo.recargar()
    _estado["agentes"].clear()
    return {"recertificados": registro.verificar_recertificacion()}
