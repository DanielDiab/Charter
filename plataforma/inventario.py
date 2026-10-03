"""Los tres inventarios que pide el reto (B.2), como vistas y no como hojas.

  agentes       ¿Cuántos hay y qué tocan?         registro + costo desde trazas
  modelos       ¿Con qué corren?                  catálogo + quién usa cada alias
  orquestacion  ¿Qué puede hacer cada uno?        herramientas, colecciones, patrón

Nadie los mantiene a mano: se calculan del registro, los catálogos y las
trazas. Si un agente no aparece aquí es porque no pasó por el registro, y
entonces tampoco tiene llaves, herramientas ni datos (figura 1).
"""

from collections import defaultdict

from plataforma import catalogo, conocimiento, registro, trazas
from plataforma.manifiesto import desde_texto


def _costos() -> dict[str, float]:
    total = defaultdict(float)
    for fila in trazas.costos_por_agente():
        total[fila["agente"]] += fila["costo_usd"] or 0
    return total


def agentes() -> list[dict]:
    costos = _costos()
    salida = []
    for f in registro.listar():
        m = desde_texto(f["manifiesto"])
        salida.append({
            "id": m.id,
            "version": m.version,
            "estado": f["estado"],
            "dueno": m.metadata.owner,
            "area": m.metadata.area,
            "arquetipo": m.metadata.archetype,
            "alias": m.spec.model.alias,
            "modelo_hoy": catalogo.alias(m.spec.model.alias)["modelo"],
            "clasificacion": m.spec.data.classification,
            "autonomia": m.spec.autonomy,
            "riesgo": f["riesgo"],
            "herramientas": [t.mcp for t in m.spec.tools],
            "colecciones": m.spec.knowledge,
            "costo_usd_acumulado": round(costos.get(m.id, 0), 5),
        })
    return salida


def modelos() -> list[dict]:
    usos = defaultdict(list)
    for a in agentes():
        if a["estado"] in ("publicado", "evaluacion", "borrador"):
            usos[a["alias"]].append(f"{a['id']} ({a['estado']})")
    return [
        {
            "alias": nombre,
            "modelo": v["modelo"],
            "proveedor": v["proveedor"],
            "retencion": v["retencion"],
            "datos_hasta": v["clasificacion_maxima"],
            "capacidades": [k for k, ok in v["capacidades"].items() if ok is True],
            "precio_usd_por_millon": v["precio_usd_por_millon"],
            "agentes": usos.get(nombre, []),
        }
        for nombre, v in catalogo.modelos()["alias"].items()
    ]


def orquestacion() -> dict:
    por_herramienta, por_coleccion = defaultdict(list), defaultdict(list)
    patrones = {}
    for f in registro.listar():
        m = desde_texto(f["manifiesto"])
        for t in m.spec.tools:
            por_herramienta[t.mcp].append(m.id)
        for c in m.spec.knowledge:
            por_coleccion[c].append(m.id)
        patrones[m.id] = catalogo.arquetipos()[m.metadata.archetype]["patron"]

    try:
        indice = conocimiento.cargar_indice()
    except FileNotFoundError:
        indice = []
    return {
        "herramientas": [
            {"ref": ref, "tipo": h["tipo"], "confirmacion": bool(h.get("requiere_confirmacion")),
             "clasificacion": h["clasificacion"], "servidor": catalogo.servidor_de(ref)["sistema"],
             "agentes": sorted(set(por_herramienta.get(ref, [])))}
            for ref, h in catalogo.herramientas()["herramientas"].items()
        ],
        "colecciones": [
            {"coleccion": c, "dueno": v["dueno"], "clasificacion": v["clasificacion"],
             "fragmentos_vigentes": sum(1 for x in indice if x["coleccion"] == c and conocimiento.vigente(x, conocimiento.hoy())),
             "fragmentos_vencidos": sum(1 for x in indice if x["coleccion"] == c and not conocimiento.vigente(x, conocimiento.hoy())),
             "agentes": sorted(set(por_coleccion.get(c, [])))}
            for c, v in catalogo.colecciones().items()
        ],
        "flujos": [{"agente": a, "patron": p} for a, p in sorted(patrones.items())],
    }
