"""El Arquitecto: enrutador entre preguntas (agente) y creación (flujo determinista)."""

import json

import yaml
from langchain_core.messages import AIMessage

from plataforma import registro, runtime
from plataforma.arquitecto import Arquitecto
from plataforma.config import EVALS, MANIFIESTOS
from plataforma.manifiesto import cargar
from plataforma.mcp import Conexiones

SESION = {"cliente_id": None, "usuario": "lider.ventas@bia.app"}


def _json(**datos) -> AIMessage:
    return AIMessage(content=json.dumps(datos, ensure_ascii=False))


async def _arquitecto(cx):
    m = cargar(MANIFIESTOS / "plataforma-arquitecto.yaml")
    return Arquitecto(await runtime.Agente(m, cx, "sandbox").preparar())


async def test_entrevista_completa_crea_un_borrador_valido(guion):
    guion(
        _json(proposito="Resumir las llamadas de ventas de los asesores.", arquetipo="extractor-clasificador",
              tarea="estrecha", herramientas=[], colecciones=[]),
        _json(datos="internos"),
        _json(siempre=["decir el siguiente paso acordado"], nunca=["inventar precios"]),
        AIMessage(content=json.dumps([   # una lista suelta: otra forma que devuelve el modelo
            {"pregunta": "Resume esta llamada: Pedro quiere el plan solar y pidió cotización el viernes",
             "respuesta_buena": "Cliente: Pedro. Interés: plan solar. Siguiente paso: cotización el viernes."},
            # Inventado por el modelo: no está en lo que escribió el usuario.
            {"pregunta": "¿Cuál es el estado del pedido 123 de María?", "respuesta_buena": "En camino."},
        ], ensure_ascii=False)),
        _json(area="ventas", nombre="resumen de llamadas"),
    )
    conv = "arq-entrevista"
    async with Conexiones() as cx:
        a = await _arquitecto(cx)
        r = await a.turno("Quiero crear un agente", SESION, conv)
        assert "1/5" in r.respuesta
        await a.turno("Que resuma las llamadas de ventas de mis asesores, es para mi equipo interno", SESION, conv)
        r = await a.turno("Ve transcripciones internas", SESION, conv)
        assert "rapido" in r.respuesta  # tarea estrecha + datos internos → tier rápido (figura 9)
        await a.turno("Siempre decir el siguiente paso. Nunca inventar precios.", SESION, conv)
        await a.turno("Ejemplo: Resume esta llamada: Pedro quiere el plan solar y pidió cotización el viernes. "
                      "Buena respuesta: Cliente: Pedro. Interés: plan solar. Siguiente paso: cotización el viernes.",
                      SESION, conv)
        r = await a.turno("Es de ventas, llámalo resumen de llamadas", SESION, conv)
        assert "ventas-resumen-de-llamadas" in r.respuesta and "lider.ventas@bia.app" in r.respuesta
        r = await a.turno("sí", SESION, conv)
    assert r.herramientas == ["plataforma/guardar_borrador"]
    m, info = registro.obtener("ventas-resumen-de-llamadas")
    assert info["estado"] == "borrador"
    assert m.metadata.owner == "lider.ventas@bia.app"          # de la sesión, no del modelo
    assert m.spec.model.alias == "rapido"
    suite = yaml.safe_load((EVALS / "ventas-resumen-de-llamadas.yaml").read_text(encoding="utf-8"))
    entradas = [c["entrada"] for c in suite["casos"]]
    assert not any("María" in e for e in entradas)               # el ejemplo inventado no llegó a la suite
    (MANIFIESTOS / "borradores" / "ventas-resumen-de-llamadas.yaml").unlink()
    (EVALS / "ventas-resumen-de-llamadas.yaml").unlink()


async def test_las_preguntas_van_al_agente(guion):
    guion(AIMessage(content="Un agente es un manifiesto. [plataforma-docs/manifiesto-y-ciclo-de-vida#que-es-un-agente]"))
    async with Conexiones() as cx:
        a = await _arquitecto(cx)
        r = await a.turno("¿Qué es un agente en esta plataforma?", SESION)
    assert "manifiesto" in r.respuesta
    assert r.herramientas == ["conocimiento/buscar_conocimiento"]  # recuperar_siempre del arquetipo


async def test_cancelar_no_guarda_nada(guion):
    guion()
    async with Conexiones() as cx:
        a = await _arquitecto(cx)
        await a.turno("Quiero crear un agente", SESION, "arq-cancela")
        r = await a.turno("cancelar", SESION, "arq-cancela")
    assert "No se guardó nada" in r.respuesta


def test_ejemplo_suelto_tambien_se_reconoce():
    from plataforma.arquitecto import _como_ejemplos
    assert len(_como_ejemplos({"pregunta": "a", "respuesta_buena": "b"})) == 1
    assert len(_como_ejemplos({"ejemplos": [{"pregunta": "a"}, {"pregunta": "c"}]})) == 2
    assert len(_como_ejemplos([{"pregunta": "a"}])) == 1
