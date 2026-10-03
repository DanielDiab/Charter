"""Genera los datos sintéticos que sirven los servidores MCP del prototipo.

Ningún dato de aquí es de un cliente real de Bia. Los genero con un script, y
no a mano, por una razón concreta: el guard de salida verifica que cada cifra
de una respuesta aparezca en el resultado de alguna herramienta. Si las
facturas no cuadraran con el consumo y la tarifa, la compuerta de evaluación
estaría midiendo errores míos en los datos y no errores del agente.

Uso:  python scripts/generar_datos.py      (sobrescribe datos/*.json)

Las tarifas son ilustrativas: siguen la estructura del costo unitario (CU) de la
regulación colombiana (G + T + D + C + P + R), pero los valores no son los
publicados por ningún comercializador.
"""

import json
import math
import random
from pathlib import Path

DATOS = Path(__file__).resolve().parents[1] / "datos"

PERIODOS = ["2026-07", "2026-08", "2026-09"]

# COP/kWh por componente. Septiembre sube generación y restricciones: es la
# historia que el asistente tiene que poder explicar con datos.
TARIFAS = {
    "2026-07": {"G": 331.40, "T": 54.80, "D": 259.60, "C": 74.90, "P": 44.70, "R": 29.80},
    "2026-08": {"G": 344.10, "T": 55.30, "D": 261.20, "C": 75.40, "P": 45.60, "R": 41.30},
    "2026-09": {"G": 372.60, "T": 55.90, "D": 262.00, "C": 76.10, "P": 46.80, "R": 58.20},
}
CONTRIBUCION_PCT = 20  # contribución de solidaridad, usuarios comerciales

CLIENTES = [
    {
        "cliente_id": "CLI-001",
        "razon_social": "Panadería La Espiga S.A.S.",
        "nit": "900123456-1",
        "contacto": "compras@laespiga.example",
        "telefono": "3001112233",
        "segmento": "comercial",
        "medidor": "MI-55021",
        # Horno nuevo desde el 8 de septiembre: el medidor lo muestra.
        "base_kwh_dia": 140.0,
        "cambio": {"periodo": "2026-09", "desde_dia": 8, "factor": 1.38},
    },
    {
        "cliente_id": "CLI-002",
        "razon_social": "Taller Metalmecánico Andes Ltda.",
        "nit": "800987654-3",
        "contacto": "gerencia@tallerandes.example",
        "telefono": "3104445566",
        "segmento": "comercial",
        "medidor": "MI-55340",
        "base_kwh_dia": 310.0,
        "cambio": None,
        "saldo_anterior_pendiente": True,
    },
    {
        "cliente_id": "CLI-003",
        "razon_social": "Clínica Veterinaria Norte S.A.S.",
        "nit": "901555222-7",
        "contacto": "admin@vetnorte.example",
        "telefono": "3157778899",
        "segmento": "comercial",
        "medidor": "MI-56012",
        "base_kwh_dia": 95.0,
        "cambio": None,
    },
]

DIAS = {"2026-07": 31, "2026-08": 31, "2026-09": 30}
VENCE = {"2026-07": "2026-08-20", "2026-08": "2026-09-20", "2026-09": "2026-10-20"}


def cu(periodo: str) -> float:
    return round(sum(TARIFAS[periodo].values()), 2)


def serie_diaria(cliente: dict, periodo: str, rng: random.Random) -> list[float]:
    serie = []
    for dia in range(1, DIAS[periodo] + 1):
        base = cliente["base_kwh_dia"]
        cambio = cliente.get("cambio")
        if cambio and cambio["periodo"] == periodo and dia >= cambio["desde_dia"]:
            base *= cambio["factor"]
        # Domingos más bajos: que la serie se parezca a un negocio real.
        factor_semana = 0.55 if dia % 7 == 0 else 1.0
        serie.append(round(base * factor_semana * rng.uniform(0.93, 1.07), 1))
    return serie


def main() -> None:
    rng = random.Random(2026)  # semilla fija: los datos no cambian entre corridas
    consumo, facturas = {}, {}

    for c in CLIENTES:
        cid = c["cliente_id"]
        consumo[cid] = {"medidor": c["medidor"], "periodos": {}}
        facturas[cid] = []
        for i, periodo in enumerate(PERIODOS):
            diaria = serie_diaria(c, periodo, rng)
            kwh = round(sum(diaria))
            punta = round(kwh * 0.41)
            consumo[cid]["periodos"][periodo] = {
                "kwh_total": kwh,
                "kwh_punta": punta,
                "kwh_fuera_punta": kwh - punta,
                "serie_diaria_kwh": diaria,
            }

            valor_energia = math.floor(kwh * cu(periodo))
            contribucion = math.floor(valor_energia * CONTRIBUCION_PCT / 100)
            total = valor_energia + contribucion
            ultimo = i == len(PERIODOS) - 1
            pagada = not ultimo and not (c.get("saldo_anterior_pendiente") and i == 1)
            facturas[cid].append(
                {
                    "numero": f"FE-{cid[-3:]}-{periodo.replace('-', '')}",
                    "periodo": periodo,
                    "kwh": kwh,
                    "cu_cop_kwh": cu(periodo),
                    "valor_energia_cop": valor_energia,
                    "contribucion_cop": contribucion,
                    "total_cop": total,
                    "fecha_vencimiento": VENCE[periodo],
                    "estado": "pagada" if pagada else "pendiente",
                }
            )

    tarifas = {
        "nota": "Valores ilustrativos para el prototipo. No son tarifas publicadas.",
        "contribucion_pct": CONTRIBUCION_PCT,
        "periodos": {
            p: {"componentes_cop_kwh": comps, "cu_cop_kwh": cu(p), "vigente_desde": f"{p}-01"}
            for p, comps in TARIFAS.items()
        },
    }
    clientes = [
        {k: v for k, v in c.items() if k not in ("base_kwh_dia", "cambio", "saldo_anterior_pendiente")}
        for c in CLIENTES
    ]
    # SSO simulado: el token es lo único que el canal manda; el cliente_id sale
    # de aquí, nunca del texto de la conversación.
    sesiones = {
        "tok-espiga": {"cliente_id": "CLI-001", "usuario": "compras@laespiga.example"},
        "tok-andes": {"cliente_id": "CLI-002", "usuario": "gerencia@tallerandes.example"},
        "tok-vetnorte": {"cliente_id": "CLI-003", "usuario": "admin@vetnorte.example"},
        "tok-empleado": {"cliente_id": None, "usuario": "asesor.sac@bia.app"},
    }

    for nombre, contenido in [
        ("clientes.json", clientes),
        ("consumo.json", consumo),
        ("facturas.json", facturas),
        ("tarifas.json", tarifas),
        ("sesiones.json", sesiones),
    ]:
        (DATOS / nombre).write_text(json.dumps(contenido, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Datos sintéticos escritos en {DATOS}")


if __name__ == "__main__":
    main()
