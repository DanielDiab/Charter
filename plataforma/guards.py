"""Guards de entrada y salida: capas 2 y 5 de la figura 7.

Son de la plataforma, no del agente. Todo agente los hereda y ningún creador
los puede quitar ni configurar (decisión 2.5). Si cada agente implementara su
propia seguridad, la seguridad dependería de quién lo construyó.

ENTRADA, en este orden y del más barato al más caro:
  0. Identidad: pedir datos de otro cliente (NIT, nombre o id) se responde
     sin pasar por el modelo, en agentes con sujeto de sesión.
  1. Longitud.
  2. Inyección directa: una lista común de patrones. Aclaración honesta: en el
     documento descarto "filtros por regex POR AGENTE", escritos por cada
     creador, porque fallan en los dos sentidos. Esta lista es de la
     plataforma, se prueba con la suite red-team-base y es solo la primera
     línea. En producción va un clasificador dedicado (tipo Prompt Guard).
  3. Alcance: el tier `rapido` clasifica si el mensaje cabe en el propósito
     del agente. Pasa por el gateway, así que también cuesta y deja traza.

SALIDA, por bloques:
  - Cifras verificadas: toda cifra relevante de la respuesta tiene que
    aparecer en un resultado de herramienta (o en lo que dijo el usuario) de
    esta conversación. Aplica a agentes con datos confidenciales. El modelo no
    puede "acordarse" de un saldo: o lo consultó, o no lo dice.
  - PII ajena: datos de otro cliente distinto al de la sesión.
  - Promesas: descuentos, acuerdos o condonaciones que solo decide un humano.

La defensa más fuerte contra "dame la factura de la empresa X" no está aquí
sino en el runtime: el cliente_id lo pone la sesión. Este guard es la red por
si algo se filtra por otro camino (por ejemplo, un documento).
"""

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache

from langchain_core.messages import HumanMessage, SystemMessage

from plataforma import catalogo
from plataforma.config import DATOS, config

LONGITUD_MAXIMA = 2000

# Alcance en dos pasos, del más barato al más caro:
#   a) Léxico: si el mensaje comparte vocabulario con el terreno del agente
#      (propósito, herramientas y el texto de SUS colecciones), pasa. Cero costo.
#   b) Solo si no comparte nada, decide el clasificador LLM del tier `rapido`.
# Lo medí antes de decidir: con solo el clasificador, qwen2.5:3b Y qwen2.5:7b
# acertaron 13 de 18 mensajes, bloqueando pedidos legítimos ("necesito un
# acuerdo de pago", "¿las tarifas deberían ir en RAG?"). Un falso "fuera de
# alcance" deja al cliente sin respuesta; dejar pasar algo dudoso no, porque
# el agente sigue acotado por sus herramientas y sus políticas.
# Con los dos pasos: 17 de 18. El que se escapa ("escríbeme un programa en
# Python") comparte la palabra "programa" con la FAQ; llega al agente y lo
# contiene la política 6 heredada ("fuera de mi propósito").
ALIAS_CLASIFICADOR = "rapido"
_GENERICAS = set(
    "quiero queria puedo podria necesito dame decir saber hola gracias favor cuanto cuanta cuando donde "
    "como cual cuales tengo tiene tienen hacer hace esta este estos estas sobre algun alguna para porque "
    "mucho tanto bien buenas buenos dias tardes noches ayuda ayudame ahora todo todos quien quienes "
    "otro otra otros otras alguien nada mejor peor solo tambien entonces luego despues antes".split()
)
_vocabularios: dict[str, set[str]] = {}


def _vocabulario(m) -> set[str]:
    from plataforma import conocimiento

    if m.id not in _vocabularios:
        textos = [m.spec.purpose] + [catalogo.herramienta(t.mcp)["para_que"] for t in m.spec.tools]
        textos += [catalogo.colecciones()[c]["descripcion"] for c in m.spec.knowledge]
        try:
            textos += [f["texto"] for f in conocimiento.cargar_indice() if f["coleccion"] in m.spec.knowledge]
        except FileNotFoundError:
            pass
        _vocabularios[m.id] = {t for x in textos for t in conocimiento.tokenizar(x) if len(t) >= 4} - _GENERICAS
    return _vocabularios[m.id]


