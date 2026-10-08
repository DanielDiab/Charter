"""CLI `charter`: la consola del prototipo.

En la propuesta la consola es una aplicación web (inventarios, constructor,
aprobaciones). Para el prototipo es este CLI: cubre el mismo recorrido sin
agregar un frontend que mantener. Los comandos siguen el camino pavimentado:

    charter iniciar                       registra los manifiestos e indexa el conocimiento
    charter inventario                    los tres inventarios
    charter arquitecto                    el agente que guía la creación de agentes
    charter chat sac-asistente-facturacion --sandbox     probar un borrador
    charter evaluar sac-asistente-facturacion            la compuerta
    charter aprobar sac-asistente-facturacion --rol dueno --quien lider.sac@energia.example
    charter publicar sac-asistente-facturacion           solo si pasó todo lo anterior
    charter servir                        la API compatible con OpenAI
    charter costos | trazas | metricas    observabilidad
"""

import asyncio
import json
import uuid
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from plataforma import catalogo, conocimiento, inventario, monitoreo, registro, trazas
from plataforma.config import DATOS, MANIFIESTOS, RAIZ
from plataforma.gateway import gateway
from plataforma.manifiesto import cargar, riesgo, validar

consola = Console()
COLOR_ESTADO = {"borrador": "yellow", "evaluacion": "cyan", "publicado": "green",
                "suspendido": "red", "deprecado": "dim", "retirado": "dim"}


@click.group()
def cli():
    """Charter: plataforma de agentes, prototipo del corte vertical."""
    # Re-certificación automática: si alguien cambió un alias, una herramienta,
    # una colección o una plantilla, los agentes afectados vuelven a evaluación
    # antes de que este proceso sirva una sola respuesta.
    for c in registro.verificar_recertificacion():
        consola.print(f"[yellow]Re-certificación:[/] {c['agente']} v{c['version']} vuelve a evaluación "
                      f"porque cambió {', '.join(c['cambios'])}.")


# ── Registro e inventarios ───────────────────────────────────────────────


@cli.command()
def iniciar():
    """Registra los manifiestos de manifiestos/ e indexa el conocimiento."""
    rutas = sorted(MANIFIESTOS.glob("*.yaml")) + sorted((MANIFIESTOS / "borradores").glob("*.yaml"))
    for ruta in rutas:
        try:
            estado = registro.registrar(cargar(ruta))
            consola.print(f"  [green]✓[/] {ruta.relative_to(RAIZ)} → {estado}")
        except Exception as exc:  # noqa: BLE001
            consola.print(f"  [red]✗[/] {ruta.relative_to(RAIZ)}: {exc}")
    consola.print("Indexando conocimiento (con embeddings si Ollama responde)...")
    resumen = asyncio.run(conocimiento.ingestar(gateway()))
    consola.print(f"  {resumen['fragmentos']} fragmentos · {resumen['por_coleccion']} · embeddings: {resumen['embeddings']}")


@cli.command("validar")
@click.argument("ruta", type=click.Path(exists=True))
def validar_cmd(ruta):
    """Valida un manifiesto contra los catálogos sin registrarlo."""
    m = cargar(ruta)
    errores = validar(m)
    if errores:
        consola.print(Panel("\n".join(f"• {e}" for e in errores), title=f"{m.id}: no cumple", border_style="red"))
        raise SystemExit(1)
    consola.print(f"[green]{m.id} v{m.version} cumple la arquitectura.[/] Riesgo calculado: {riesgo(m)}.")


@cli.command("registrar")
@click.argument("ruta", type=click.Path(exists=True))
def registrar_cmd(ruta):
    """Registra (o actualiza) un manifiesto como borrador."""
    m = cargar(ruta)
    try:
        consola.print(f"{m.id} v{m.version} → {registro.registrar(m)}")
    except registro.ErrorRegistro as exc:
        consola.print(f"[red]{exc}[/]")
        raise SystemExit(1)


