"""Gateway de modelos: el único componente que habla con un proveedor de LLM.

Decisión del documento (2.2): el gateway es el único componente con llaves.
Así cada llamada queda atribuida a un agente y un área, con costo y política de
datos aplicados en un solo lugar. Ningún otro módulo de este repo importa
`langchain_ollama`; si alguien lo hace, se salta el costo, el presupuesto y la
traza, y eso es lo que hay que detectar en revisión de código.

En producción el gateway es LiteLLM (alias, llaves, reintentos, costo). En el
prototipo es este módulo, con la misma responsabilidad y sin un proxy más que
levantar. Lo que hace en cada llamada, en orden:

  1. Resuelve el alias contra el catálogo (P3: el agente pide capacidad).
  2. Revisa que el alias sea elegible para la clasificación del agente. El
     manifiesto ya se validó al registrarlo, pero el catálogo puede cambiar
     después; esta es la segunda línea.
  3. Revisa el presupuesto: tope por conversación y tope mensual del agente.
  4. Llama al modelo; si falla, intenta con el alias de respaldo.
  5. Registra el span con tokens, costo y latencia.
"""

import time

import httpx
from langchain_core.messages import AIMessage

from plataforma import catalogo, trazas
from plataforma.config import config, hoy


class PresupuestoExcedido(Exception):
    pass


class ModeloNoElegible(Exception):
    pass


def _fabrica_ollama(nombre_alias: str, a: dict):
    from langchain_ollama import ChatOllama

    p = a.get("parametros", {})
    extra = {"reasoning": p["reasoning"]} if "reasoning" in p else {}
    return ChatOllama(
        model=a["modelo"],
        base_url=config().ollama_base_url,
        temperature=p.get("temperatura", 0),
        num_predict=p.get("max_tokens", 600),
        num_ctx=p.get("num_ctx", 8192),
        # Mantiene el modelo cargado entre turnos: ahorra ~1 s de carga cuando
        # Ollama lo descarga por inactividad. Aprendido en el curso con GPU de 4 GB.
        keep_alive="30m",
        **extra,
    )


def costo_usd(a: dict, tokens_entrada: int, tokens_salida: int) -> float:
    precio = a["precio_usd_por_millon"]
    return round((tokens_entrada * precio["entrada"] + tokens_salida * precio["salida"]) / 1_000_000, 6)


class Gateway:
    def __init__(self, fabrica=_fabrica_ollama):
        # `fabrica` existe para las pruebas: inyectan un modelo falso y todo lo
        # demás (presupuesto, costo, traza) se ejercita igual.
        self._fabrica = fabrica
        self._modelos: dict = {}

    def _modelo(self, nombre_alias: str):
        a = catalogo.alias(nombre_alias)
        clave = (nombre_alias, a["modelo"])
        if clave not in self._modelos:
            self._modelos[clave] = self._fabrica(nombre_alias, a)
        return self._modelos[clave], a

    def _verificar_politica(self, ctx: dict, nombre_alias: str, a: dict) -> None:
        clasif = ctx.get("clasificacion", "interna")
        if clasif == "restringida":
            raise ModeloNoElegible("Los datos restringidos nunca van a un modelo.")
        if catalogo.nivel(clasif) > catalogo.nivel(a["clasificacion_maxima"]):
            raise ModeloNoElegible(f"El alias '{nombre_alias}' no está aprobado para datos '{clasif}'.")

    def _verificar_presupuesto(self, ctx: dict) -> None:
        presupuesto = ctx.get("presupuesto")
        if not presupuesto:
            return
        gastado = trazas.costo_conversacion(ctx["conversacion"])
        if gastado >= presupuesto["max_usd_per_conversation"]:
            raise PresupuestoExcedido(
                f"La conversación ya consumió US${gastado:.4f} de US${presupuesto['max_usd_per_conversation']}."
            )
        if ctx.get("entorno") == "produccion":
            mes = trazas.costo_mes(ctx["agente"], hoy()[:7])
            if mes >= presupuesto["monthly_cap_usd"]:
                raise PresupuestoExcedido(f"El agente alcanzó su tope mensual de US${presupuesto['monthly_cap_usd']}.")

    async def chat(self, ctx: dict, mensajes: list, *, alias: str, fallback: str | None = None,
                   herramientas: list[dict] | None = None, nombre: str = "llm") -> AIMessage:
        self._verificar_presupuesto(ctx)
        intentos = [alias] + ([fallback] if fallback and fallback != alias else [])
        ultimo_error = None
        for nombre_alias in intentos:
            modelo, a = self._modelo(nombre_alias)
            self._verificar_politica(ctx, nombre_alias, a)
            llamable = modelo.bind_tools(herramientas) if herramientas else modelo
            inicio = time.perf_counter()
            try:
                respuesta = await llamable.ainvoke(mensajes)
            except Exception as exc:  # noqa: BLE001 — cualquier falla del proveedor activa el respaldo
                ultimo_error = exc
                trazas.registrar_span(ctx, "llm", nombre, estado="error", alias=nombre_alias, modelo=a["modelo"],
                                      latencia_ms=int((time.perf_counter() - inicio) * 1000),
                                      detalle={"error": str(exc)[:300]})
                continue
            uso = respuesta.usage_metadata or {}
            t_in, t_out = uso.get("input_tokens", 0), uso.get("output_tokens", 0)
            trazas.registrar_span(
                ctx, "llm", nombre, alias=nombre_alias, modelo=a["modelo"],
                tokens_entrada=t_in, tokens_salida=t_out, costo_usd=costo_usd(a, t_in, t_out),
                latencia_ms=int((time.perf_counter() - inicio) * 1000),
                detalle={
                    "respuesta": str(respuesta.content)[:500],
                    "tool_calls": [tc["name"] for tc in respuesta.tool_calls],
                    "respaldo": nombre_alias != alias,
                },
            )
            return respuesta
        raise RuntimeError(f"Ningún modelo respondió (alias {intentos}): {ultimo_error}")

    async def embeber(self, ctx: dict, textos: list[str]) -> list[list[float]]:
        emb = catalogo.modelos()["embeddings"]
        inicio = time.perf_counter()
        async with httpx.AsyncClient(timeout=120) as cliente:
            r = await cliente.post(f"{config().ollama_base_url}/api/embed", json={"model": emb["modelo"], "input": textos})
            r.raise_for_status()
            datos = r.json()
        tokens = datos.get("prompt_eval_count", 0)
        trazas.registrar_span(ctx, "embeddings", "embeber", alias="embeddings", modelo=emb["modelo"],
                              tokens_entrada=tokens, costo_usd=costo_usd(emb, tokens, 0),
                              latencia_ms=int((time.perf_counter() - inicio) * 1000),
                              detalle={"textos": len(textos)})
        return datos["embeddings"]


_gateway: Gateway | None = None


def gateway() -> Gateway:
    global _gateway
    if _gateway is None:
        _gateway = Gateway()
    return _gateway


def usar(g: Gateway) -> None:
    """Reemplaza el gateway del proceso (pruebas)."""
    global _gateway
    _gateway = g
