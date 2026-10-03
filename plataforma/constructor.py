"""Constructor: convierte lo que sabe un empleado en un agente decente (sección 4).

El empleado aporta el negocio (tarea, qué está bien y mal, ejemplos). La
plataforma aporta la técnica: escoge el tier con el árbol de la figura 9, la
plantilla y la autonomía del arquetipo, marca las escrituras con confirmación,
fija el umbral según el riesgo y convierte sus ejemplos en la primera suite.

Estas funciones son deterministas a propósito. Las llama el flujo de creación
del Arquitecto (plataforma/arquitecto.py), y las decisiones que importan no
dependen de que un modelo "las razone bien": las toma este código y se pueden
probar.

La propuesta vive en .estado/propuestas/<id>.json entre un paso y otro, para
que ningún modelo tenga que copiar un YAML de un lado a otro.
"""

import json
import re

import yaml

from plataforma import catalogo, registro
from plataforma.config import EVALS, MANIFIESTOS, RAIZ, config
from plataforma.manifiesto import UMBRAL_POR_RIESGO, desde_texto, riesgo, validar

DATOS_A_CLASIFICACION = {
    "publicos": "publica",
    "internos": "interna",
    "clientes": "confidencial",
    "restringidos": "restringida",
}
PRESUPUESTO_POR_TIER = {
    "rapido": {"max_usd_per_conversation": 0.01, "monthly_cap_usd": 50},
    "estandar": {"max_usd_per_conversation": 0.05, "monthly_cap_usd": 200},
    "razonamiento": {"max_usd_per_conversation": 0.15, "monthly_cap_usd": 400},
}


def _propuestas_dir():
    d = config().estado_dir / "propuestas"
    d.mkdir(exist_ok=True)
    return d


def ejemplos_no_dichos(ejemplos: list[str], dicho_por_usuario: str, minimo: float = 0.6) -> list[str]:
    """Los ejemplos se vuelven la suite: si los inventa el modelo, la suite
    prueba lo que el modelo imagina y no lo que el área necesita. Un ejemplo
    cuenta como dicho si al menos el 60 % de sus palabras está en lo que el
    usuario escribió (tolera que el modelo lo reformule un poco)."""
    from plataforma.conocimiento import tokenizar

    dicho = set(tokenizar(dicho_por_usuario))
    if not dicho_por_usuario:
        return []  # llamada directa (pruebas, CLI): no hay conversación contra qué comparar
    faltan = []
    for e in ejemplos:
        palabras = set(tokenizar(e))
        if palabras and len(palabras & dicho) / len(palabras) < minimo:
            faltan.append(e)
    return faltan


def recomendar_tier(datos: str, tarea: str) -> dict:
    """Figura 9: primero el dato, después la tarea.

    datos: publicos | internos | clientes | restringidos
    tarea: estrecha (clasificar, extraer, resumir) | conversacion | razonamiento
    """
    if datos not in DATOS_A_CLASIFICACION:
        return {"error": f"datos debe ser uno de {list(DATOS_A_CLASIFICACION)}"}
    clasif = DATOS_A_CLASIFICACION[datos]
    if clasif == "restringida":
        return {
            "alias": None,
            "clasificacion": clasif,
            "explicacion": "Los datos restringidos (bancarios, credenciales, cédulas) nunca van a un modelo. "
                           "Se enmascaran antes o se resuelven dentro de una herramienta.",
        }
    restricciones = []
    if clasif == "confidencial":
        restricciones.append("Solo modelos con retención cero y acuerdo de datos (todos los del catálogo actual cumplen).")
    alias = {"estrecha": "rapido", "razonamiento": "razonamiento"}.get(tarea, "estandar")
    porque = {
        "rapido": "Es una tarea estrecha y de alto volumen: el modelo pequeño la resuelve y cuesta una fracción.",
        "estandar": "Es una conversación con herramientas: el tier estándar es el punto medio de costo y calidad.",
        "razonamiento": "La tarea planifica varios pasos o analiza: justifica el tier más caro.",
    }[alias]
    return {"alias": alias, "modelo_hoy": catalogo.alias(alias)["modelo"], "clasificacion": clasif,
            "restricciones": restricciones, "explicacion": porque}


