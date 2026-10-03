"""El manifiesto y sus reglas no negociables (sección 3)."""

import pytest

from plataforma.config import MANIFIESTOS
from plataforma.manifiesto import cargar, desde_texto, riesgo, validar


@pytest.mark.parametrize("nombre", ["sac-asistente-facturacion", "sac-procedimientos-internos", "plataforma-arquitecto"])
def test_los_manifiestos_del_repo_cumplen(nombre):
    assert validar(cargar(MANIFIESTOS / f"{nombre}.yaml")) == []


def test_riesgo_lo_calcula_la_plataforma():
    assert riesgo(cargar(MANIFIESTOS / "sac-asistente-facturacion.yaml")) == "medio"
    assert riesgo(cargar(MANIFIESTOS / "sac-procedimientos-internos.yaml")) == "bajo"


def _facturacion(**cambios) -> str:
    texto = (MANIFIESTOS / "sac-asistente-facturacion.yaml").read_text(encoding="utf-8")
    for viejo, nuevo in cambios.items():
        assert viejo in texto
        texto = texto.replace(viejo, nuevo)
    return texto


def _errores(texto: str) -> str:
    return " ".join(validar(desde_texto(texto)))


def test_escritura_sin_confirmacion_no_pasa():
    texto = _facturacion(**{"      requires_confirmation: true                 # escritura: confirma el usuario\n": ""})
    assert "requires_confirmation" in _errores(texto)


def test_datos_restringidos_nunca_van_al_modelo():
    assert "restringidos" in _errores(_facturacion(**{"classification: confidencial": "classification: restringida"}))


def test_herramienta_mas_sensible_que_el_agente():
    # Un agente "interno" no puede usar herramientas que devuelven datos de clientes.
    assert "consultar_factura" in _errores(_facturacion(**{"classification: confidencial": "classification: interna"}))


def test_umbral_menor_que_el_del_riesgo():
    assert "90%" in _errores(_facturacion(**{"min_pass_rate: 0.90": "min_pass_rate: 0.50"}))


def test_autonomia_l5_no_existe_en_fases_1_y_2():
    assert "L4" in _errores(_facturacion(**{"autonomy: L2 ": "autonomy: L5 "}))


def test_el_agente_pide_alias_no_modelo():
    assert "no existe" in _errores(_facturacion(**{"alias: estandar,": "alias: gpt-5,"}))


def test_sin_dueno_no_hay_manifiesto():
    with pytest.raises(Exception):
        desde_texto(_facturacion(**{"owner: lider.sac@bia.app": "owner: nadie"}))
