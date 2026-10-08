"""Constructor: de la entrevista a un manifiesto válido sin escribir prompts (sección 4)."""

import yaml

from plataforma import constructor, registro
from plataforma.compilador import compilar
from plataforma.config import MANIFIESTOS
from plataforma.manifiesto import cargar, desde_texto


def test_arbol_de_tiers_primero_el_dato():
    assert constructor.recomendar_tier("restringidos", "estrecha")["alias"] is None
    assert constructor.recomendar_tier("internos", "estrecha")["alias"] == "rapido"
    assert constructor.recomendar_tier("clientes", "conversacion")["alias"] == "estandar"
    assert constructor.recomendar_tier("clientes", "conversacion")["restricciones"]
    assert constructor.recomendar_tier("internos", "razonamiento")["alias"] == "razonamiento"


def test_de_la_entrevista_al_borrador_registrado():
    p = constructor.proponer_manifiesto(
        id="cobranza-consulta-saldo", area="cobranzas", owner="lider.cobranzas@energia.example",
        arquetipo="asistente-con-datos", proposito="Responder a clientes cuánto deben y cuándo vence su factura.",
        datos="clientes", tarea="conversacion", siempre=["ofrecer escalar a un asesor"],
        herramientas=["facturacion/consultar_factura", "soporte/crear_caso"],
    )
    assert p["errores"] == []
    m = desde_texto(p["manifiesto_yaml"])
    assert m.spec.model.alias == "estandar"
    assert m.spec.data.subject_from == "session.cliente_id"             # lo puso la plataforma
    assert m.herramienta("soporte/crear_caso").requires_confirmation    # lo puso la plataforma
    assert m.spec.quality.min_pass_rate == 0.90 and "pii-base" in m.spec.quality.inherit

    s = constructor.generar_casos_prueba(m.id, ["¿cuánto debo?"], ["Debes X pesos y vence el día Y"], "Inventar el saldo")
    assert s["casos_adversos"] >= 1
    g = constructor.guardar_borrador(m.id)
    assert g["estado"] == "borrador"
    assert registro.obtener(m.id)[1]["estado"] == "borrador"
    suite = yaml.safe_load((MANIFIESTOS.parent / g["suite"]).read_text(encoding="utf-8"))
    assert suite["casos"][0]["sesion"] == {"cliente_id": "CLI-001"}
    (MANIFIESTOS.parent / g["manifiesto"]).unlink()
    (MANIFIESTOS.parent / g["suite"]).unlink()


def test_arquetipo_interno_no_se_ofrece():
    assert "asistente-de-plataforma" not in constructor.resumen_catalogo("arquetipos")
    assert "error" in constructor.proponer_manifiesto("x-y", "a", "a@b.c", "asistente-de-plataforma", "p" * 30, "internos", "conversacion")


def test_las_politicas_siempre_van_al_final():
    instrucciones = compilar(cargar(MANIFIESTOS / "sac-asistente-facturacion.yaml"))
    assert instrucciones.rstrip().endswith("sin emojis.")
    assert "prometer descuentos o acuerdos de pago" in instrucciones
    assert "dato_no_confiable" in instrucciones