@cli.command("inventario")
@click.argument("cual", required=False, type=click.Choice(["agentes", "modelos", "orquestacion"]))
def inventario_cmd(cual):
    """Inventarios de agentes, modelos y orquestación."""
    if cual in (None, "agentes"):
        t = Table(title="Inventario de agentes — ¿cuántos hay y qué tocan?")
        for col in ("agente", "versión", "estado", "dueño", "área", "alias → modelo", "datos", "aut.", "riesgo", "herramientas", "US$"):
            t.add_column(col)
        for a in inventario.agentes():
            t.add_row(a["id"], a["version"], f"[{COLOR_ESTADO[a['estado']]}]{a['estado']}[/]", a["dueno"], a["area"],
                      f"{a['alias']} → {a['modelo_hoy']}", a["clasificacion"], a["autonomia"], a["riesgo"],
                      str(len(a["herramientas"])), f"{a['costo_usd_acumulado']:.4f}")
        consola.print(t)
    if cual in (None, "modelos"):
        t = Table(title="Inventario de modelos — ¿con qué corren?")
        for col in ("alias", "modelo", "proveedor", "retención", "datos hasta", "US$/M in·out", "agentes"):
            t.add_column(col)
        for m in inventario.modelos():
            precio = m["precio_usd_por_millon"]
            t.add_row(m["alias"], m["modelo"], m["proveedor"], m["retencion"], m["datos_hasta"],
                      f"{precio['entrada']}·{precio['salida']}", "\n".join(m["agentes"]) or "—")
        consola.print(t)
    if cual in (None, "orquestacion"):
        o = inventario.orquestacion()
        t = Table(title="Inventario de orquestación — ¿qué puede hacer cada uno?")
        for col in ("herramienta", "tipo", "confirmación", "datos", "agentes"):
            t.add_column(col)
        for h in o["herramientas"]:
            t.add_row(h["ref"], h["tipo"], "sí" if h["confirmacion"] else "", h["clasificacion"], ", ".join(h["agentes"]) or "—")
        consola.print(t)
        t = Table(title="Colecciones de conocimiento")
        for col in ("colección", "dueño", "datos", "fragmentos vigentes", "vencidos", "agentes"):
            t.add_column(col)
        for c in o["colecciones"]:
            t.add_row(c["coleccion"], c["dueno"], c["clasificacion"], str(c["fragmentos_vigentes"]),
                      str(c["fragmentos_vencidos"]), ", ".join(c["agentes"]) or "—")
        consola.print(t)
        consola.print("Flujos: " + " · ".join(f"{f['agente']} ({f['patron']})" for f in o["flujos"]))


# ── Compuerta y publicación ──────────────────────────────────────────────


@cli.command()
@click.argument("id_agente")
@click.option("--version")
@click.option("--juez", is_flag=True, help="Evalúa también las rúbricas con el tier razonamiento.")
@click.option("--casos", help="Solo estos casos (separados por coma). No habilita publicación.")
def evaluar(id_agente, version, juez, casos):
    """Corre la compuerta de evaluación sobre un agente."""
    from plataforma import evaluacion, runtime
    from plataforma.mcp import Conexiones

    def progreso(capa, r):
        marca = "[green]✓[/]" if r["paso"] else "[red]✗[/]"
        consola.print(f"  {marca} {capa:<14} {r['id']:<28} {r['latencia_s']:>5}s  {'; '.join(r['fallas'])[:110]}")

    async def correr():
        async with Conexiones() as cx:
            agente = await runtime.abrir(id_agente, cx, entorno="evaluacion", version=version)
            consola.print(f"Compuerta para [bold]{agente.m.id} v{agente.m.version}[/] (riesgo {riesgo(agente.m)}, "
                          f"modelo {catalogo.alias(agente.m.spec.model.alias)['modelo']})")
            return await evaluacion.evaluar(agente, usar_juez=juez, solo=casos.split(",") if casos else None, progreso=progreso)

    rep = asyncio.run(correr())
    c1, c3 = rep["capa1_suite_propia"], rep["capa3_costo_latencia"]
    lineas = [
        f"Capa 1 · suite propia: {c1['pasaron']}/{c1['total']} = {c1['tasa']:.0%} (umbral {rep['umbral']:.0%})",
        *[f"Capa 2 · {k}: {v['pasaron']}/{v['total']}" for k, v in rep["capa2_suites_comunes"].items()],
        f"Capa 3 · costo promedio US${c3['costo_promedio_usd']:.5f} (tope {c3['presupuesto_usd']}) · "
        f"latencia p95 {c3['latencia_p95_s']}s (tope {c3['latencia_max_s']}s)",
    ]
    color = "green" if rep["aprobado"] else "red"
    lineas += [f"[yellow]⚠ {a}[/]" for a in rep.get("advertencias", [])]
    consola.print(Panel("\n".join(lineas), title=rep["resumen"], border_style=color))
    if rep["aprobado"]:
        # Comandos listos para copiar: con marcadores como <rol>, la shell los
        # interpreta como redirecciones y el comando falla.
        dueno = registro.obtener(id_agente, rep["version"])[0].metadata.owner
        quien = {"dueno": dueno, "equipo-ia": "equipo.ia@energia.example", "cumplimiento": "cumplimiento@energia.example"}
        consola.print(f"Aprobaciones necesarias (riesgo {rep['riesgo']}). Para registrarlas y publicar:")
        for rol in registro.APROBACIONES[rep["riesgo"]]:
            consola.print(f"  charter aprobar {id_agente} --rol {rol} --quien {quien[rol]}", highlight=False)
        consola.print(f"  charter publicar {id_agente}", highlight=False)