def proponer_manifiesto(id: str, area: str, owner: str, arquetipo: str, proposito: str, datos: str, tarea: str,
                        siempre: list[str] | None = None, nunca: list[str] | None = None,
                        herramientas: list[str] | None = None, colecciones: list[str] | None = None,
                        tono: str = "cercano-profesional") -> dict:
    id = re.sub(r"[^a-z0-9-]+", "-", id.lower()).strip("-")
    if "-" not in id:
        id = f"{re.sub(r'[^a-z0-9]+', '-', area.lower()).strip('-')}-{id}"
    arqs = catalogo.arquetipos()
    if arquetipo not in arqs or arqs[arquetipo].get("interno"):
        return {"error": f"Arquetipo desconocido. Opciones: {[a for a, v in arqs.items() if not v.get('interno')]}"}
    tier = recomendar_tier(datos, tarea)
    if not tier.get("alias"):
        return {"error": tier.get("explicacion", tier.get("error"))}

    arq = arqs[arquetipo]
    refs = list(dict.fromkeys(arq["herramientas_base"] + (herramientas or [])))
    colecciones = colecciones or []
    if colecciones and "conocimiento/buscar_conocimiento" not in refs:
        refs.append("conocimiento/buscar_conocimiento")

    tools, desconocidas, toca_cliente = [], [], False
    for ref in refs:
        try:
            h = catalogo.herramienta(ref)
        except KeyError:
            desconocidas.append(ref)
            continue
        tool = {"mcp": ref}
        if h.get("requiere_confirmacion"):
            tool["requires_confirmation"] = True  # la plataforma lo pone, no el creador
        toca_cliente |= "cliente_id" in h.get("inyectados", {})
        tools.append(tool)

    clasif = tier["clasificacion"]
    data = {"classification": clasif, "mask_pii_in_traces": True}
    if toca_cliente:
        data["subject_from"] = "session.cliente_id"
    hereda = ["red-team-base"] + (["pii-base"] if catalogo.nivel(clasif) >= catalogo.nivel("confidencial") else [])

    borrador = {
        "apiVersion": "bia.ai/v1",
        "kind": "Agent",
        "metadata": {"id": id, "version": "0.1.0", "owner": owner, "area": area, "archetype": arquetipo},
        "spec": {
            "purpose": proposito,
            "model": {"alias": tier["alias"], **({"fallback": "rapido"} if tier["alias"] != "rapido" else {})},
            "instructions": {"template": arq["plantilla"], "tone": tono, "must": siempre or [], "must_not": nunca or []},
            "tools": tools,
            "knowledge": colecciones,
            "data": data,
            "autonomy": arq["autonomia_defecto"],
            "quality": {"suite": f"evals/{id}.yaml", "min_pass_rate": 0.0, "inherit": hereda},
            "budget": PRESUPUESTO_POR_TIER[tier["alias"]],
        },
    }
    texto = yaml.safe_dump(borrador, sort_keys=False, allow_unicode=True)
    try:
        m = desde_texto(texto)
    except Exception as exc:  # noqa: BLE001 — se devuelve como error de validación legible
        return {"id": id, "errores": [f"Forma inválida: {exc}"]}

    nivel_riesgo = riesgo(m)
    m.spec.quality.min_pass_rate = UMBRAL_POR_RIESGO[nivel_riesgo]
    # La suite todavía no existe: la crea generar_casos_prueba.
    errores = [e for e in validar(m) if "suite de evaluación" not in e]
    errores += [f"La herramienta '{r}' no existe en el catálogo." for r in desconocidas]

    (_propuestas_dir() / f"{id}.json").write_text(json.dumps({"manifiesto": m.a_yaml(), "suite": None}, ensure_ascii=False))
    return {
        "id": id,
        "riesgo": nivel_riesgo,
        "umbral_compuerta": UMBRAL_POR_RIESGO[nivel_riesgo],
        "aprobaciones_necesarias": registro.APROBACIONES[nivel_riesgo],
        "tier": tier,
        "autonomia": arq["autonomia_defecto"],
        "errores": errores,
        "manifiesto_yaml": m.a_yaml(),
    }


