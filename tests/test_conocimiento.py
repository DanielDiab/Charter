"""RAG con vigencia y permisos (figura 12)."""

from plataforma import conocimiento


async def test_el_documento_vencido_no_compite():
    r = await conocimiento.buscar("restricciones valor fijo mensual por cliente", ["tarifas-metodologia"])
    assert r, "debería encontrar el documento vigente"
    assert all("v2026-01" not in f["cita"] for f in r)
    assert all("valor fijo mensual" not in f["texto"] for f in r)


async def test_el_vencido_si_aparece_si_la_fecha_es_la_de_su_vigencia():
    r = await conocimiento.buscar("restricciones valor fijo mensual", ["tarifas-metodologia"], fecha="2026-03-15")
    assert any("v2026-01" in f["cita"] for f in r)


async def test_solo_busca_en_las_colecciones_del_agente():
    r = await conocimiento.buscar("gateway de modelos llaves", ["faq-facturacion"])
    assert all(f["cita"].startswith("faq-facturacion/") for f in r)


async def test_faq_se_trocea_por_pregunta():
    r = await conocimiento.buscar("medios de pago PSE", ["faq-facturacion"])
    assert r[0]["texto"].startswith("Pregunta: ¿Qué medios de pago")


def test_rrf_premia_lo_que_aparece_en_ambos_rankings():
    a, b, c = {"id": "a"}, {"id": "b"}, {"id": "c"}
    assert conocimiento.rrf([a, b, c], [b, c, a])[0]["id"] == "b"