@cli.command()
@click.argument("id_agente")
@click.option("--rol", required=True, type=click.Choice(["dueno", "equipo-ia", "cumplimiento"]))
@click.option("--quien", required=True, help="Correo de quien aprueba.")
@click.option("--version")
def aprobar(id_agente, rol, quien, version):
    """Registra una aprobación (en producción viene del SSO, no de un parámetro)."""
    m, _ = registro.obtener(id_agente, version)
    try:
        hechas = registro.aprobar(id_agente, m.version, rol, quien)
        consola.print(f"Aprobaciones de {id_agente} v{m.version}: {', '.join(hechas)}")
    except registro.ErrorRegistro as exc:
        consola.print(f"[red]{exc}[/]")
        raise SystemExit(1)


@cli.command()
@click.argument("id_agente")
@click.option("--version")
def publicar(id_agente, version):
    """Publica un agente que pasó la compuerta y tiene sus aprobaciones."""
    try:
        v = registro.publicar(id_agente, version)
        consola.print(f"[green]{id_agente} v{v} publicado.[/] Ya aparece en /v1/models de la API.")
    except registro.ErrorRegistro as exc:
        consola.print(f"[red]{exc}[/]")
        raise SystemExit(1)


@cli.command()
@click.argument("id_agente")
@click.option("--motivo", required=True)
def suspender(id_agente, motivo):
    """Suspende el agente publicado (incidente manual)."""
    m = registro.obtener_publicado(id_agente)
    registro.suspender(id_agente, m.version, motivo)
    consola.print(f"[red]{id_agente} v{m.version} suspendido.[/]")


@cli.command()
@click.argument("id_agente")
def reactivar(id_agente):
    """Un agente suspendido vuelve a evaluación, nunca directo a publicado."""
    m, _ = registro.obtener(id_agente, estado="suspendido")
    registro.reactivar(id_agente, m.version)
    consola.print(f"{id_agente} v{m.version} → evaluacion. Corre `charter evaluar {id_agente}`.")


@cli.command()
@click.argument("id_agente", required=False)
def eventos(id_agente):
    """Historia del ciclo de vida (registro, compuerta, aprobaciones, re-certificaciones)."""
    import datetime

    t = Table(title="Eventos del registro")
    for col in ("fecha", "agente", "versión", "evento", "detalle"):
        t.add_column(col)
    for e in registro.eventos(id_agente):
        t.add_row(datetime.datetime.fromtimestamp(e["ts"]).strftime("%m-%d %H:%M"), e["id"], e["version"], e["evento"], e["detalle"][:90])
    consola.print(t)


# ── Conversar ────────────────────────────────────────────────────────────


def _conversar(id_agente: str, sesion: dict, entorno: str, version: str | None, bienvenida: str | None = None):
    from plataforma import runtime
    from plataforma.mcp import Conexiones

    async def bucle():
        async with Conexiones() as cx:
            agente = await runtime.abrir(id_agente, cx, entorno=entorno, version=version)
            conversacion = uuid.uuid4().hex[:12]
            consola.print(Panel(
                f"{agente.m.id} v{agente.m.version} · entorno {entorno} · alias {agente.m.spec.model.alias} "
                f"({catalogo.alias(agente.m.spec.model.alias)['modelo']}) · sesión {sesion.get('cliente_id') or sesion.get('usuario')}\n"
                f"conversación {conversacion} · 'salir' para terminar",
                border_style="blue"))
            if bienvenida:
                consola.print(f"[bold blue]{agente.m.id}[/] › {bienvenida}\n")
            while True:
                try:
                    texto = (await asyncio.to_thread(consola.input, "[bold]tú[/] › ")).strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if texto.lower() in ("salir", "exit", "quit"):
                    break
                if not texto:
                    continue
                primero = True
                with consola.status("pensando...", spinner="dots") as estado:
                    async for ev in agente.responder(texto, sesion, conversacion):
                        if ev["tipo"] == "herramienta":
                            estado.update(f"usando {ev['ref']}...")
                            consola.print(f"  [dim]⚙ {ev['ref']} ({ev['estado']})[/]")
                        elif ev["tipo"] == "guard":
                            consola.print(f"  [yellow]⛨ guard de {ev['capa']}: {ev['motivo']}[/]")
                        elif ev["tipo"] == "pendiente":
                            consola.print(f"  [yellow]⏸ {ev['ref']} retenida hasta tu confirmación[/]")
                        elif ev["tipo"] == "bloque":
                            prefijo = f"[bold blue]{agente.m.id}[/] › " if primero else ""
                            consola.print(prefijo + ev["texto"])
                            primero = False
                costo = trazas.costo_conversacion(conversacion)
                consola.print(f"[dim]  costo acumulado de la conversación: US${costo:.5f}[/]\n")

    asyncio.run(bucle())


