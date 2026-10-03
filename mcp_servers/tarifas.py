"""MCP de tarifas: cálculo determinista.

El modelo no hace aritmética (figura 11). Todo porcentaje o escenario que el
agente pueda necesitar lo calcula esta herramienta, para que el guard de
salida encuentre la cifra en un resultado y no tenga que confiar en el modelo.
"""

import math
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from mcp_servers._datos import cargar, mes, num, pct, periodo_anterior, pesos, resolver_periodo

mcp = FastMCP("tarifas", log_level="WARNING")

NOMBRES = {
    "G": "generación", "T": "transmisión", "D": "distribución",
    "C": "comercialización", "P": "pérdidas", "R": "restricciones",
}


def _total(kwh: float, cu: float, contribucion_pct: float) -> int:
    energia = math.floor(kwh * cu)
    return energia + math.floor(energia * contribucion_pct / 100)


@mcp.tool()
def calcular_desglose(
    cliente_id: str,
    periodo: Annotated[str | None, Field(description='Texto con año y mes, por ejemplo "2026-07". Omitir si el usuario no lo menciona: se usa el más reciente.')] = None,
    reduccion_consumo_pct: Annotated[float | None, Field(ge=0, le=100, description="Escenario: cuánto bajaría el consumo, en %.")] = None,
) -> dict:
    """Desglose de la factura por componente del costo unitario (generación,
    transmisión, distribución, comercialización, pérdidas, restricciones), qué
    explica la variación frente al periodo anterior y, si se pide, cuánto
    pagaría el cliente con menos consumo."""
    periodo = resolver_periodo(cliente_id, periodo)
    tarifas = cargar("tarifas")
    factura = next(f for f in cargar("facturas")[cliente_id] if f["periodo"] == periodo)
    comps = tarifas["periodos"][periodo]["componentes_cop_kwh"]
    kwh = factura["kwh"]

    resultado = {
        "periodo": periodo,
        "kwh": kwh,
        "cu_cop_kwh": factura["cu_cop_kwh"],
        "componentes": [
            {"codigo": c, "nombre": NOMBRES[c], "cop_kwh": v, "valor_cop": round(kwh * v)}
            for c, v in comps.items()
        ],
        "contribucion_pct": tarifas["contribucion_pct"],
        "total_cop": factura["total_cop"],
    }

    if anterior := periodo_anterior(cliente_id, periodo):
        f_ant = next(f for f in cargar("facturas")[cliente_id] if f["periodo"] == anterior)
        comps_ant = tarifas["periodos"][anterior]["componentes_cop_kwh"]
        cambios = {c: round(comps[c] - comps_ant[c], 2) for c in comps}
        mayor = max(cambios, key=cambios.get)
        # Cuánto del aumento se explica por consumo y cuánto por tarifa:
        # consumo nuevo a tarifa vieja vs. factura anterior, y el resto.
        por_consumo = _total(kwh, f_ant["cu_cop_kwh"], tarifas["contribucion_pct"]) - f_ant["total_cop"]
        por_tarifa = factura["total_cop"] - f_ant["total_cop"] - por_consumo
        diferencia = factura["total_cop"] - f_ant["total_cop"]
        # Los porcentajes también se calculan aquí. Medido en la primera prueba:
        # sin ellos, el modelo inventó "la generación explicó el 79 % del
        # aumento" y el guard de salida tuvo que tapar la respuesta entera.
        # Si el modelo necesita una cifra, la herramienta debe dársela.
        participacion = {c: round(cambios[c] / (factura["cu_cop_kwh"] - f_ant["cu_cop_kwh"]) * 100, 1) for c in comps}
        resultado["variacion"] = {
            "periodo_anterior": anterior,
            "total_anterior_cop": f_ant["total_cop"],
            "diferencia_total_cop": diferencia,
            "variacion_total_pct": pct(factura["total_cop"], f_ant["total_cop"]),
            "variacion_kwh_pct": pct(kwh, f_ant["kwh"]),
            "variacion_cu_pct": pct(factura["cu_cop_kwh"], f_ant["cu_cop_kwh"]),
            "explicado_por_consumo_cop": por_consumo,
            "explicado_por_tarifa_cop": por_tarifa,
            "explicado_por_consumo_pct": round(por_consumo / diferencia * 100, 1) if diferencia else 0,
            "explicado_por_tarifa_pct": round(por_tarifa / diferencia * 100, 1) if diferencia else 0,
            "participacion_en_aumento_cu_pct": {NOMBRES[c]: v for c, v in participacion.items()},
            "componente_que_mas_subio": {"codigo": mayor, "nombre": NOMBRES[mayor], "aumento_cop_kwh": cambios[mayor]},
        }
        v = resultado["variacion"]
        resultado["resumen"] = (
            f"La factura de {mes(periodo)} es de {pesos(factura['total_cop'])} pesos y la del mes anterior "
            f"({mes(anterior)}) fue de {pesos(f_ant['total_cop'])} pesos: subió {pesos(diferencia)} pesos "
            f"({num(v['variacion_total_pct'])} %). De ese aumento, {pesos(por_consumo)} pesos "
            f"({num(v['explicado_por_consumo_pct'])} %) se explican porque el consumo subió "
            f"{num(v['variacion_kwh_pct'])} %, y {pesos(por_tarifa)} pesos ({num(v['explicado_por_tarifa_pct'])} %) "
            f"porque el costo unitario subió {num(v['variacion_cu_pct'])} %. El componente que más subió fue "
            f"{NOMBRES[mayor]} (+{num(cambios[mayor])} pesos por kWh)."
        )

    if reduccion_consumo_pct:
        kwh_e = round(kwh * (1 - reduccion_consumo_pct / 100))
        total_e = _total(kwh_e, factura["cu_cop_kwh"], tarifas["contribucion_pct"])
        resultado["escenario"] = {
            "reduccion_consumo_pct": reduccion_consumo_pct,
            "kwh": kwh_e,
            "total_cop": total_e,
            "ahorro_cop": factura["total_cop"] - total_e,
        }
        resultado["resumen_escenario"] = (
            f"Con {num(reduccion_consumo_pct)} % menos consumo ({pesos(kwh_e)} kWh) la factura sería de "
            f"{pesos(total_e)} pesos, un ahorro de {pesos(factura['total_cop'] - total_e)} pesos."
        )
    return resultado


if __name__ == "__main__":
    mcp.run()
