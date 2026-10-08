"""El manifiesto: qué es un agente en esta plataforma (sección 3).

Un agente es un archivo YAML declarativo y versionado. No tiene código ni
nombres de modelos. La validación ocurre en dos niveles:

1. Forma (Pydantic): que el archivo esté bien escrito.
2. Contra los catálogos (`validar`): que lo que pide exista y sea compatible.
   Aquí viven las reglas que la plataforma no negocia: escritura con
   confirmación, clasificación del dato antes que el modelo, autonomía máxima
   L4, umbral mínimo según el riesgo.

Los mensajes de error están escritos para quien creó el agente, no para un
desarrollador: el Arquitecto se los muestra tal cual.

El riesgo NO se declara: lo calcula la plataforma a partir de lo que el
agente toca. Si el creador pudiera declararlo, podría bajarlo para pasar la
compuerta con un umbral menor.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from plataforma import catalogo
from plataforma.config import RAIZ

UMBRAL_POR_RIESGO = {"bajo": 0.85, "medio": 0.90, "alto": 0.95}
AUTONOMIA_MAXIMA_FASES_1_2 = "L4"


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Metadata(_Base):
    id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)+$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    owner: str = Field(pattern=r"^[^@\s]+@[^@\s]+$")
    area: str
    archetype: str


class Modelo(_Base):
    alias: str
    fallback: str | None = None


class Instrucciones(_Base):
    template: str
    tone: str = "cercano-profesional"
    must: list[str] = []
    must_not: list[str] = []


class Herramienta(_Base):
    mcp: str
    requires_confirmation: bool = False


class Datos(_Base):
    classification: Literal["publica", "interna", "confidencial", "restringida"]
    subject_from: str | None = None
    mask_pii_in_traces: bool = True


class Calidad(_Base):
    suite: str
    min_pass_rate: float = Field(ge=0, le=1)
    inherit: list[str] = []


class Presupuesto(_Base):
    max_usd_per_conversation: float = Field(gt=0)
    monthly_cap_usd: float = Field(gt=0)


class Spec(_Base):
    purpose: str = Field(min_length=20)
    model: Modelo
    instructions: Instrucciones
    tools: list[Herramienta] = []
    knowledge: list[str] = []
    data: Datos
    autonomy: Literal["L1", "L2", "L3", "L4", "L5"]
    quality: Calidad
    budget: Presupuesto


class Manifiesto(_Base):
    apiVersion: Literal["charter/v1"]
    kind: Literal["Agent"]
    metadata: Metadata
    spec: Spec

    @property
    def id(self) -> str:
        return self.metadata.id

    @property
    def version(self) -> str:
        return self.metadata.version

    def a_yaml(self) -> str:
        return yaml.safe_dump(self.model_dump(exclude_none=True), sort_keys=False, allow_unicode=True)

    def herramienta(self, ref: str) -> Herramienta | None:
        return next((t for t in self.spec.tools if t.mcp == ref), None)


def cargar(ruta: str | Path) -> Manifiesto:
    datos = yaml.safe_load(Path(ruta).read_text(encoding="utf-8"))
    return Manifiesto.model_validate(datos)


def desde_texto(texto: str) -> Manifiesto:
    return Manifiesto.model_validate(yaml.safe_load(texto))


def riesgo(m: Manifiesto) -> str:
    """Tabla 4 del documento.

    Bajo:  interno, solo lectura.
    Medio: toca datos de clientes.
    Alto:  actúa sobre el mundo con autonomía (L3 o más con escritura) o es un
           redactor cuyo texto llega a clientes.

    Con escritura confirmada por el usuario (L2), el asistente de facturación
    queda en medio: la acción la decide una persona. Si actuara sin confirmar,
    subiría a alto.
    """
    escribe = any(catalogo.herramienta(t.mcp)["tipo"] == "escritura" for t in m.spec.tools)
    if (escribe and m.spec.autonomy in ("L3", "L4", "L5")) or catalogo.arquetipos()[m.metadata.archetype]["riesgo_base"] == "alto":
        return "alto"
    if catalogo.nivel(m.spec.data.classification) >= catalogo.nivel("confidencial"):
        return "medio"
    return "bajo"


def validar(m: Manifiesto) -> list[str]:
    """Reglas contra los catálogos. Devuelve la lista de problemas (vacía = ok)."""
    errores: list[str] = []
    arqs = catalogo.arquetipos()

    if m.metadata.archetype not in arqs:
        errores.append(f"El arquetipo '{m.metadata.archetype}' no existe. Opciones: {', '.join(arqs)}.")
        return errores

    # Primero el dato (sección 2.6): es lo único que no se negocia por calidad ni costo.
    clasif = m.spec.data.classification
    if clasif == "restringida":
        errores.append(
            "Un agente no puede trabajar con datos restringidos (bancarios, credenciales, cédulas): "
            "esos datos nunca van al modelo. Deben enmascararse o resolverse dentro de una herramienta."
        )

    for nombre_alias in filter(None, [m.spec.model.alias, m.spec.model.fallback]):
        try:
            a = catalogo.alias(nombre_alias)
        except KeyError as e:
            errores.append(str(e.args[0]))
            continue
        if catalogo.nivel(clasif) > catalogo.nivel(a["clasificacion_maxima"]):
            errores.append(f"El alias '{nombre_alias}' no está aprobado para datos '{clasif}'.")
        if catalogo.nivel(clasif) >= catalogo.nivel("confidencial") and not (
            a["retencion"] == "cero" and a["acuerdo_datos"]
        ):
            errores.append(f"Datos de clientes solo van a modelos con retención cero y acuerdo de datos; '{nombre_alias}' no cumple.")

    if m.spec.tools and not any(t.mcp == "conocimiento/buscar_conocimiento" for t in m.spec.tools) and m.spec.knowledge:
        errores.append("Declara colecciones de conocimiento pero no la herramienta conocimiento/buscar_conocimiento para consultarlas.")

    for t in m.spec.tools:
        try:
            h = catalogo.herramienta(t.mcp)
        except KeyError as e:
            errores.append(str(e.args[0]))
            continue
        if h.get("requiere_confirmacion") and not t.requires_confirmation:
            errores.append(f"'{t.mcp}' escribe en un sistema de negocio: debe declarar requires_confirmation: true.")
        if catalogo.nivel(h["clasificacion"]) > catalogo.nivel(clasif):
            errores.append(
                f"'{t.mcp}' devuelve datos '{h['clasificacion']}' pero el agente se declaró '{clasif}'. "
                "Sube la clasificación del agente o quita la herramienta."
            )
        if "cliente_id" in h.get("inyectados", {}) and m.spec.data.subject_from != "session.cliente_id":
            errores.append(f"'{t.mcp}' consulta datos de un cliente: el agente debe declarar data.subject_from: session.cliente_id.")

    for c in m.spec.knowledge:
        meta = catalogo.colecciones().get(c)
        if meta is None:
            errores.append(f"La colección '{c}' no existe.")
        elif catalogo.nivel(meta["clasificacion"]) > catalogo.nivel(clasif):
            errores.append(f"La colección '{c}' es '{meta['clasificacion']}', más sensible que el agente ('{clasif}').")

    try:
        catalogo.plantilla(m.spec.instructions.template)
    except KeyError as e:
        errores.append(str(e.args[0]))
    plantilla_arq = arqs[m.metadata.archetype]["plantilla"].split("@")[0]
    if m.spec.instructions.template.split("@")[0] != plantilla_arq:
        errores.append(f"El arquetipo '{m.metadata.archetype}' usa la plantilla '{plantilla_arq}', no '{m.spec.instructions.template}'.")

    if m.spec.autonomy > AUTONOMIA_MAXIMA_FASES_1_2:
        errores.append("En las fases 1 y 2 la autonomía máxima es L4: toda acción con efecto externo pasa por un humano.")

    nivel_riesgo = riesgo(m)
    minimo = UMBRAL_POR_RIESGO[nivel_riesgo]
    if m.spec.quality.min_pass_rate < minimo:
        errores.append(f"Con riesgo {nivel_riesgo} el umbral mínimo de la compuerta es {minimo:.0%}; declaró {m.spec.quality.min_pass_rate:.0%}.")
    if not (RAIZ / m.spec.quality.suite).exists():
        errores.append(f"No encuentro la suite de evaluación '{m.spec.quality.suite}'.")

    return errores
