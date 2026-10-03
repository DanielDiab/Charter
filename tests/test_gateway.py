"""Gateway: alias, costo atribuido, presupuesto y respaldo (decisión 2.2)."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from plataforma import catalogo, gateway, trazas


def _ctx(conv, **extra):
    return {"agente": "prueba", "version": "1.0.0", "area": "pruebas", "entorno": "sandbox",
            "conversacion": conv, "clasificacion": "confidencial", **extra}


async def test_costo_queda_atribuido(guion):
    guion(AIMessage(content="hola"))
    await gateway.gateway().chat(_ctx("g-costo"), [HumanMessage(content="hola")], alias="estandar")
    esperado = gateway.costo_usd(catalogo.alias("estandar"), 1000, 100)
    assert trazas.costo_conversacion("g-costo") == pytest.approx(esperado)


async def test_presupuesto_por_conversacion(guion):
    guion(AIMessage(content="uno"), AIMessage(content="dos"))
    ctx = _ctx("g-tope", presupuesto={"max_usd_per_conversation": 0.0001, "monthly_cap_usd": 10})
    await gateway.gateway().chat(ctx, [HumanMessage(content="x")], alias="razonamiento")
    with pytest.raises(gateway.PresupuestoExcedido):
        await gateway.gateway().chat(ctx, [HumanMessage(content="x")], alias="razonamiento")


async def test_datos_restringidos_no_llegan_al_modelo(guion):
    guion(AIMessage(content="no debería llamarse"))
    with pytest.raises(gateway.ModeloNoElegible):
        await gateway.gateway().chat(_ctx("g-restr", clasificacion="restringida"), [HumanMessage(content="x")], alias="estandar")


async def test_respaldo_si_el_principal_falla():
    llamados = []

    class Falla:
        def bind_tools(self, _):
            return self

        async def ainvoke(self, _):
            raise ConnectionError("modelo caído")

    class Responde(Falla):
        async def ainvoke(self, _):
            return AIMessage(content="respondí yo", usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})

    def fabrica(alias, a):
        llamados.append(alias)
        return Falla() if alias == "estandar" else Responde()

    gateway.usar(gateway.Gateway(fabrica=fabrica))
    try:
        r = await gateway.gateway().chat(_ctx("g-resp"), [HumanMessage(content="x")], alias="estandar", fallback="rapido")
    finally:
        gateway.usar(gateway.Gateway())
    assert r.content == "respondí yo" and llamados == ["estandar", "rapido"]
    estados = [s["estado"] for s in trazas.spans("g-resp")]
    assert "error" in estados and "ok" in estados