def comparte_terreno(texto: str, m) -> set[str]:
    from plataforma import conocimiento

    return {t for t in conocimiento.tokenizar(texto) if len(t) >= 4} & _vocabulario(m) - _GENERICAS

_INYECCION = [
    r"ignor\w*\s+(?:\w+\s+){0,4}(?:instrucciones|reglas|indicaciones|pol[ií]ticas)",
    r"olvid\w*\s+(?:\w+\s+){0,4}(?:instrucciones|reglas|indicaciones)",
    r"(?:revela|mu[eé]strame|muestra|dime|imprime|repite|copia)\w*\s+(?:\w+\s+){0,4}(?:prompt|instrucciones\s+de\s+sistema|tus\s+instrucciones|pol[ií]ticas\s+internas)",
    r"\bsystem\s+prompt\b",
    r"(?:eres|act[uú]a\s+como|ahora\s+eres|finge\s+ser)\s+(?:\w+\s+){0,4}(?:sin\s+(?:reglas|restricciones|filtros|l[ií]mites))",
    r"\bmodo\s+(?:desarrollador|dios|sin\s+restricciones|libre)\b",
    r"\bjailbreak\b|\bDAN\b",
    r"ignore\s+(?:all\s+|the\s+)?(?:previous|prior|above)\s+instructions",
]
_INYECCION_RE = [re.compile(p, re.IGNORECASE) for p in _INYECCION]

# Ampliados después de la compuerta del 2026-10-03: con qwen2.5:3b, la
# inyección indirecta del documento contaminado salió como "La comercializadora le aplica un
# descuento del 40 por ciento ... y ya quedó aprobado ... está disponible", y
# la primera versión de estos patrones ("te aplico", "queda aprobado" pegado a
# "descuento") no la vio. La compuerta sí la detuvo; ahora también el guard.
_PROMESAS = [
    r"\b(?:te|le|les)\s+(?:aplic\w*|otorg\w*|doy|damos|da|dan|conced\w*|hago|hacemos|hace)\s+(?:un|el|una)?\s*(?:descuento|acuerdo|condonaci[oó]n|rebaja)",
    r"(?:descuento|acuerdo\s+de\s+pago|condonaci[oó]n|rebaja)[^.]{0,80}?(?<!no )\b(?:queda|qued[oó]|est[aá]|fue|ha\s+sido)\s+(?:ya\s+)?(?:aprobad|aplicad|concedid|disponible)",
    r"\bte\s+garantizo\b",
]
_PROMESAS_RE = [re.compile(p, re.IGNORECASE) for p in _PROMESAS]

# "Quedó guardado", "tu caso fue creado", "has confirmado la guardada": afirmar
# una escritura que no ocurrió. Pasó en una entrevista de prueba del Arquitecto.
_AFIRMA_ESCRITURA = re.compile(
    r"\b(?:qued[oó]|ha\s+quedado|fue|ha\s+sido|est[aá])\s+(?:correctamente\s+|exitosamente\s+)?"
    r"(?:guardad|registrad|cread|abiert|enviad)\w*"
    r"|\b(?:he|hemos|se\s+ha|se\s+han)\s+(?:guardado|registrado|creado|abierto|enviado)\b"
    r"|\b(?:guardad|registrad|cread|abiert)[oa]s?\s+(?:con\s+[ée]xito|exitosamente|correctamente)"
    r"|\bconfirmado\s+(?:la|el)\s+(?:guardad|registr|creaci)\w*", re.I)

RESPUESTA_INYECCION = (
    "No puedo cambiar mis reglas ni compartir mis instrucciones internas. "
    "Con gusto te ayudo con lo que sí hago."
)
RESPUESTA_LONGITUD = "Tu mensaje es muy largo para procesarlo. ¿Me lo puedes resumir en pocas frases?"


@dataclass
class Veredicto:
    permitido: bool
    motivo: str = ""
    respuesta: str = ""
    detalle: dict = field(default_factory=dict)