def generar_casos_prueba(id: str, preguntas: list[str], respuestas_buenas: list[str],
                         respuesta_mala: str | None = None, cliente_de_prueba: str = "CLI-001") -> dict:
    ruta = _propuestas_dir() / f"{id}.json"
    if not ruta.exists():
        return {"error": f"No hay propuesta para '{id}'."}
    propuesta = json.loads(ruta.read_text())
    m = desde_texto(propuesta["manifiesto"])
    sesion = {"cliente_id": cliente_de_prueba} if m.spec.data.subject_from else {}

    casos = []
    for i, pregunta in enumerate(preguntas, 1):
        caso = {"id": f"ejemplo-{i:02d}", "entrada": pregunta, "esperado": {"no_bloqueado": True}}
        if i <= len(respuestas_buenas):
            caso["rubrica"] = f"Una buena respuesta se parece a: {respuestas_buenas[i - 1]}"
            if respuesta_mala:
                caso["rubrica"] += f" No debe parecerse a: {respuesta_mala}"
        if sesion:
            caso["sesion"] = sesion
        casos.append(caso)
    for j, adv in enumerate(catalogo.arquetipos()[m.metadata.archetype]["casos_adversos"], 1):
        caso = {"id": f"adverso-{j:02d}", "entrada": adv["entrada"], "esperado": adv["esperado"]}
        if sesion:
            caso["sesion"] = sesion
        casos.append(caso)

    suite = {"agente": id, "casos": casos}
    propuesta["suite"] = yaml.safe_dump(suite, sort_keys=False, allow_unicode=True)
    ruta.write_text(json.dumps(propuesta, ensure_ascii=False))
    return {
        "id": id,
        "casos_del_creador": len(preguntas),
        "casos_adversos": len(casos) - len(preguntas),
        "suites_heredadas": m.spec.quality.inherit,
        "nota": "La documentación recomienda entre 15 y 30 casos antes de publicar; estos son el punto de partida.",
    }


def guardar_borrador(id: str) -> dict:
    ruta = _propuestas_dir() / f"{id}.json"
    if not ruta.exists():
        return {"error": f"No hay propuesta para '{id}'."}
    propuesta = json.loads(ruta.read_text())
    if not propuesta["suite"]:
        return {"error": "Falta la suite de pruebas de la propuesta."}
    (EVALS / f"{id}.yaml").write_text(propuesta["suite"], encoding="utf-8")
    destino = MANIFIESTOS / "borradores" / f"{id}.yaml"
    destino.write_text(propuesta["manifiesto"], encoding="utf-8")
    try:
        estado = registro.registrar(desde_texto(propuesta["manifiesto"]))
    except registro.ErrorRegistro as exc:
        return {"error": str(exc)}
    ruta.unlink()  # una propuesta guardada no se reutiliza por accidente en otra entrevista
    return {
        "id": id,
        "estado": estado,
        "manifiesto": str(destino.relative_to(RAIZ)),
        "suite": f"evals/{id}.yaml",
        "siguientes_pasos": [f"bia chat {id} --sandbox", f"bia evaluar {id}", f"bia publicar {id}"],
    }


def resumen_catalogo(tipo: str) -> dict:
    if tipo == "modelos":
        return {a: {"modelo": v["modelo"], "para": v["descripcion"], "datos_hasta": v["clasificacion_maxima"]}
                for a, v in catalogo.modelos()["alias"].items()}
    if tipo == "herramientas":
        return {r: {"tipo": v["tipo"], "para": v["para_que"], "confirmacion": bool(v.get("requiere_confirmacion"))}
                for r, v in catalogo.herramientas()["herramientas"].items() if not r.startswith("plataforma/")}
    if tipo == "colecciones":
        return {c: {"dueno": v["dueno"], "clasificacion": v["clasificacion"], "contenido": v["descripcion"]}
                for c, v in catalogo.colecciones().items()}
    if tipo == "arquetipos":
        return {a: {"que_hace": v["que_hace"], "ejemplo": v["ejemplo_bia"], "riesgo": v["riesgo_base"],
                    "autonomia": v["autonomia_defecto"]}
                for a, v in catalogo.arquetipos().items() if not v.get("interno")}
    return {"error": "tipo debe ser modelos, herramientas, colecciones o arquetipos"}
