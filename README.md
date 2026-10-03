# Plataforma de agentes de Bia — prototipo

**macOS / Linux**

1. `python3 -m venv .venv && source .venv/bin/activate && pip install -e .`
2. `ollama serve` y en otra terminal `ollama pull qwen2.5:7b-instruct qwen2.5:3b qwen3:8b nomic-embed-text`
3. `bia iniciar` registra los manifiestos e indexa el conocimiento; `bia inventario` muestra los tres inventarios
4. `bia arquitecto` abre el agente que guía y crea agentes; `bia chat sac-asistente-facturacion --sandbox` prueba el caso aplicado
5. `bia evaluar sac-procedimientos-internos` corre la compuerta (~1 min), `bia servir` levanta la API compatible con OpenAI y `pytest` corre las 85 pruebas offline

**Windows (PowerShell)**

1. `py -m venv .venv; .venv\Scripts\Activate.ps1; $env:PYTHONUTF8 = "1"; pip install -e .`
2. Instalar Ollama desde ollama.com (queda corriendo en segundo plano) y `ollama pull qwen2.5:7b-instruct qwen2.5:3b qwen3:8b nomic-embed-text`
3. `bia iniciar` registra los manifiestos e indexa el conocimiento; `bia inventario` muestra los tres inventarios
4. `bia arquitecto` abre el agente que guía y crea agentes; `bia chat sac-asistente-facturacion --sandbox` prueba el caso aplicado
5. `bia evaluar sac-procedimientos-internos` corre la compuerta (~1 min), `bia servir` levanta la API compatible con OpenAI y `pytest` corre las 85 pruebas offline

> En Windows, si PowerShell no deja activar el entorno, corre antes
> `Set-ExecutionPolicy -Scope Process RemoteSigned`. Se recomienda Windows
> Terminal, que muestra bien las tablas y los símbolos del CLI. Requiere Python
> 3.11 o superior; el prototipo se probó con Python 3.14 en macOS.

Todo corre en local con Ollama, sin llaves de API.

---

## Para entender el proyecto

Recomiendo leer estos tres documentos en este orden. Juntos explican qué se
propuso, qué se construyó y cómo verlo funcionando.

| # | Documento | Para qué sirve | Tiempo |
|---|---|---|---|
| 1 | [docs/bia-arquitectura-agentes-v5.pdf](docs/bia-arquitectura-agentes-v5.pdf) | **La propuesta.** La arquitectura completa: qué es un agente, cómo se crea sin escribir prompts, cómo se evalúa, el caso de facturación y la hoja de ruta. | 20 min |
| 2 | [docs/DECISIONES.md](docs/DECISIONES.md) | **La implementación.** Dónde vive cada pieza del documento en el código, qué se simplificó para el prototipo, cómo se tomaron las decisiones y los resultados de la compuerta. | 15 min |
| 3 | [docs/GUIA-DEMO.md](docs/GUIA-DEMO.md) | **La demo.** Un recorrido de unos 20 minutos, comando por comando, en el orden en que una persona de Bia viviría la plataforma: inventarios, compuerta, publicación, el caso aplicado, el Arquitecto y la API. | 20 min |

Si solo hay tiempo para una cosa: la sección 4 de `DECISIONES.md` y el paso 5
de `GUIA-DEMO.md`, donde el Arquitecto crea un agente nuevo a partir de una
conversación.

## Qué hay en el repositorio

```
catalogos/      Lo que cura el equipo de IA: modelos (alias), herramientas, colecciones,
                arquetipos, plantillas de instrucciones y políticas heredadas
manifiestos/    Los agentes: cada uno es un YAML versionado (borradores/ guarda los creados con el Arquitecto)
evals/          Las suites de la compuerta: una por agente y las comunes de seguridad (comunes/)
conocimiento/   Documentos de las colecciones, con dueño y vigencia
datos/          Datos sintéticos de clientes, facturas, medidores y tarifas (scripts/generar_datos.py)
mcp_servers/    Un servidor MCP por sistema: facturación, medición, tarifas, soporte, conocimiento, plataforma
plataforma/     El núcleo: manifiesto, registro, gateway, runtime, guards, conocimiento, compuerta,
                Arquitecto, trazas, API y el CLI `bia`
tests/          85 pruebas automáticas que corren sin Ollama
docs/           La propuesta, las decisiones de implementación y la guía de la demo
```

Cada módulo de `plataforma/` abre con un comentario que explica qué parte de la
arquitectura implementa y por qué está hecho así.