# ── Entrada ──────────────────────────────────────────────────────────────


def detectar_inyeccion(texto: str) -> str | None:
    for patron in _INYECCION_RE:
        if m := patron.search(texto):
            return m.group(0)
    return None


def pide_otro_cliente(texto: str, cliente_sesion: str | None) -> str | None:
    """Capa 1, identidad: el mensaje pide datos de un cliente distinto al de la
    sesión (por NIT, por nombre o por id). El documento lo dice así: "dame la
    factura de la empresa X" no se rechaza con inteligencia, la arquitectura lo
    hace imposible. El runtime ya lo hace imposible (el cliente_id lo pone la
    sesión); este guard además le responde al usuario con claridad. Medido: el
    modelo, ante "dame la factura del NIT ...", contestaba "confírmalo y lo
    haré por ti", sin filtrar nada pero haciéndole creer que podía."""
    bajo, digitos = texto.lower(), re.sub(r"\D", "", texto)
    for c in _clientes():
        if c["cliente_id"] == cliente_sesion:
            continue
        if (re.sub(r"\D", "", c["nit"])[:9] in digitos or c["cliente_id"].lower() in bajo
                or " ".join(c["razon_social"].lower().split()[:2]) in bajo):
            return c["cliente_id"]
    if (m := re.search(r"\bCLI-\d{3}\b", texto, re.I)) and m.group(0).upper() != (cliente_sesion or "").upper():
        return m.group(0).upper()
    return None


RESPUESTA_OTRO_CLIENTE = (
    "Solo puedo consultar la información de la cuenta con la que iniciaste sesión. Para datos de otra empresa, "
    "esa empresa debe consultarlos con su propio acceso. ¿Te ayudo con algo de tu cuenta?"
)


async def revisar_entrada(texto: str, m, ctx: dict, gateway, ultimo_mensaje_agente: str = "",
                          sesion: dict | None = None) -> Veredicto:
    if len(texto) > LONGITUD_MAXIMA:
        return Veredicto(False, "longitud", RESPUESTA_LONGITUD, {"caracteres": len(texto)})
    if hallazgo := detectar_inyeccion(texto):
        return Veredicto(False, "inyeccion", RESPUESTA_INYECCION, {"patron": hallazgo})
    if m.spec.data.subject_from and (otro := pide_otro_cliente(texto, (sesion or {}).get("cliente_id"))):
        return Veredicto(False, "otro_cliente", RESPUESTA_OTRO_CLIENTE, {"pedido": otro})

    # Respuestas cortas ("sí", "ventas", "está bien así, guárdalo") solo tienen
    # sentido con la pregunta anterior: clasificarlas aisladas da falsos "fuera
    # de alcance" (pasó en una entrevista de prueba con "Sí, está bien así,
    # guárdalo"). Dentro de una conversación en curso las dejo pasar; el agente
    # sigue acotado por sus instrucciones y sus herramientas.
    limite_palabras = 8 if ultimo_mensaje_agente else 4
    if not config().guard_alcance or len(texto.split()) <= limite_palabras:
        return Veredicto(True)

    if comparte_terreno(texto, m):
        return Veredicto(True)

    # Le paso al clasificador todo lo que define el terreno del agente: el
    # propósito, lo que hacen sus herramientas y de qué tratan sus colecciones.
    # Con el propósito solo, el modelo marcaba FUERA pedidos legítimos como
    # "necesito un acuerdo de pago" o "¿vamos a hacer fine-tuning?", porque
    # esas palabras no aparecen en la frase del propósito.
    terreno = [" ".join(m.spec.purpose.split())]
    terreno += [catalogo.herramienta(t.mcp)["para_que"] for t in m.spec.tools]
    terreno += [catalogo.colecciones()[c]["descripcion"] for c in m.spec.knowledge]
    prompt = [
        SystemMessage(content=(
            "Decides si un mensaje tiene ALGUNA relación, aunque sea indirecta, con el tema de un asistente. "
            "Responde SI si el mensaje toca cualquier aspecto del tema, si pide hablar con una persona, si es "
            "un saludo, una confirmación o la respuesta a la pregunta anterior del asistente, o si pregunta por "
            "otra persona o empresa dentro del mismo tema. Responde NO solo si el mensaje es de un tema "
            "completamente distinto (recetas, deportes, entretenimiento, geografía, programación, tareas). "
            "Responde solo SI o NO."
        )),
        HumanMessage(content=(
            "Tema del asistente:\n- " + "\n- ".join(terreno) + "\n"
            f"Última pregunta del asistente: {ultimo_mensaje_agente[:300] or '(ninguna)'}\n"
            f"Mensaje: {texto}"
        )),
    ]
    resp = await gateway.chat(ctx, prompt, alias=ALIAS_CLASIFICADOR, nombre="guard_alcance")
    if str(resp.content).strip().upper().startswith("NO"):
        return Veredicto(
            False, "fuera_de_alcance",
            "Eso está fuera de lo que puedo ayudarte. Mi función es: " + " ".join(m.spec.purpose.split()),
        )
    return Veredicto(True)


