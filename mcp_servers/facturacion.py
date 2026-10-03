"""MCP de facturación: solo lectura."""

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from mcp_servers._datos import cargar, mes, pesos, resolver_periodo

mcp = FastMCP("facturacion", log_level="WARNING")


@mcp.tool()
def consultar_factura(
    cliente_id: str,
    periodo: Annotated[str | None, Field(description='Texto con año y mes, por ejemplo "2026-07". Omitir si el usuario no lo menciona: se usa la factura más reciente.')] = None,
) -> dict:
    """Factura de energía del cliente: consumo facturado, costo unitario, total,
    fecha de vencimiento y estado. Incluye el saldo pendiente total."""
    periodo = resolver_periodo(cliente_id, periodo)
    facturas = cargar("facturas")[cliente_id]
    factura = next(f for f in facturas if f["periodo"] == periodo)
    pendientes = [f for f in facturas if f["estado"] == "pendiente"]
    saldo = sum(f["total_cop"] for f in pendientes)
    return {
        # Medido en la compuerta: con solo el JSON, el modelo de 7B a veces
        # reformateaba o mezclaba cifras. Un resumen ya redactado se parafrasea
        # sin hacer cuentas, y cada cifra queda verificable por el guard.
        "resumen": (
            f"Factura {factura['numero']} de {mes(periodo)}: {pesos(factura['kwh'])} kWh, total "
            f"{pesos(factura['total_cop'])} pesos, vence el {factura['fecha_vencimiento']}, estado {factura['estado']}. "
            f"Saldo pendiente total del cliente: {pesos(saldo)} pesos."
        ),
        "factura": factura,
        "saldo_pendiente_total_cop": saldo,
        "facturas_pendientes": [f["numero"] for f in pendientes],
        "periodos_disponibles": [f["periodo"] for f in facturas],
    }


if __name__ == "__main__":
    mcp.run()
