---
titulo: Conocimiento, RAG, fine-tuning y orquestación
dueno: equipo-ia
vigente_desde: 2026-10-01
clasificacion: interna
---

## Dónde vive cada tipo de conocimiento
Se recorre en orden y se detiene en el primer sí. Si es de un cliente o cambia en vivo (factura, consumo), va por herramienta al sistema fuente. Si es un cálculo, herramienta determinista: el modelo no hace aritmética. Si es una regla que siempre aplica, va como política o guard: no se recupera, se impone. Si es pequeño y estable (pocas preguntas frecuentes, tono, glosario), va en las instrucciones. Si es extenso, cambia y hay que citarlo, va por RAG.

## Cómo funciona el RAG
En la ingesta cada documento lleva dueño, vigencia y clasificación, y se trocea según su tipo: por sección los procedimientos, por par pregunta y respuesta las preguntas frecuentes. En la consulta primero se filtra por vigencia y permisos, luego se hace búsqueda híbrida (palabras clave con BM25 más búsqueda semántica con vectores), se fusionan los resultados con RRF y se entregan los cinco mejores al agente, como dato y con cita. Las cifras tarifarias no van en RAG: van en tablas consultables por herramienta, porque una tarifa vencida no es menos relevante, es incorrecta.

## Fine-tuning
No se hace en las fases 0 a 2: no hay datos validados, el conocimiento del negocio cambia cada mes y el fine-tuning inyecta conocimiento peor que la recuperación, además de atar la plataforma a un modelo base. Tendría lugar en una tarea estrecha y de alto volumen, como resumir llamadas de ventas, destilando a un modelo pequeño cuando haya techo de calidad con instrucciones, costo relevante y miles de pares validados.

## Orquestación
Por defecto, un agente único con herramientas. Se divide en varios solo cuando las partes necesitan permisos, tiers o evaluación distintos. En procesos regulados el flujo lo decide el código y el modelo ocupa pasos acotados, como en cobranzas por la Ley 2300 de 2023. Los traspasos entre agentes son objetos tipados, nunca el historial completo. El supervisor con especialistas queda para exploración de bajo riesgo.

## Hoja de ruta
Fase 0, visibilidad (semanas 1 y 2): inventario de agentes actuales y gateway con llaves centralizadas. Fase 1, núcleo (semanas 3 a 8): manifiesto, registro, runtime con guards, MCP de facturación y medición, compuerta y migración del asistente de facturación. Fase 2, autoservicio (semanas 9 a 16): constructor y Arquitecto, conocimiento con vigencia, evaluación en línea y caducidad. Fase 3, escala (semanas 17 a 26): cobranzas con aprobación humana, enrutamiento por costo y fine-tuning solo si hay señal.
