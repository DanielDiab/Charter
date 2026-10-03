"""Compila las instrucciones de un agente desde su manifiesto (sección 4).

Nadie escribe un prompt. Las instrucciones salen de:

    plantilla curada del arquetipo  +  lo que el creador declaró  +  políticas heredadas
    (la técnica, la revisa IA)         (el negocio: propósito,      (datos, marca, escalamiento,
                                        must, must_not, tono)        contenido recuperado = dato)

Las políticas van AL FINAL y no se pueden quitar: el creador controla el qué,
nunca las reglas de la plataforma. La compilación es conservadora a propósito
(sustitución sobre plantillas revisadas); la optimización automática al estilo
DSPy queda para después, cuando haya suites con historia contra qué optimizar.
"""

from string import Template

from plataforma import catalogo
from plataforma.config import hoy
from plataforma.manifiesto import Manifiesto


def _lista(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "- (nada adicional)"


def compilar(m: Manifiesto) -> str:
    plantilla = Template(catalogo.plantilla(m.spec.instructions.template))
    nombres_herramientas = [t.mcp.split("/", 1)[1] for t in m.spec.tools]
    cuerpo = plantilla.safe_substitute(
        nombre=m.id,
        area=m.metadata.area,
        proposito=" ".join(m.spec.purpose.split()),
        tono=m.spec.instructions.tone,
        must=_lista(m.spec.instructions.must),
        must_not=_lista(m.spec.instructions.must_not),
        herramientas=", ".join(nombres_herramientas) or "ninguna",
        colecciones=", ".join(m.spec.knowledge) or "ninguna",
    )
    # La fecha va en las instrucciones: sin ella, el modelo local resolvía
    # "este mes" como un periodo inventado (noviembre de 2023 en una prueba).
    contexto = f"Fecha de hoy: {hoy()}."
    return f"{cuerpo.strip()}\n\n{contexto}\n\n{catalogo.politicas().strip()}\n"