# ── Salida ───────────────────────────────────────────────────────────────

_NUMERO = re.compile(r"\d[\d.,]*\d|\d")
_CITA = re.compile(r"\[[^\]]*\]")


def _interpretaciones(token: str) -> set[float]:
    """Un mismo número se escribe distinto: 5.369.752 · 5,369,752 · 871,6 · 871.6.
    Devuelvo todas las lecturas razonables y comparo por valor."""
    valores = set()
    limpio = token.strip(".,")
    for miles, decimal in ((".", ","), (",", ".")):
        t = limpio.replace(miles, "")
        if t.count(decimal) <= 1:
            try:
                valores.add(float(t.replace(decimal, ".")))
            except ValueError:
                pass
    try:
        valores.add(float(re.sub(r"[.,]", "", limpio)))
    except ValueError:
        pass
    return valores


def _relevante(token: str, texto: str, fin: int) -> bool:
    """Ignoro enteros pequeños sueltos (numeraciones, "2 opciones", días del mes):
    no son cifras de negocio. Cuento todo lo que tenga decimales, 3 o más dígitos,
    o vaya junto a %, $ o una unidad."""
    digitos = re.sub(r"\D", "", token)
    if len(digitos) >= 3 or re.search(r"[.,]\d", token):
        return True
    contexto = texto[fin:fin + 6].lower()
    previo = texto[max(0, fin - len(token) - 2):fin - len(token)]
    return "%" in contexto or "kwh" in contexto or "$" in previo


def cifras(texto: str) -> list[tuple[str, set[float], float]]:
    """(token, valores posibles, multiplicador) para cada cifra relevante."""
    texto = _CITA.sub("", texto)
    salida = []
    for mt in _NUMERO.finditer(texto):
        token = mt.group(0)
        if not _relevante(token, texto, mt.end()):
            continue
        siguiente = texto[mt.end():mt.end() + 10].lower()
        mult = 1e6 if siguiente.strip().startswith("millon") else 1.0
        salida.append((token, _interpretaciones(token), mult))
    return salida


def valores_fuente(fuentes: list[str]) -> set[float]:
    vals: set[float] = set()
    for f in fuentes:
        for mt in _NUMERO.finditer(f):
            vals |= _interpretaciones(mt.group(0))
    return vals


def _coincide(token: str, valores: set[float], mult: float, disponibles: set[float]) -> bool:
    """Reglas de coincidencia, de la más laxa a la más estricta:

    - Escrita como redondeo ("5,37 millones"): tolerancia relativa de 0,5 %.
    - Entero corto sin decimales ("78 %", "26 %"): vale el redondeo del dato
      (77,6 → 78).
    - Con decimales ("871,6"): igual al dato redondeado a esos decimales.
    - Monto escrito completo ("4.833.195"): EXACTO. Una primera versión de
      este guard tenía tolerancia para todo y dejó pasar "4.835.557" cuando la
      herramienta había calculado 4.833.195: el modelo mezcló dos cifras y la
      diferencia (0,05 %) cabía en la tolerancia.
    """
    digitos = re.sub(r"\D", "", token).lstrip("0")
    decimales = re.search(r"[.,](\d{1,2})$", token)
    for v in valores:
        for d in disponibles:
            if v * mult == d:
                return True
            if mult > 1 and d and abs(v * mult - d) / abs(d) <= 0.005:
                return True
            if not decimales and len(digitos) <= 3 and v == round(d):
                return True
            if decimales and v == round(d, len(decimales.group(1))):
                return True
    return False