@cli.command()
@click.argument("id_agente")
@click.option("--cliente", default="CLI-001", help="Cliente de la sesión simulada (CLI-001, CLI-002, CLI-003).")
@click.option("--sandbox", is_flag=True, help="Permite conversar con un borrador. Las trazas quedan como sandbox.")
@click.option("--version")
def chat(id_agente, cliente, sandbox, version):
    """Conversa con un agente. Sin --sandbox, solo agentes publicados."""
    sesiones = json.loads((DATOS / "sesiones.json").read_text(encoding="utf-8"))
    sesion = next((s for s in sesiones.values() if s["cliente_id"] == cliente), {"cliente_id": cliente})
    try:
        _conversar(id_agente, sesion, "sandbox" if sandbox else "produccion", version)
    except registro.ErrorRegistro as exc:
        consola.print(f"[red]{exc}[/] ¿Querías probar el borrador? Usa --sandbox.")


@cli.command()
def arquitecto():
    """El Arquitecto: pregúntale por la plataforma o crea un agente con él."""
    try:
        registro.obtener_publicado("plataforma-arquitecto")
        entorno = "produccion"
    except registro.ErrorRegistro:
        entorno = "sandbox"
        consola.print("[dim]El Arquitecto aún no está publicado: corre en sandbox. "
                      "Para publicarlo: charter evaluar plataforma-arquitecto.[/]")
    _conversar("plataforma-arquitecto", {"cliente_id": None, "usuario": "empleado@energia.example"}, entorno, None,
               bienvenida="Hola, soy el Arquitecto. Puedo explicarte cómo funciona la plataforma de agentes "
                          "o acompañarte a crear un agente nuevo sin escribir prompts. ¿Qué necesitas?")


# ── Observabilidad ───────────────────────────────────────────────────────


@cli.command()
def costos():
    """Costo por agente, área y entorno, desde las trazas."""
    t = Table(title="Costos (costo sombra con precios de referencia del catálogo)")
    for col in ("agente", "área", "entorno", "conversaciones", "llamadas LLM", "tokens in", "tokens out", "US$"):
        t.add_column(col)
    for f in trazas.costos_por_agente():
        t.add_row(f["agente"], f["area"], f["entorno"], str(f["conversaciones"]), str(f["llamadas_llm"]),
                  str(f["tokens_entrada"]), str(f["tokens_salida"]), f"{f['costo_usd']:.5f}")
    consola.print(t)


@cli.command("trazas")
@click.option("--conversacion")
@click.option("--agente")
@click.option("-n", default=25)
def trazas_cmd(conversacion, agente, n):
    """Últimos spans (PII enmascarada)."""
    t = Table(title="Trazas")
    for col in ("agente", "entorno", "tipo", "nombre", "modelo", "tokens", "US$", "ms", "estado", "detalle"):
        t.add_column(col, overflow="fold")
    for s in reversed(trazas.spans(conversacion, agente, n)):
        t.add_row(s["agente"], s["entorno"], s["tipo"], s["nombre"], s["modelo"],
                  f"{s['tokens_entrada']}/{s['tokens_salida']}", f"{s['costo_usd']:.5f}", str(s["latencia_ms"]),
                  s["estado"], s["detalle"][:80])
    consola.print(t)


@cli.command("metricas")
@click.argument("id_agente")
@click.option("--entorno", default="produccion", type=click.Choice(["produccion", "sandbox", "evaluacion"]))
def metricas_cmd(id_agente, entorno):
    """Las cinco dimensiones de monitoreo de un agente."""
    consola.print_json(json.dumps(monitoreo.metricas(id_agente, entorno), ensure_ascii=False))


@cli.command()
@click.option("--puerto", default=8000)
def servir(puerto):
    """Levanta la API compatible con OpenAI."""
    import uvicorn

    uvicorn.run("plataforma.api:app", host="127.0.0.1", port=puerto)


def main():
    cli()


if __name__ == "__main__":
    main()
