"""Registro y ciclo de vida (figura 17): el único camino a producción."""

import pytest

from plataforma import catalogo, registro
from plataforma.config import MANIFIESTOS
from plataforma.manifiesto import cargar


def _reporte(m, aprobado=True):
    return {"aprobado": aprobado, "resumen": "prueba", "huella_manifiesto": catalogo.huella(m.a_yaml())}


def test_camino_completo_y_reglas():
    m = cargar(MANIFIESTOS / "sac-procedimientos-internos.yaml")
    assert registro.registrar(m) == "borrador"

    with pytest.raises(registro.ErrorRegistro, match="sin compuerta"):
        registro.publicar(m.id)
    with pytest.raises(registro.ErrorRegistro, match="no pasó la compuerta"):
        registro.aprobar(m.id, m.version, "dueno", "lider.sac@energia.example")

    registro.guardar_reporte(m.id, m.version, _reporte(m, aprobado=False))
    assert registro.obtener(m.id)[1]["estado"] == "borrador"  # falla: vuelve con el reporte

    registro.guardar_reporte(m.id, m.version, _reporte(m))
    with pytest.raises(registro.ErrorRegistro, match="faltan aprobaciones"):
        registro.publicar(m.id)
    registro.aprobar(m.id, m.version, "dueno", "lider.sac@energia.example")
    assert registro.publicar(m.id) == m.version
    assert registro.obtener_publicado(m.id).version == m.version


def test_riesgo_medio_exige_al_equipo_de_ia():
    m = cargar(MANIFIESTOS / "sac-asistente-facturacion.yaml")
    registro.registrar(m)
    registro.guardar_reporte(m.id, m.version, _reporte(m))
    registro.aprobar(m.id, m.version, "dueno", "lider.sac@energia.example")
    with pytest.raises(registro.ErrorRegistro, match="equipo-ia"):
        registro.publicar(m.id)
    registro.aprobar(m.id, m.version, "equipo-ia", "equipo.ia@energia.example")
    registro.publicar(m.id)


def test_publicado_es_inmutable():
    m = cargar(MANIFIESTOS / "sac-procedimientos-internos.yaml")
    m.spec.instructions.tone = "otro tono"
    with pytest.raises(registro.ErrorRegistro, match="Sube la versión"):
        registro.registrar(m)


def test_recertificacion_cuando_cambia_el_modelo_del_alias(monkeypatch):
    # sac-procedimientos-internos quedó publicado arriba con alias `rapido`.
    assert registro.verificar_recertificacion() == []
    monkeypatch.setitem(catalogo.modelos()["alias"]["rapido"], "modelo", "un-modelo-nuevo:3b")
    cambios = registro.verificar_recertificacion()
    afectado = next(c for c in cambios if c["agente"] == "sac-procedimientos-internos")
    assert "alias:rapido" in afectado["cambios"]
    assert registro.obtener("sac-procedimientos-internos")[1]["estado"] == "evaluacion"
    # facturación usa `estandar` con respaldo `rapido`: también depende de él.
    assert any(c["agente"] == "sac-asistente-facturacion" for c in cambios)


def test_caducidad_a_los_90_dias():
    m = cargar(MANIFIESTOS / "plataforma-arquitecto.yaml")
    registro.registrar(m)
    registro.guardar_reporte(m.id, m.version, _reporte(m))
    registro.aprobar(m.id, m.version, "dueno", "equipo.ia@energia.example")
    registro.publicar(m.id)
    import time
    assert m.id in registro.verificar_caducidad({}, ahora=time.time() + 91 * 86400)
    assert registro.obtener(m.id)[1]["estado"] == "deprecado"
