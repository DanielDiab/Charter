"""Registro de agentes: el inventario de agentes y su ciclo de vida (figura 17).

El inventario no es una hoja de cálculo que alguien mantiene: es una vista de
este registro, y sin registro no hay camino a producción (P2). La API solo
sirve agentes en estado `publicado`, así que un agente que no pasó por aquí
simplemente no existe para los canales.

Ciclo de vida:

    borrador ──enviar──▶ evaluacion ──pasa compuerta + aprobaciones──▶ publicado
        ▲                    │                                           │  │  │
        └──── falla ─────────┘          re-certificación (cambió algo) ◀─┘  │  │
                                        suspendido (incidente) ◀────────────┘  │
                                        deprecado (nueva versión o 90 días) ◀──┘

Lo que dispara la plataforma sola (en ámbar en el documento): re-certificación
cuando cambia una dependencia, suspensión por incidente y caducidad.
"""

import json
import sqlite3
import time

from plataforma import catalogo
from plataforma.config import config
from plataforma.manifiesto import Manifiesto, desde_texto, riesgo, validar

ESTADOS = ["borrador", "evaluacion", "publicado", "suspendido", "deprecado", "retirado"]

# Quién debe aprobar según el riesgo (tabla 4). El dueño siempre.
APROBACIONES = {
    "bajo": ["dueno"],
    "medio": ["dueno", "equipo-ia"],
    "alto": ["dueno", "equipo-ia", "cumplimiento"],
}
DIAS_CADUCIDAD = 90


class ErrorRegistro(Exception):
    pass


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(config().estado_dir / "registro.db")
    con.row_factory = sqlite3.Row
    con.execute(
        """CREATE TABLE IF NOT EXISTS agentes (
            id TEXT, version TEXT, estado TEXT, manifiesto TEXT, riesgo TEXT,
            huellas TEXT, reporte TEXT, aprobaciones TEXT, creado REAL, actualizado REAL,
            PRIMARY KEY (id, version))"""
    )
    con.execute("CREATE TABLE IF NOT EXISTS eventos (ts REAL, id TEXT, version TEXT, evento TEXT, detalle TEXT)")
    return con


def _evento(con, id_: str, version: str, evento: str, detalle: str = "") -> None:
    con.execute("INSERT INTO eventos VALUES (?,?,?,?,?)", (time.time(), id_, version, evento, detalle))