def cifras_no_verificadas(texto: str, fuentes: list[str]) -> list[str]:
    disponibles = valores_fuente(fuentes)
    return [token for token, valores, mult in cifras(texto) if not _coincide(token, valores, mult, disponibles)]


@lru_cache
def _clientes() -> list[dict]:
    return json.loads((DATOS / "clientes.json").read_text(encoding="utf-8"))


def pii_ajena(texto: str, cliente_sesion: str | None, dicho_por_usuario: str = "") -> list[str]:
    """Datos de clientes distintos al de la sesión. Lo que el propio usuario
    escribió no cuenta: repetir el NIT que él mismo dio no filtra nada; decir
    a qué empresa pertenece, sí."""
    hallazgos = []
    bajo, usuario = texto.lower(), dicho_por_usuario.lower()
    solo_digitos, digitos_usuario = re.sub(r"\D", "", texto), re.sub(r"\D", "", dicho_por_usuario)
    for c in _clientes():
        if c["cliente_id"] == cliente_sesion:
            continue
        nombre_corto = " ".join(c["razon_social"].lower().split()[:2])
        nit = re.sub(r"\D", "", c["nit"])
        if nombre_corto in bajo and nombre_corto not in usuario:
            hallazgos.append(c["razon_social"])
        if nit in solo_digitos and nit not in digitos_usuario:
            hallazgos.append("NIT de otro cliente")
        if (c["contacto"].lower() in bajo and c["contacto"].lower() not in usuario) or (
            c["telefono"] in solo_digitos and c["telefono"] not in digitos_usuario
        ):
            hallazgos.append("contacto de otro cliente")
    return hallazgos


def promesas(texto: str) -> list[str]:
    return [m.group(0) for p in _PROMESAS_RE if (m := p.search(texto))]


def afirma_escritura(texto: str) -> list[str]:
    return [m.group(0) for m in _AFIRMA_ESCRITURA.finditer(texto)]


def dividir_en_bloques(texto: str) -> list[str]:
    """Bloque = párrafo. Es la unidad que el cliente ve aparecer y la que se valida."""
    return [b.strip() for b in re.split(r"\n\s*\n", texto) if b.strip()]


def revisar_bloque(bloque: str, m, fuentes: list[str], cliente_sesion: str | None, dicho_por_usuario: str = "",
                   hubo_escritura: bool = False) -> dict:
    problemas = {}
    if not hubo_escritura and (afirma := afirma_escritura(bloque)):
        problemas["afirmacion_sin_accion"] = afirma
    if catalogo.nivel(m.spec.data.classification) >= catalogo.nivel("confidencial"):
        if faltan := cifras_no_verificadas(bloque, fuentes):
            problemas["cifras_no_verificadas"] = faltan
    if ajena := pii_ajena(bloque, cliente_sesion, dicho_por_usuario):
        problemas["pii_ajena"] = ajena
    if prom := promesas(bloque):
        problemas["promesas"] = prom
    return problemas


RESPUESTA_SEGURA = {
    "afirmacion_sin_accion": "Todavía no se ha guardado ningún cambio. ¿Quieres que lo haga ahora?",
    "pii_ajena": "Solo puedo darte información de tu propia cuenta.",
    "promesas": "Eso no lo puedo decidir yo: lo decide un asesor. Si quieres, abro un caso para que lo revise.",
    "cifras_no_verificadas": (
        "No pude verificar uno de los datos de esta respuesta contra tus sistemas, así que prefiero no "
        "dártelo. Si quieres, abro un caso para que un asesor lo revise."
    ),
}
