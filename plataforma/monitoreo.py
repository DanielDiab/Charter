"""Monitoreo en producción: las cinco dimensiones por agente (sección 5).

  calidad     retroalimentación de usuarios y tasa de escalamiento
  seguridad   bloqueos de entrada y salida, incidentes (suspenden solos)
  costo       por conversación y total
  operación   latencia p95 de las llamadas al modelo, errores de herramientas
  adopción    conversaciones

Todo sale de las trazas. Lo que queda para la fase 2, como dice la hoja de
ruta: el muestreo de conversaciones evaluado por el juez en línea con los
mismos criterios de la compuerta.
"""

from plataforma import trazas


def _p95(valores: list[int]) -> int:
    if not valores:
        return 0
    valores = sorted(valores)
    return valores[min(len(valores) - 1, int(round(0.95 * (len(valores) - 1))))]


def metricas(agente: str, entorno: str = "produccion") -> dict:
    spans = [s for s in trazas.spans(agente=agente, limite=100_000) if s["entorno"] == entorno]
    conversaciones = {s["conversacion"] for s in spans}
    n = len(conversaciones) or 1
    guard_entrada = [s for s in spans if s["nombre"] == "guard_entrada"]
    bloqueos_entrada = sum('"permitido": false' in s["detalle"] for s in guard_entrada)
    bloqueos_salida = sum(1 for s in spans if s["nombre"] == "guard_salida" and s["estado"] == "bloqueo")
    escalamientos = {s["conversacion"] for s in spans if s["nombre"] == "soporte/crear_caso" and s["tipo"] == "herramienta" and s["estado"] == "ok"}
    herramientas = [s for s in spans if s["tipo"] == "herramienta"]
    feedback = trazas.retroalimentacion(agente)
    return {
        "agente": agente,
        "entorno": entorno,
        "adopcion": {"conversaciones": len(conversaciones)},
        "calidad": {
            "retroalimentacion": len(feedback),
            "util_pct": round(100 * sum(f["util"] for f in feedback) / len(feedback), 1) if feedback else None,
            "escalamiento_pct": round(100 * len(escalamientos) / n, 1),
        },
        "seguridad": {
            "bloqueos_entrada": bloqueos_entrada,
            "bloqueos_salida": bloqueos_salida,
            "incidentes": sum(1 for s in spans if s["nombre"] == "incidente_suspension"),
        },
        "costo": {
            "total_usd": round(sum(s["costo_usd"] for s in spans), 5),
            "por_conversacion_usd": round(sum(s["costo_usd"] for s in spans) / n, 5),
        },
        "operacion": {
            "latencia_p95_llm_ms": _p95([s["latencia_ms"] for s in spans if s["tipo"] == "llm"]),
            "errores_herramientas": sum(1 for s in herramientas if s["estado"] == "error"),
            "llamadas_herramientas": len(herramientas),
        },
    }