def _version_tupla(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


# ── Altas y consultas ────────────────────────────────────────────────────


def registrar(m: Manifiesto) -> str:
    """Registra un manifiesto como borrador. Devuelve el estado resultante.

    Un manifiesto publicado es inmutable: cambiarlo sin subir la versión
    rompería la trazabilidad ("¿con qué instrucciones respondió esto?").
    """
    errores = validar(m)
    if errores:
        raise ErrorRegistro("El manifiesto no cumple la arquitectura:\n- " + "\n- ".join(errores))
    texto = m.a_yaml()
    ahora = time.time()
    with _con() as con:
        fila = con.execute("SELECT * FROM agentes WHERE id=? AND version=?", (m.id, m.version)).fetchone()
        if fila is None:
            con.execute(
                "INSERT INTO agentes VALUES (?,?,?,?,?,?,?,?,?,?)",
                (m.id, m.version, "borrador", texto, riesgo(m), "{}", "null", "[]", ahora, ahora),
            )
            _evento(con, m.id, m.version, "registrado", f"riesgo {riesgo(m)}")
            return "borrador"
        if fila["manifiesto"] == texto:
            return fila["estado"]
        if fila["estado"] not in ("borrador", "evaluacion"):
            raise ErrorRegistro(
                f"{m.id} v{m.version} está '{fila['estado']}': un manifiesto publicado no se edita. Sube la versión."
            )
        # Cambió el borrador: la evaluación anterior ya no aplica.
        con.execute(
            "UPDATE agentes SET manifiesto=?, riesgo=?, estado='borrador', reporte='null', aprobaciones='[]', actualizado=? "
            "WHERE id=? AND version=?",
            (texto, riesgo(m), ahora, m.id, m.version),
        )
        _evento(con, m.id, m.version, "actualizado", "el borrador cambió; vuelve a requerir evaluación")
        return "borrador"


def _fila(id_: str, version: str | None = None, estado: str | None = None) -> sqlite3.Row:
    with _con() as con:
        filas = con.execute("SELECT * FROM agentes WHERE id=?", (id_,)).fetchall()
    if version:
        filas = [f for f in filas if f["version"] == version]
    if estado:
        filas = [f for f in filas if f["estado"] == estado]
    if not filas:
        detalle = f" v{version}" if version else ""
        detalle += f" en estado '{estado}'" if estado else ""
        raise ErrorRegistro(f"No hay agente '{id_}'{detalle} en el registro.")
    return max(filas, key=lambda f: _version_tupla(f["version"]))


def obtener(id_: str, version: str | None = None, estado: str | None = None) -> tuple[Manifiesto, dict]:
    f = _fila(id_, version, estado)
    return desde_texto(f["manifiesto"]), {
        "estado": f["estado"],
        "riesgo": f["riesgo"],
        "reporte": json.loads(f["reporte"]),
        "aprobaciones": json.loads(f["aprobaciones"]),
        "huellas": json.loads(f["huellas"]),
    }


def obtener_publicado(id_: str) -> Manifiesto:
    return obtener(id_, estado="publicado")[0]


def listar() -> list[dict]:
    with _con() as con:
        return [dict(f) for f in con.execute("SELECT * FROM agentes ORDER BY id, version").fetchall()]


def eventos(id_: str | None = None) -> list[dict]:
    with _con() as con:
        q = "SELECT * FROM eventos" + (" WHERE id=?" if id_ else "") + " ORDER BY ts"
        return [dict(f) for f in con.execute(q, (id_,) if id_ else ()).fetchall()]


# ── Transiciones ─────────────────────────────────────────────────────────


def _cambiar(id_: str, version: str, estado: str, evento: str, detalle: str = "", **campos) -> None:
    sets = ", ".join(["estado=?", "actualizado=?"] + [f"{k}=?" for k in campos])
    with _con() as con:
        con.execute(f"UPDATE agentes SET {sets} WHERE id=? AND version=?",
                    (estado, time.time(), *campos.values(), id_, version))
        _evento(con, id_, version, evento, detalle)


def guardar_reporte(id_: str, version: str, reporte: dict) -> None:
    """Lo llama la compuerta. Si no pasa, el agente vuelve a borrador con el reporte."""
    estado = "evaluacion" if reporte["aprobado"] else "borrador"
    _cambiar(id_, version, estado, "compuerta_aprobada" if reporte["aprobado"] else "compuerta_fallida",
             reporte["resumen"], reporte=json.dumps(reporte, ensure_ascii=False), aprobaciones="[]")


def aprobar(id_: str, version: str, rol: str, quien: str) -> list[str]:
    m, info = obtener(id_, version)
    if not (info["reporte"] and info["reporte"]["aprobado"]):
        raise ErrorRegistro("No se aprueba algo que no pasó la compuerta. Corre primero `charter evaluar`.")
    if rol not in APROBACIONES[info["riesgo"]]:
        raise ErrorRegistro(f"Con riesgo {info['riesgo']} las aprobaciones son: {APROBACIONES[info['riesgo']]}.")
    aprobaciones = [a for a in info["aprobaciones"] if a["rol"] != rol] + [{"rol": rol, "quien": quien}]
    _cambiar(id_, version, info["estado"], "aprobado", f"{rol}: {quien}", aprobaciones=json.dumps(aprobaciones))
    return [a["rol"] for a in aprobaciones]


def publicar(id_: str, version: str | None = None) -> str:
    m, info = obtener(id_, version)
    reporte = info["reporte"]
    if info["estado"] != "evaluacion" or not reporte or not reporte["aprobado"]:
        raise ErrorRegistro(f"{id_} v{m.version} está '{info['estado']}' sin compuerta aprobada. Corre `charter evaluar {id_}`.")
    if reporte["huella_manifiesto"] != catalogo.huella(m.a_yaml()):
        raise ErrorRegistro("El manifiesto cambió después de evaluarlo. Vuelve a correr la compuerta.")
    faltan = [r for r in APROBACIONES[info["riesgo"]] if r not in {a["rol"] for a in info["aprobaciones"]}]
    if faltan:
        raise ErrorRegistro(f"Riesgo {info['riesgo']}: faltan aprobaciones de {', '.join(faltan)} (`charter aprobar`).")

    # Una sola versión publicada por agente: la anterior se depreca (deja de
    # recibir tráfico nuevo pero su traza se conserva).
    for f in listar():
        if f["id"] == id_ and f["estado"] == "publicado" and f["version"] != m.version:
            _cambiar(id_, f["version"], "deprecado", "deprecado", f"reemplazado por v{m.version}")
    huellas = catalogo.huella_dependencias(m)
    _cambiar(id_, m.version, "publicado", "publicado", f"aprobaciones: {info['aprobaciones']}",
             huellas=json.dumps(huellas))
    return m.version


def suspender(id_: str, version: str, motivo: str) -> None:
    _cambiar(id_, version, "suspendido", "suspendido", motivo)


def reactivar(id_: str, version: str) -> None:
    """Un agente suspendido vuelve a evaluación, nunca directo a publicado."""
    _cambiar(id_, version, "evaluacion", "reactivado", "vuelve a pasar la compuerta", reporte="null", aprobaciones="[]")


def deprecar(id_: str, version: str, motivo: str) -> None:
    _cambiar(id_, version, "deprecado", "deprecado", motivo)


# ── Lo que la plataforma dispara sola ────────────────────────────────────


def verificar_recertificacion() -> list[dict]:
    """Compara las huellas guardadas al publicar con las de hoy. Si cambió el
    modelo detrás de un alias, una herramienta, una colección, la plantilla o
    las políticas, el agente vuelve a evaluación.

    Esto es lo que hace que cambiar de modelo deje de ser un riesgo: nadie
    tiene que acordarse de volver a probar. Corre al iniciar el CLI y la API.
    """
    cambios = []
    for f in listar():
        if f["estado"] != "publicado":
            continue
        m = desde_texto(f["manifiesto"])
        antes, ahora = json.loads(f["huellas"]), catalogo.huella_dependencias(m)
        diferentes = sorted(k for k in set(antes) | set(ahora) if antes.get(k) != ahora.get(k))
        if diferentes:
            _cambiar(f["id"], f["version"], "evaluacion", "recertificacion",
                     "cambió: " + ", ".join(diferentes), reporte="null", aprobaciones="[]")
            cambios.append({"agente": f["id"], "version": f["version"], "cambios": diferentes})
    return cambios


def verificar_caducidad(ultimo_uso: dict[str, float], ahora: float | None = None) -> list[str]:
    """Depreca agentes publicados sin uso en producción en 90 días. Sin esto,
    toda plataforma de autoservicio se llena de agentes huérfanos."""
    ahora = ahora or time.time()
    limite = DIAS_CADUCIDAD * 86400
    deprecados = []
    for f in listar():
        if f["estado"] != "publicado":
            continue
        referencia = ultimo_uso.get(f["id"], f["actualizado"])
        if ahora - referencia > limite:
            deprecar(f["id"], f["version"], f"sin uso en {DIAS_CADUCIDAD} días")
            deprecados.append(f["id"])
    return deprecados
