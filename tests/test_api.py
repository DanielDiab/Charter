"""API compatible con OpenAI: solo publicados, sesión desde el token."""

from contextlib import asynccontextmanager

import httpx
from langchain_core.messages import AIMessage

from plataforma import catalogo, registro
from plataforma.api import app
from plataforma.config import MANIFIESTOS
from plataforma.manifiesto import cargar
from tests.conftest import llamada


@asynccontextmanager
async def cliente():
    # Cliente en el mismo event loop que la prueba. Con TestClient (otro hilo y
    # otro loop) las sesiones MCP abiertas en el lifespan quedaban en un loop
    # distinto al de la petición y la llamada se cancelaba.
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            yield c


def _publicar(nombre: str):
    m = cargar(MANIFIESTOS / f"{nombre}.yaml")
    registro.registrar(m)
    estado = registro.obtener(m.id, m.version)[1]["estado"]
    if estado != "publicado":
        registro.guardar_reporte(m.id, m.version, {"aprobado": True, "resumen": "prueba",
                                                   "huella_manifiesto": catalogo.huella(m.a_yaml())})
        for rol in registro.APROBACIONES[registro.obtener(m.id, m.version)[1]["riesgo"]]:
            registro.aprobar(m.id, m.version, rol, "prueba@energia.example")
        registro.publicar(m.id, m.version)


async def test_token_invalido():
    async with cliente() as c:
        r = await c.post("/v1/chat/completions", headers={"Authorization": "Bearer no-existe"},
                   json={"model": "sac-asistente-facturacion", "messages": [{"role": "user", "content": "hola"}]})
    assert r.status_code == 401


async def test_un_borrador_no_existe_para_los_canales():
    async with cliente() as c:
        r = await c.post("/v1/chat/completions", headers={"Authorization": "Bearer tok-espiga"},
                   json={"model": "agente-que-no-existe", "messages": [{"role": "user", "content": "hola"}]})
    assert r.status_code == 404


async def test_el_cliente_sale_del_token(guion):
    _publicar("sac-asistente-facturacion")
    guion(llamada("consultar_factura", {"cliente_id": "CLI-001"}), AIMessage(content="Tu saldo es 18.106.880 pesos."))
    async with cliente() as c:
        modelos = {m["id"] for m in (await c.get("/v1/models")).json()["data"]}
        assert "sac-asistente-facturacion" in modelos
        r = (await c.post("/v1/chat/completions", headers={"Authorization": "Bearer tok-andes"},
                   json={"model": "sac-asistente-facturacion",
                         "messages": [{"role": "user", "content": "¿cuál es mi saldo?"}]})).json()
    # El modelo pidió CLI-001, pero el token es de CLI-002: el saldo es el de CLI-002.
    assert r["choices"][0]["message"]["content"] == "Tu saldo es 18.106.880 pesos."
    assert r["charter"]["herramientas"] == ["facturacion/consultar_factura"]


async def test_inventarios_por_api():
    async with cliente() as c:
        assert (await c.get("/inventario/agentes")).status_code == 200
        assert {m["alias"] for m in (await c.get("/inventario/modelos")).json()} == {"rapido", "estandar", "razonamiento"}
        assert "herramientas" in (await c.get("/inventario/orquestacion")).json()
