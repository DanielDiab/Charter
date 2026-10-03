"""MCP de medición: lectura del medidor inteligente.

Es la ventaja que el documento le reconoce a Bia (sección 6): la serie diaria
del medidor explica una variación con precisión. Aquí detecto el día en que
cambió el patrón de consumo para que el agente no tenga que inferirlo.
"""

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from mcp_servers._datos import cargar, mes, num, pct, periodo_anterior, pesos, resolver_periodo

mcp = FastMCP("medicion", log_level="WARNING")

UMBRAL_CAMBIO = 1.15  # +15 % sostenido se reporta como cambio de patrón


def _cambio_de_patron(serie: list[float]) -> dict | None:
    mejor = None
    for d in range(3, len(serie) - 4):
        antes, despues = serie[:d], serie[d:]
        razon = (sum(despues) / len(despues)) / (sum(antes) / len(antes))
        if razon >= UMBRAL_CAMBIO and (mejor is None or razon > mejor[1]):
            mejor = (d, razon, sum(antes) / len(antes), sum(despues) / len(despues))
    if not mejor:
        return None
    d, razon, prom_antes, prom_despues = mejor
    return {
        "desde_dia": d + 1,
        "promedio_diario_antes_kwh": round(prom_antes, 1),
        "promedio_diario_despues_kwh": round(prom_despues, 1),
        "variacion_pct": round((razon - 1) * 100, 1),
    }


@mcp.tool()
def consultar_consumo(
    cliente_id: str,
    periodo: Annotated[str | None, Field(description='Texto con año y mes, por ejemplo "2026-07". Omitir si el usuario no lo menciona: se usa el más reciente.')] = None,
) -> dict:
    """Consumo medido del cliente en un periodo: total, franjas punta y fuera de
    punta, día de mayor consumo, comparación con el periodo anterior y, si lo
    hay, el día en que cambió el patrón de consumo."""
    periodo = resolver_periodo(cliente_id, periodo)
    datos = cargar("consumo")[cliente_id]
    p = datos["periodos"][periodo]
    serie = p["serie_diaria_kwh"]
    dia_max = max(range(len(serie)), key=lambda i: serie[i])
    resultado = {
        "medidor": datos["medidor"],
        "periodo": periodo,
        "kwh_total": p["kwh_total"],
        "kwh_punta": p["kwh_punta"],
        "kwh_fuera_punta": p["kwh_fuera_punta"],
        "promedio_diario_kwh": round(p["kwh_total"] / len(serie), 1),
        "dia_mayor_consumo": {"dia": dia_max + 1, "kwh": serie[dia_max]},
        "cambio_de_patron": _cambio_de_patron(serie),
    }
    resumen = f"En {mes(periodo)} el medidor registró {pesos(p['kwh_total'])} kWh."
    if anterior := periodo_anterior(cliente_id, periodo):
        kwh_ant = datos["periodos"][anterior]["kwh_total"]
        resultado["periodo_anterior"] = {
            "periodo": anterior,
            "kwh_total": kwh_ant,
            "variacion_kwh_pct": pct(p["kwh_total"], kwh_ant),
        }
        resumen += (f" Frente al mes anterior ({mes(anterior)}, {pesos(kwh_ant)} kWh) el consumo cambió "
                    f"{num(pct(p['kwh_total'], kwh_ant))} %.")
    if c := resultado["cambio_de_patron"]:
        resumen += (f" Desde el día {c['desde_dia']} el consumo diario pasó de {num(c['promedio_diario_antes_kwh'])} "
                    f"a {num(c['promedio_diario_despues_kwh'])} kWh en promedio ({num(c['variacion_pct'])} % más).")
    return {"resumen": resumen, **resultado}


if __name__ == "__main__":
    mcp.run()
