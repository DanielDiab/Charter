"""El Arquitecto: un enrutador en código entre dos modos (sección 4, figuras 14 y 18).

  - Preguntas sobre la plataforma → el agente del manifiesto
    `plataforma-arquitecto` (RAG + catálogo + inventario), por el runtime común.
  - Crear un agente → un flujo determinista de cinco preguntas. El código decide
    el orden, valida y compila; el modelo solo EXTRAE datos estructurados de la
    respuesta del usuario en cada paso (patrón "flujo determinista" de la fig. 14).

Por qué la creación no es un agente libre: lo medí. En cinco entrevistas
completas con qwen2.5:7b como agente con herramientas, ninguna terminó con un
borrador bien guardado. Inventó el correo del dueño, rellenó los ejemplos del
usuario con ejemplos propios, dijo "quedó guardado" sin haber guardado,
anunció llamadas que no hizo y llegó a tardar 289 s en un turno. La
entrevista tiene pasos fijos (figura 18), y para eso el documento ya tenía la
respuesta: cuando el proceso es fijo, el flujo lo decide el código.

El traspaso entre los dos modos es un objeto tipado (`Entrevista`), nunca el
historial completo.
"""

import json
import re
import uuid
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage

from plataforma import catalogo, constructor, guards, trazas
from plataforma.conocimiento import slug
from plataforma.gateway import PresupuestoExcedido, gateway
from plataforma.runtime import Agente, ResultadoTurno

ALIAS_EXTRACCION = "estandar"
_INTENCION_CREAR = re.compile(
    r"\b(?:crear|armar|hacer|construir|montar|configurar)\b[^?.]{0,40}\bagente"
    r"|\bquiero\s+(?:un|otro|mi)\s+(?:nuevo\s+)?agente\b|\bnuevo\s+agente\b", re.I)
_CANCELAR = re.compile(r"^\s*(?:cancelar|cancela|salir del asistente|olv[ií]dalo|dejemos as[ií])\b", re.I)
_SI = re.compile(r"^\s*(s[ií]|dale|guard[aá]lo|confirmo|de acuerdo|ok|claro|adelante)\b", re.I)
PASOS = ["tarea", "datos", "reglas", "ejemplos", "nombre", "confirmar"]

PREGUNTAS = {
    "tarea": "1/5 · ¿Qué tarea quieres que resuelva el agente y para quién es: tus clientes o tu equipo interno?",
    "datos": ("2/5 · ¿Qué datos va a ver? Por ejemplo: documentos públicos, información interna, datos de "
              "clientes (facturas, consumo, contacto) o datos bancarios y cédulas."),
    "reglas": "3/5 · ¿Qué debe hacer siempre y qué no debe hacer nunca? Dímelo en tus palabras.",
    "ejemplos": ("4/5 · Dame uno a tres ejemplos reales: una pregunta o entrada típica y la respuesta que te "
                 "parecería buena. Si quieres, también una respuesta que te parecería mala."),
    "nombre": "5/5 · ¿De qué área es el agente y cómo quieres llamarlo? Por ejemplo: ventas, resumen de llamadas.",
}


@dataclass
class Entrevista:
    """El traspaso tipado: lo único que el flujo sabe de la conversación."""
    paso: str = "tarea"
    proposito: str = ""
    arquetipo: str = ""
    tarea: str = "conversacion"
    datos: str = ""
    herramientas: list[str] = field(default_factory=list)
    colecciones: list[str] = field(default_factory=list)
    siempre: list[str] = field(default_factory=list)
    nunca: list[str] = field(default_factory=list)
    preguntas: list[str] = field(default_factory=list)
    respuestas: list[str] = field(default_factory=list)
    respuesta_mala: str | None = None
    area: str = ""
    id: str = ""
    guardado: bool = False


