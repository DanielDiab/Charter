"""Runtime: convierte un manifiesto en un grafo LangGraph ejecutable.

Un solo runtime para todos los agentes (decisión 2.2). No hay código por
agente: lo que cambia entre el asistente de facturación y el Arquitecto es el
manifiesto que recibe esta clase.

    START → guard_entrada ─┬─▶ [recuperar] ─▶ agente ◀──▶ herramientas
                           │                    │              │
                           └────────────────────┴──▶ salida ◀──┘ → END
                                                       │
                                                       └─▶ agente (una corrección, si un bloque no pasa)

`recuperar` solo corre en arquetipos con `recuperar_siempre` (pregunta sobre
documentos y el Arquitecto): ahí la búsqueda es un paso que decide el código.

Las capas de seguridad de la figura 7 viven aquí y no en las instrucciones:

  1. Identidad   `cliente_id` sale de la sesión. El modelo ni siquiera ve ese
                 parámetro en el esquema de la herramienta; aunque lo pusiera,
                 se sobrescribe.
  2. Entrada     guards.revisar_entrada antes de gastar una llamada al modelo grande.
  3. Permisos    solo se cargan las herramientas del manifiesto; las de
                 escritura quedan retenidas hasta que el usuario dice "sí".
  4. Lo recuperado es dato: todo resultado se envuelve en <dato_no_confiable>.
  5. Salida      guards.revisar_bloque por bloque antes de emitir.
  6. Trazas      cada nodo deja span; el gateway aplica el presupuesto.

Herencia del agente del curso: el tope de iteraciones como red de seguridad,
la recuperación de tool calls con formato corrupto (frecuente en modelos
locales pequeños) y convertir errores de herramienta en mensajes en vez de
tumbar el grafo.
"""

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from plataforma import catalogo, guards, registro, trazas
from plataforma.compilador import compilar
from plataforma.gateway import PresupuestoExcedido, gateway
from plataforma.manifiesto import Manifiesto
from plataforma.mcp import Conexiones

MAX_ITERACIONES = 8
# Llamadas a una misma herramienta dentro de un turno. Medido con la primera
# versión del Arquitecto: ante un error que decía "pídele los ejemplos al
# usuario", el modelo volvió a llamar la herramienta con ejemplos inventados
# seis veces, hasta agotar el presupuesto de la conversación.
MAX_LLAMADAS_POR_HERRAMIENTA = 2
# "Voy a consultar", "vamos a hacerlo ahora", "podemos consultar el inventario"
# sin un tool call: el modelo narra la acción en vez de ejecutarla. Fue la falla
# más repetida del agente del curso y reapareció en la compuerta del Arquitecto.
_VERBOS = r"(?:consultar|revisar|verificar|buscar|obtener|llamar|hacerlo|proceder|ejecutar|generar|guardar|registrar|crear|proponer|ver\b)"
_NARRA_ACCION = re.compile(
    r"\b(?:voy|vamos|procedo|procedemos|podemos|puedo|necesitamos|necesito|d[eé]jame|perm[ií]teme)\s+(?:a\s+)?" + _VERBOS
    + r"|\b(?:consultar|revisar|verificar|buscar|llamar|generar|guardar|registrar|crear|proponer)emos\b", re.I)
_AFIRMATIVO = re.compile(r"^\s*(s[ií]|dale|confirmo|de acuerdo|ok|okay|h[aá]zlo|h[aá]galo|claro|adelante|correcto)\b", re.I)

RESPUESTA_TOPE = "No logré resolver esto en esta conversación. Si quieres, abro un caso para que un asesor te ayude."
RESPUESTA_PRESUPUESTO = "Esta conversación alcanzó su límite. Para seguir, un asesor puede ayudarte por los canales de Bia."