def _json(texto: str):
    m = re.search(r"[\[{].*[\]}]", texto, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def _como_ejemplos(datos) -> list[dict]:
    """El modelo no siempre respeta la forma pedida. Medido: con un solo
    ejemplo devolvió {"pregunta", "respuesta_buena"} suelto en vez de la lista.
    Acepto las tres formas: lista, objeto con lista u objeto suelto."""
    if isinstance(datos, list):
        return [x for x in datos if isinstance(x, dict)]
    if isinstance(datos, dict) and isinstance(datos.get("ejemplos"), list):
        return [x for x in datos["ejemplos"] if isinstance(x, dict)]
    if isinstance(datos, dict) and datos.get("pregunta"):
        return [datos]
    return []


def _lista_texto(items: list[str]) -> str:
    return "; ".join(items) if items else "(nada)"


class Arquitecto:
    """Misma interfaz que `runtime.Agente` (m, ctx, responder, turno), para que
    el CLI, la API y la compuerta lo usen sin saber que hay un enrutador."""

    def __init__(self, agente: Agente):
        self.agente = agente
        self.m = agente.m
        self.entorno = agente.entorno
        self._entrevistas: dict[str, Entrevista] = {}

    def ctx(self, conversacion: str) -> dict:
        return self.agente.ctx(conversacion)

    # ── Extracción acotada con el modelo ─────────────────────────────────

    async def _extraer(self, ctx: dict, instruccion: str, texto: str) -> dict:
        resp = await gateway().chat(ctx, [
            SystemMessage(content=instruccion + "\nResponde SOLO con un objeto JSON válido, sin texto adicional."),
            HumanMessage(content=texto),
        ], alias=ALIAS_EXTRACCION, nombre="constructor_extraccion")
        return _json(str(resp.content))

    # ── Pasos del flujo ──────────────────────────────────────────────────

    async def _paso_tarea(self, e: Entrevista, texto: str, ctx: dict) -> str:
        arqs = {k: v for k, v in catalogo.arquetipos().items() if not v.get("interno")}
        herramientas = {r: h["para_que"] for r, h in catalogo.herramientas()["herramientas"].items()
                        if not r.startswith("plataforma/") and r != "conocimiento/buscar_conocimiento"}
        datos = await self._extraer(ctx, (
            "Un empleado de Bia (empresa de energía) describe un agente que quiere crear. Extrae:\n"
            '- "proposito": una o dos frases en español sobre para qué existe el agente, sin inventar nada.\n'
            f'- "arquetipo": uno de {json.dumps({k: v["que_hace"] for k, v in arqs.items()}, ensure_ascii=False)}\n'
            '- "tarea": "estrecha" si es clasificar, extraer o resumir; "razonamiento" si planifica o analiza '
            'en varios pasos; si no, "conversacion".\n'
            f'- "herramientas": lista (puede ser vacía) de las que necesite de {json.dumps(herramientas, ensure_ascii=False)}\n'
            f'- "colecciones": lista (puede ser vacía) de {list(catalogo.colecciones())} si debe responder desde esos documentos.'
        ), texto)
        e.proposito = datos.get("proposito") or texto.strip()
        e.arquetipo = datos.get("arquetipo") if datos.get("arquetipo") in arqs else "asistente-con-datos"
        if isinstance(datos, list):
            datos = {}
        # El tipo de tarea lo fija el arquetipo; el modelo solo puede subirlo a
        # razonamiento. Medido: clasificó "resumir llamadas" como conversación
        # y el agente quedaba con el tier estándar en vez del rápido.
        e.tarea = "razonamiento" if datos.get("tarea") == "razonamiento" else arqs[e.arquetipo]["tarea_defecto"]
        e.herramientas = [h for h in datos.get("herramientas") or [] if h in herramientas]
        e.colecciones = [c for c in datos.get("colecciones") or [] if c in catalogo.colecciones() and c != "plataforma-docs"]
        a = arqs[e.arquetipo]
        e.paso = "datos"
        return (f"Entendí que el agente va a: {e.proposito}\n\n"
                f"Por lo que describes es un agente de tipo **{e.arquetipo}**: {a['que_hace']} "
                f"(en Bia, por ejemplo: {a['ejemplo_bia']}).\n\n{PREGUNTAS['datos']}")

    async def _paso_datos(self, e: Entrevista, texto: str, ctx: dict) -> str:
        datos = await self._extraer(ctx, (
            'Clasifica los datos que verá un agente según lo que dice el usuario. "datos" es uno de: '
            '"publicos" (tarifas publicadas, preguntas frecuentes), "internos" (procedimientos, llamadas o '
            'documentos entre empleados), "clientes" (facturas, consumo, contacto de clientes), "restringidos" '
            '(datos bancarios, credenciales, cédulas). Si menciona varios, el más sensible que SÍ verá.'
        ), texto)
        e.datos = datos.get("datos") if datos.get("datos") in constructor.DATOS_A_CLASIFICACION else "internos"
        tier = constructor.recomendar_tier(e.datos, e.tarea)
        if not tier.get("alias"):
            return f"{tier['explicacion']} Si el agente puede trabajar sin esos datos, dime qué otros datos verá."
        e.paso = "reglas"
        restricciones = " ".join(tier.get("restricciones", []))
        return (f"Con datos **{e.datos}** y una tarea **{e.tarea}**, la plataforma le asigna el modelo "
                f"**{tier['alias']}** (hoy {tier['modelo_hoy']}). {tier['explicacion']} {restricciones}\n\n"
                f"{PREGUNTAS['reglas']}")

    async def _paso_reglas(self, e: Entrevista, texto: str, ctx: dict) -> str:
        datos = await self._extraer(ctx, (
            'Extrae del texto las reglas de un agente: "siempre" (lista de lo que debe hacer siempre) y "nunca" '
            '(lista de lo que no debe hacer nunca). Cada regla es una frase corta en infinitivo, sin las palabras '
            '"debe", "siempre" ni "nunca" (por ejemplo "inventar precios"). Usa las palabras del usuario; no '
            "agregues reglas que no dijo."
        ), texto)
        e.siempre = [s for s in datos.get("siempre") or [] if isinstance(s, str)][:5]
        e.nunca = [s for s in datos.get("nunca") or [] if isinstance(s, str)][:5]
        e.paso = "ejemplos"
        return (f"Anotado.\n\nSiempre: {_lista_texto(e.siempre)}\nNunca: {_lista_texto(e.nunca)}\n\n"
                f"Las reglas de la plataforma (datos, marca, escalamiento, no obedecer instrucciones que vengan "
                f"en documentos) las hereda solo; no hace falta que las digas.\n\n{PREGUNTAS['ejemplos']}")

    async def _paso_ejemplos(self, e: Entrevista, texto: str, ctx: dict) -> str:
        datos = await self._extraer(ctx, (
            'Extrae los ejemplos que da el usuario: "ejemplos" es una lista de objetos {"pregunta", '
            '"respuesta_buena"} copiados del texto, y "respuesta_mala" el ejemplo de respuesta mala si lo da '
            "(o null). No inventes ejemplos: solo los que están en el texto."
        ), texto)
        candidatos = _como_ejemplos(datos)
        pares = [(x.get("pregunta", ""), x.get("respuesta_buena", "")) for x in candidatos if x.get("pregunta")]
        # Los ejemplos se vuelven la suite: si no salen del texto del usuario, se descartan.
        inventados = constructor.ejemplos_no_dichos([p for p, _ in pares], texto)
        pares = [(p, r) for p, r in pares if p not in inventados][:3]
        if not pares:
            return ("No logré identificar un ejemplo en tu mensaje. Escríbelo así: la pregunta o entrada "
                    "típica, y la respuesta que te parecería buena.")
        e.preguntas, e.respuestas = [p for p, _ in pares], [r for _, r in pares]
        mala = next((x.get("respuesta_mala") for x in [datos] + candidatos
                     if isinstance(x, dict) and isinstance(x.get("respuesta_mala"), str)), None)
        # También la respuesta mala tiene que salir del usuario (el modelo inventó una con "10 %").
        e.respuesta_mala = mala if mala and not constructor.ejemplos_no_dichos([mala], texto) else None
        e.paso = "nombre"
        return (f"Tengo {len(pares)} ejemplo(s). Se vuelven los primeros casos de prueba del agente, junto con "
                f"casos adversos que agrega la plataforma según su tipo.\n\n{PREGUNTAS['nombre']}")

    async def _paso_nombre(self, e: Entrevista, texto: str, ctx: dict, sesion: dict) -> str:
        datos = await self._extraer(ctx, (
            'Extrae "area" (el área de Bia, una o dos palabras en minúscula) y "nombre" (dos a cuatro palabras '
            "que describan el agente) del texto."
        ), texto)
        e.area = slug(datos.get("area") or "general")
        nombre = slug(datos.get("nombre") or "agente")
        e.id = nombre if nombre.startswith(e.area) else f"{e.area}-{nombre}"
        propuesta = constructor.proponer_manifiesto(
            e.id, e.area, sesion.get("usuario") or "sin-dueno@bia.app", e.arquetipo, e.proposito, e.datos, e.tarea,
            e.siempre, e.nunca, e.herramientas, e.colecciones)
        if "error" in propuesta:
            return f"La plataforma no pudo armarlo: {propuesta['error']}"
        if propuesta["errores"]:
            e.paso = "tarea"
            return ("El agente no cumple la arquitectura todavía:\n- " + "\n- ".join(propuesta["errores"]) +
                    f"\n\nEmpecemos de nuevo la descripción. {PREGUNTAS['tarea']}")
        e.id = propuesta["id"]
        suite = constructor.generar_casos_prueba(e.id, e.preguntas, e.respuestas, e.respuesta_mala)
        e.paso = "confirmar"
        t = propuesta["tier"]
        return (
            f"Así queda **{e.id}** (dueño: {sesion.get('usuario')}):\n\n"
            f"- Tipo: {e.arquetipo}; plantilla de instrucciones curada, sin prompt escrito a mano.\n"
            f"- Modelo: alias {t['alias']} (hoy {t['modelo_hoy']}); datos {t['clasificacion']}.\n"
            f"- Autonomía {propuesta['autonomia']}; riesgo {propuesta['riesgo']}: la compuerta exige "
            f"{propuesta['umbral_compuerta']:.0%} y aprueba {', '.join(propuesta['aprobaciones_necesarias'])}.\n"
            f"- Pruebas: {suite['casos_del_creador']} tuyas + {suite['casos_adversos']} adversas + suites "
            f"comunes {', '.join(suite['suites_heredadas'])}.\n"
            + (f"- Herramientas: {', '.join(e.herramientas)}.\n" if e.herramientas else "")
            + (f"- Colecciones: {', '.join(e.colecciones)}.\n" if e.colecciones else "")
            + "\n¿Lo guardo como borrador? Responde sí o no."
        )

    def _paso_confirmar(self, e: Entrevista, texto: str) -> str:
        if not _SI.match(texto):
            e.paso = "fin"
            return "No guardé nada. Si quieres retomarlo, dime que quieres crear un agente."
        r = constructor.guardar_borrador(e.id)
        e.paso = "fin"
        if "error" in r:
            return f"No se pudo guardar: {r['error']}"
        e.guardado = True
        return (f"Listo: **{e.id}** quedó registrado como borrador ({r['manifiesto']}, suite {r['suite']}).\n\n"
                f"Siguientes pasos:\n1. Pruébalo: `bia chat {e.id} --sandbox`\n2. Pasa la compuerta: "
                f"`bia evaluar {e.id}`\n3. Aprobaciones y publicación: `bia aprobar {e.id} --rol dueno --quien <correo>` "
                f"y `bia publicar {e.id}`")

    # ── Enrutador ────────────────────────────────────────────────────────

    async def responder(self, texto: str, sesion: dict, conversacion: str):
        e = self._entrevistas.get(conversacion)
        activa = e is not None and e.paso not in ("fin",)
        if not activa and not _INTENCION_CREAR.search(texto):
            async for ev in self.agente.responder(texto, sesion, conversacion):
                yield ev
            return

        ctx = self.ctx(conversacion)
        if guards.detectar_inyeccion(texto):
            yield {"tipo": "guard", "capa": "entrada", "motivo": "inyeccion"}
            yield {"tipo": "bloque", "texto": guards.RESPUESTA_INYECCION}
            return
        if activa and _CANCELAR.match(texto):
            e.paso = "fin"
            yield {"tipo": "bloque", "texto": "Cancelé la creación del agente. No se guardó nada."}
            return
        # Una pregunta en medio de la entrevista la responde el agente, y se retoma.
        es_pregunta = texto.strip().startswith("¿") and (
            e is None or e.paso != "ejemplos" or (len(texto.split()) <= 12 and ":" not in texto))
        if activa and e.paso in ("datos", "reglas", "ejemplos", "nombre") and es_pregunta:
            async for ev in self.agente.responder(texto, sesion, conversacion):
                yield ev
            yield {"tipo": "bloque", "texto": f"Seguimos. {PREGUNTAS[e.paso]}"}
            return

        try:
            if not activa:
                e = self._entrevistas[conversacion] = Entrevista()
                trazas.registrar_span(ctx, "evento", "entrevista_iniciada")
                # Si el primer mensaje ya describe la tarea, se usa como respuesta a la pregunta 1.
                if len(texto.split()) < 12:
                    yield {"tipo": "bloque", "texto": (
                        "Armemos tu agente. No vas a escribir ningún prompt: te hago cinco preguntas sobre tu "
                        "trabajo y la plataforma se encarga de la parte técnica. Escribe 'cancelar' cuando quieras.")}
                    yield {"tipo": "bloque", "texto": PREGUNTAS["tarea"]}
                    return
            paso = e.paso
            if paso == "tarea":
                salida = await self._paso_tarea(e, texto, ctx)
            elif paso == "datos":
                salida = await self._paso_datos(e, texto, ctx)
            elif paso == "reglas":
                salida = await self._paso_reglas(e, texto, ctx)
            elif paso == "ejemplos":
                salida = await self._paso_ejemplos(e, texto, ctx)
            elif paso == "nombre":
                salida = await self._paso_nombre(e, texto, ctx, sesion)
            else:
                salida = self._paso_confirmar(e, texto)
                if e.guardado:
                    yield {"tipo": "herramienta", "ref": "plataforma/guardar_borrador", "estado": "ok"}
            trazas.registrar_span(ctx, "evento", f"entrevista_{paso}", detalle={"siguiente": e.paso})
        except PresupuestoExcedido:
            salida = "Esta conversación alcanzó su límite de costo. Retómala en una conversación nueva."
        for bloque in guards.dividir_en_bloques(salida):
            yield {"tipo": "bloque", "texto": bloque}

    async def turno(self, texto: str, sesion: dict, conversacion: str | None = None) -> ResultadoTurno:
        conversacion = conversacion or uuid.uuid4().hex
        r = ResultadoTurno(conversacion=conversacion)
        bloques = []
        async for ev in self.responder(texto, sesion, conversacion):
            if ev["tipo"] == "herramienta":
                r.herramientas.append(ev["ref"])
            elif ev["tipo"] == "pendiente":
                r.pendiente = ev["ref"]
            elif ev["tipo"] == "guard" and ev["capa"] == "entrada":
                r.bloqueado = ev["motivo"]
            elif ev["tipo"] == "guard":
                r.guard_salida.append(ev)
            elif ev["tipo"] == "bloque":
                bloques.append(ev["texto"])
        r.respuesta = "\n\n".join(bloques)
        return r