class Estado(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    sesion: dict
    pendiente: dict | None
    confirmado: bool
    iteracion: int
    correcciones: int
    nota: str
    reintentar: bool
    respuesta_final: str


@dataclass
class ResultadoTurno:
    """Lo que la compuerta y la API necesitan saber de un turno."""
    respuesta: str = ""
    herramientas: list[str] = field(default_factory=list)
    bloqueado: str | None = None
    pendiente: str | None = None
    guard_salida: list[dict] = field(default_factory=list)
    conversacion: str = ""


def _indicacion(texto: str) -> HumanMessage:
    """Corrección que la plataforma le hace al modelo dentro de una llamada (no
    queda en el historial). Va con rol de usuario y no de sistema: medido con
    qwen2.5:7b vía ChatOllama, una nota de sistema puesta después de la
    respuesta del modelo no tiene efecto (repite lo mismo); la misma nota como
    mensaje de usuario con este prefijo lo corrige."""
    return HumanMessage(content=f"[Plataforma] {texto}")


def _mensaje_plataforma(texto: str) -> AIMessage:
    # Texto escrito por la plataforma (no por el modelo): el guard de salida
    # no lo revisa y queda marcado en el historial.
    return AIMessage(content=texto, additional_kwargs={"plataforma": True})


def _tool_call_desde_texto(contenido: str):
    """Recupera un tool call que el modelo escribió como texto en vez de usar
    el formato de herramientas. Pasa con modelos locales pequeños cuando el
    contexto crece; perderlo deja al usuario esperando una consulta que nunca
    se hizo."""
    if not contenido:
        return None
    m = re.search(r'\{"name"\s*:\s*"(\w+)"\s*,\s*"arguments"\s*:\s*(\{.*\})\}', contenido, re.DOTALL)
    if not m:
        return None
    try:
        return {"name": m.group(1), "args": json.loads(m.group(2)), "id": f"recuperado-{uuid.uuid4().hex[:8]}"}
    except json.JSONDecodeError:
        return None


class Agente:
    def __init__(self, m: Manifiesto, conexiones: Conexiones, entorno: str = "produccion"):
        self.m = m
        self.conexiones = conexiones
        self.entorno = entorno
        self.instrucciones = compilar(m)
        self._grafo = None
        self._por_nombre: dict[str, str] = {}
        self._esquemas: list[dict] = []
        self._recuperar_siempre = bool(
            catalogo.arquetipos()[m.metadata.archetype].get("recuperar_siempre")
            and m.herramienta("conocimiento/buscar_conocimiento")
        )

    # ── Preparación ──────────────────────────────────────────────────────

    async def preparar(self) -> "Agente":
        for t in self.m.spec.tools:
            await self.conexiones.abrir(t.mcp.split("/", 1)[0])
            definicion = self.conexiones.definicion(t.mcp)
            ocultos = set(catalogo.herramienta(t.mcp).get("inyectados", {}))
            esquema = json.loads(json.dumps(definicion["esquema"]))
            for p in ocultos:
                esquema.get("properties", {}).pop(p, None)
            esquema["required"] = [r for r in esquema.get("required", []) if r not in ocultos]
            self._por_nombre[definicion["nombre"]] = t.mcp
            self._esquemas.append({
                "type": "function",
                "function": {"name": definicion["nombre"], "description": definicion["descripcion"], "parameters": esquema},
            })
        self._grafo = self._construir()
        return self

    def ctx(self, conversacion: str) -> dict:
        return {
            "agente": self.m.id, "version": self.m.version, "area": self.m.metadata.area,
            "entorno": self.entorno, "conversacion": conversacion,
            "clasificacion": self.m.spec.data.classification,
            "enmascarar": self.m.spec.data.mask_pii_in_traces,
            "presupuesto": self.m.spec.budget.model_dump(),
        }

    # ── Nodos ────────────────────────────────────────────────────────────

    def _construir(self):
        m = self.m
        g = StateGraph(Estado)

        async def guard_entrada(estado: Estado, config) -> dict:
            ctx = self.ctx(config["configurable"]["thread_id"])
            escribir = get_stream_writer()
            texto = str(estado["messages"][-1].content)
            base = {"iteracion": 0, "correcciones": 0, "nota": "", "confirmado": False, "reintentar": False}

            if estado.get("pendiente"):
                if _AFIRMATIVO.match(texto):
                    trazas.registrar_span(ctx, "evento", "confirmacion_usuario", detalle={"herramienta": estado["pendiente"]["ref"]})
                    return {**base, "confirmado": True}
                trazas.registrar_span(ctx, "evento", "accion_cancelada", detalle={"herramienta": estado["pendiente"]["ref"]})
                escribir({"tipo": "evento", "evento": "accion_cancelada"})
                return {**base, "pendiente": None,
                        "messages": [_mensaje_plataforma("Listo, no hice ningún cambio. ¿En qué más te ayudo?")]}

            previo = next((str(x.content) for x in reversed(estado["messages"][:-1]) if isinstance(x, AIMessage) and x.content), "")
            try:
                with trazas.medir(ctx, "guard", "guard_entrada") as span:
                    veredicto = await guards.revisar_entrada(texto, m, ctx, gateway(), previo, estado.get("sesion") or {})
                    span["detalle"] = {"permitido": veredicto.permitido, "motivo": veredicto.motivo, **veredicto.detalle}
            except PresupuestoExcedido:
                return {**base, "messages": [_mensaje_plataforma(RESPUESTA_PRESUPUESTO)]}
            if not veredicto.permitido:
                escribir({"tipo": "guard", "capa": "entrada", "motivo": veredicto.motivo})
                return {**base, "messages": [_mensaje_plataforma(veredicto.respuesta)]}
            return base

        def tras_entrada(estado: Estado) -> str:
            if estado.get("confirmado"):
                return "herramientas"
            ultimo = estado["messages"][-1]
            if isinstance(ultimo, AIMessage):
                return "salida"
            return "recuperar" if self._recuperar_siempre else "agente"

        async def recuperar(estado: Estado, config) -> dict:
            """Medido con qwen2.5 en la compuerta: en preguntas de sí/no el modelo
            contestaba "no lo encontré" sin haber buscado. Para un agente cuyo
            único trabajo es responder desde documentos, buscar no es opcional."""
            ctx = self.ctx(config["configurable"]["thread_id"])
            pregunta = str(estado["messages"][-1].content)
            llamada_id = f"recuperacion-{uuid.uuid4().hex[:8]}"
            contenido = await self._ejecutar(ctx, "conocimiento/buscar_conocimiento", {"consulta": pregunta},
                                             estado.get("sesion") or {}, get_stream_writer())
            return {"messages": [
                AIMessage(content="", tool_calls=[{"name": "buscar_conocimiento", "args": {"consulta": pregunta}, "id": llamada_id}]),
                ToolMessage(content=contenido, tool_call_id=llamada_id, name="buscar_conocimiento"),
            ]}

        async def agente(estado: Estado, config) -> dict:
            ctx = self.ctx(config["configurable"]["thread_id"])
            if estado.get("iteracion", 0) >= MAX_ITERACIONES:
                trazas.registrar_span(ctx, "evento", "tope_iteraciones", estado="error")
                return {"messages": [_mensaje_plataforma(RESPUESTA_TOPE)], "nota": ""}
            mensajes = [SystemMessage(content=self.instrucciones)] + list(estado["messages"])
            if estado.get("nota"):
                mensajes.append(_indicacion(estado["nota"]))
            try:
                resp = await self._razonar(ctx, mensajes, estado)
            except PresupuestoExcedido as exc:
                trazas.registrar_span(ctx, "evento", "presupuesto_excedido", estado="error", detalle={"motivo": str(exc)})
                return {"messages": [_mensaje_plataforma(RESPUESTA_PRESUPUESTO)], "nota": ""}
            return {"messages": [resp], "iteracion": estado.get("iteracion", 0) + 1, "nota": ""}

        def tras_agente(estado: Estado) -> str:
            ultimo = estado["messages"][-1]
            return "herramientas" if getattr(ultimo, "tool_calls", None) else "salida"

        async def herramientas(estado: Estado, config) -> dict:
            ctx = self.ctx(config["configurable"]["thread_id"])
            escribir = get_stream_writer()
            sesion = estado.get("sesion") or {}

            # Caso 1: el usuario acaba de confirmar una escritura retenida. Se
            # ejecuta y se agrega al historial como un par llamada/resultado nuevo.
            if estado.get("confirmado") and estado.get("pendiente"):
                p = estado["pendiente"]
                contenido = await self._ejecutar(ctx, p["ref"], dict(p["args"]), sesion, escribir)
                llamada_id = f"confirmada-{uuid.uuid4().hex[:8]}"
                return {
                    "pendiente": None, "confirmado": False,
                    "messages": [
                        AIMessage(content="", tool_calls=[{"name": p["nombre"], "args": p["args"], "id": llamada_id}]),
                        ToolMessage(content=contenido, tool_call_id=llamada_id, name=p["nombre"]),
                    ],
                }

            # Caso 2: el modelo pidió herramientas.
            salida, pendiente = [], None
            inicio_turno = max(i for i, x in enumerate(estado["messages"]) if isinstance(x, HumanMessage))
            previas = [x.name for x in estado["messages"][inicio_turno:] if isinstance(x, ToolMessage)]
            for llamada in estado["messages"][-1].tool_calls:
                ref = self._por_nombre.get(llamada["name"])
                if previas.count(llamada["name"]) >= MAX_LLAMADAS_POR_HERRAMIENTA:
                    trazas.registrar_span(ctx, "herramienta", ref or llamada["name"], estado="tope_repeticiones")
                    salida.append(ToolMessage(
                        content=(f"NO EJECUTADA: ya llamaste {llamada['name']} {MAX_LLAMADAS_POR_HERRAMIENTA} veces en este "
                                 "turno. No la vuelvas a llamar: responde al usuario con lo que tienes o pregúntale lo que falta."),
                        tool_call_id=llamada["id"], name=llamada["name"], status="error"))
                    continue
                if ref is None:
                    trazas.registrar_span(ctx, "herramienta", llamada["name"], estado="permiso_denegado")
                    salida.append(ToolMessage(content=f"La herramienta '{llamada['name']}' no está autorizada para este agente.",
                                              tool_call_id=llamada["id"], name=llamada["name"], status="error"))
                    continue
                if catalogo.herramienta(ref).get("requiere_confirmacion"):
                    pendiente = {"ref": ref, "nombre": llamada["name"], "args": llamada["args"]}
                    trazas.registrar_span(ctx, "herramienta", ref, estado="retenida", detalle={"args": llamada["args"]})
                    escribir({"tipo": "pendiente", "ref": ref})
                    salida.append(ToolMessage(
                        content="NO EJECUTADA: requiere confirmación del usuario. La plataforma ya se la pidió.",
                        tool_call_id=llamada["id"], name=llamada["name"]))
                    continue
                del_usuario = [x for x in estado["messages"] if isinstance(x, HumanMessage)]
                contenido = await self._ejecutar(ctx, ref, dict(llamada["args"]), sesion, escribir, del_usuario)
                salida.append(ToolMessage(content=contenido, tool_call_id=llamada["id"], name=llamada["name"]))

            cambios = {"messages": salida}
            if pendiente:
                h = catalogo.herramienta(pendiente["ref"])
                detalle = "; ".join(f"{k}: {v}" for k, v in pendiente["args"].items())
                cambios["pendiente"] = pendiente
                cambios["messages"].append(_mensaje_plataforma(
                    f"Antes de continuar necesito tu confirmación. Voy a: {h['para_que']}\n\n"
                    f"Datos: {detalle}\n\n¿Confirmas? Responde sí o no."
                ))
            return cambios

        def tras_herramientas(estado: Estado) -> str:
            return "salida" if estado.get("pendiente") else "agente"

        async def salida(estado: Estado, config) -> dict:
            ctx = self.ctx(config["configurable"]["thread_id"])
            escribir = get_stream_writer()
            ultimo = estado["messages"][-1]
            texto = str(ultimo.content).strip()

            if ultimo.additional_kwargs.get("plataforma"):
                for bloque in guards.dividir_en_bloques(texto):
                    escribir({"tipo": "bloque", "texto": bloque})
                return {"respuesta_final": texto, "reintentar": False, "nota": ""}

            fuentes = [str(x.content) for x in estado["messages"] if isinstance(x, (ToolMessage, HumanMessage))]
            cliente = (estado.get("sesion") or {}).get("cliente_id")
            bloques = guards.dividir_en_bloques(texto) or [""]
            dicho = " ".join(str(x.content) for x in estado["messages"] if isinstance(x, HumanMessage))
            # ¿Se ejecutó con éxito alguna escritura en esta conversación? Si no,
            # el agente no puede decir que algo quedó guardado o creado.
            escrituras = {t.mcp.split("/", 1)[1] for t in m.spec.tools if catalogo.herramienta(t.mcp)["tipo"] == "escritura"}
            hubo_escritura = any(
                isinstance(x, ToolMessage) and x.name in escrituras and x.content.startswith("<dato_no_confiable")
                for x in estado["messages"])
            revisiones = [guards.revisar_bloque(b, m, fuentes, cliente, dicho, hubo_escritura) for b in bloques]
            problemas = [(i, p) for i, p in enumerate(revisiones) if p]

            if problemas and estado.get("correcciones", 0) == 0 and not any("pii_ajena" in p for _, p in problemas):
                # Una sola oportunidad de corregir antes de emitir nada.
                detalle = {k: v for _, p in problemas for k, v in p.items()}
                trazas.registrar_span(ctx, "guard", "guard_salida", estado="reintento", detalle=detalle)
                escribir({"tipo": "guard", "capa": "salida", "motivo": "reintento", "detalle": detalle})
                return {
                    "correcciones": 1,
                    "reintentar": True,
                    "messages": [RemoveMessage(id=ultimo.id)],
                    "nota": (
                        "Revisión de la plataforma: tu respuesta no se envió. "
                        + (f"Estas cifras no aparecen en ningún resultado de herramienta: "
                           f"{', '.join(detalle['cifras_no_verificadas'])}. Reescribe la respuesta SIN esas cifras; "
                           "usa solo números copiados tal cual de los resultados. "
                           if "cifras_no_verificadas" in detalle else "")
                        + ("No prometas descuentos ni acuerdos: ofrece abrir un caso con un asesor. "
                           if "promesas" in detalle else "")
                        + ("No digas que algo quedó guardado o creado: ninguna herramienta de escritura se ejecutó. "
                           "Si hace falta, llámala; la plataforma pedirá confirmación. "
                           if "afirmacion_sin_accion" in detalle else "")
                    ),
                }

            emitidos = []
            for bloque, revision in zip(bloques, revisiones):
                if revision:
                    tipo = next(iter(revision))
                    emitidos.append(guards.RESPUESTA_SEGURA[tipo])
                    trazas.registrar_span(ctx, "guard", "guard_salida", estado="bloqueo", detalle=revision)
                    escribir({"tipo": "guard", "capa": "salida", "motivo": tipo, "detalle": revision})
                    if tipo == "pii_ajena" and self.entorno == "produccion":
                        # Intento de fuga de datos = incidente. El guard lo
                        # detuvo, pero el agente queda suspendido hasta revisarlo.
                        registro.suspender(m.id, m.version, f"incidente de datos: {revision['pii_ajena']}")
                        trazas.registrar_span(ctx, "evento", "incidente_suspension", estado="error", detalle=revision)
                    break
                emitidos.append(bloque)
            final = "\n\n".join(emitidos)
            for bloque in emitidos:
                escribir({"tipo": "bloque", "texto": bloque})
            return {"respuesta_final": final, "correcciones": 0, "reintentar": False, "nota": "",
                    "messages": [AIMessage(content=final, id=ultimo.id)]}

        def tras_salida(estado: Estado) -> str:
            # Bandera explícita y no "hay nota": una primera versión miraba la
            # nota, que no se limpiaba cuando el agente llegaba al tope de
            # iteraciones, y el grafo quedaba en bucle hasta el límite de LangGraph.
            return "agente" if estado.get("reintentar") else END

        g.add_node("guard_entrada", guard_entrada)
        g.add_node("recuperar", recuperar)
        g.add_node("agente", agente)
        g.add_node("herramientas", herramientas)
        g.add_node("salida", salida)
        g.add_edge(START, "guard_entrada")
        g.add_conditional_edges("guard_entrada", tras_entrada, ["recuperar", "agente", "herramientas", "salida"])
        g.add_edge("recuperar", "agente")
        g.add_conditional_edges("agente", tras_agente, ["herramientas", "salida"])
        g.add_conditional_edges("herramientas", tras_herramientas, ["agente", "salida"])
        g.add_conditional_edges("salida", tras_salida, ["agente", END])
        # Memoria de la conversación en proceso. En producción, el checkpointer
        # de PostgreSQL: la conversación se reanuda después de una aprobación.
        return g.compile(checkpointer=InMemorySaver())

    async def _razonar(self, ctx: dict, mensajes: list, estado: Estado) -> AIMessage:
        """Una llamada al modelo más las correcciones de formato que ya medimos
        con modelos locales: tool call escrito como texto, acción narrada sin
        ejecutar y respuesta vacía. Todas pasan por el gateway (y su presupuesto)."""
        resp = await gateway().chat(ctx, mensajes, alias=self.m.spec.model.alias, fallback=self.m.spec.model.fallback,
                                    herramientas=self._esquemas or None, nombre="agente")
        if not resp.tool_calls and (recuperado := _tool_call_desde_texto(str(resp.content))):
            resp = AIMessage(content="", tool_calls=[recuperado], id=resp.id)
        if not resp.tool_calls and self._esquemas and _NARRA_ACCION.search(str(resp.content)) and not estado.get("nota"):
            trazas.registrar_span(ctx, "evento", "accion_narrada", estado="reintento",
                                  detalle={"respuesta": str(resp.content)[:200]})
            mensajes += [resp, _indicacion(
                "Dijiste que ibas a consultar algo pero no llamaste ninguna herramienta. No lo anuncies ni pidas "
                "permiso: llama ahora la herramienta que corresponde y responde con su resultado.")]
            resp = await gateway().chat(ctx, mensajes, alias=self.m.spec.model.alias, fallback=self.m.spec.model.fallback,
                                        herramientas=self._esquemas or None, nombre="agente")
        if not resp.tool_calls and not str(resp.content).strip():
            # qwen2.5 en Ollama a veces emite un tool call mal formado que el
            # parser de Ollama descarta en silencio: llegan cero caracteres
            # aunque el modelo generó ~100 tokens. Medido: un reintento con
            # esta indicación lo resuelve en los casos que reproduje.
            trazas.registrar_span(ctx, "evento", "respuesta_vacia", estado="reintento")
            mensajes.append(_indicacion(
                "Tu respuesta anterior llegó vacía. Si necesitas una herramienta, llámala usando el "
                "mecanismo de herramientas; si no, responde al usuario con texto."))
            resp = await gateway().chat(ctx, mensajes, alias=self.m.spec.model.alias, fallback=self.m.spec.model.fallback,
                                        herramientas=self._esquemas or None, nombre="agente")
        return resp

    async def _ejecutar(self, ctx: dict, ref: str, args: dict, sesion: dict, escribir, mensajes_usuario=()) -> str:
        """Inyecta los parámetros de plataforma, llama al MCP y envuelve el resultado."""
        # Lo que haya puesto el modelo en estos parámetros se sobrescribe.
        for parametro, fuente in catalogo.herramienta(ref).get("inyectados", {}).items():
            if fuente.startswith("sesion."):
                valor = sesion.get(fuente.removeprefix("sesion."))
                if not valor:
                    return f"ERROR: la sesión no tiene {fuente.removeprefix('sesion.')} autenticado."
                args[parametro] = valor
            elif fuente == "manifiesto.knowledge":
                args[parametro] = list(self.m.spec.knowledge)
            elif fuente == "conversacion.usuario":
                args[parametro] = " ".join(str(x.content) for x in mensajes_usuario)
            elif fuente == "runtime":
                args[parametro] = {k: ctx[k] for k in ("agente", "version", "area", "entorno", "conversacion")}

        with trazas.medir(ctx, "herramienta", ref) as span:
            span["detalle"] = {"args": {k: v for k, v in args.items() if k not in ("traza", "dicho_por_usuario")}}
            try:
                texto = await self.conexiones.llamar(ref, args)
            except Exception as exc:  # noqa: BLE001 — un error de herramienta es un mensaje, no una caída
                span["estado"] = "error"
                span["detalle"]["error"] = str(exc)[:300]
                escribir({"tipo": "herramienta", "ref": ref, "estado": "error"})
                # El texto le pide al modelo corregir y reintentar. Medido: ante
                # un error de validación (periodo enviado como objeto), el
                # modelo se disculpaba con el usuario en vez de corregir.
                return (f"ERROR de la herramienta {ref}: {exc}\n"
                        "Corrige los argumentos según la descripción de la herramienta y vuelve a llamarla.")
            span["detalle"]["caracteres"] = len(texto)
            if texto.startswith('{"error"'):
                span["estado"] = "rechazada"  # la herramienta respondió, pero dijo que no
                span["detalle"]["error"] = texto[:300]
        escribir({"tipo": "herramienta", "ref": ref, "estado": "ok"})
        return f'<dato_no_confiable fuente="{ref}">\n{texto}\n</dato_no_confiable>'

    # ── Uso ──────────────────────────────────────────────────────────────

    async def responder(self, texto: str, sesion: dict, conversacion: str):
        """Genera eventos del turno: bloques validados, herramientas, guards."""
        config = {"configurable": {"thread_id": conversacion}}
        entrada = {"messages": [HumanMessage(content=texto)], "sesion": sesion}
        async for evento in self._grafo.astream(entrada, config, stream_mode="custom"):
            yield evento

    async def turno(self, texto: str, sesion: dict, conversacion: str | None = None) -> ResultadoTurno:
        conversacion = conversacion or uuid.uuid4().hex
        r = ResultadoTurno(conversacion=conversacion)
        async for ev in self.responder(texto, sesion, conversacion):
            if ev["tipo"] == "herramienta":
                r.herramientas.append(ev["ref"])
            elif ev["tipo"] == "pendiente":
                r.pendiente = ev["ref"]
            elif ev["tipo"] == "guard" and ev["capa"] == "entrada":
                r.bloqueado = ev["motivo"]
            elif ev["tipo"] == "guard":
                r.guard_salida.append(ev)
        estado = await self._grafo.aget_state({"configurable": {"thread_id": conversacion}})
        r.respuesta = estado.values.get("respuesta_final", "")
        return r


async def abrir(id_agente: str, conexiones: Conexiones, *, entorno: str = "produccion",
                version: str | None = None) -> Agente:
    """Producción solo abre agentes publicados: es el único camino (P2).
    El sandbox y la compuerta pueden abrir borradores."""
    if entorno == "produccion":
        m = registro.obtener_publicado(id_agente)
    else:
        m, _ = registro.obtener(id_agente, version)
    agente = await Agente(m, conexiones, entorno).preparar()
    if m.metadata.archetype == "asistente-de-plataforma":
        # El Arquitecto enruta: preguntas al agente, creación al flujo determinista.
        from plataforma.arquitecto import Arquitecto

        return Arquitecto(agente)
    return agente
