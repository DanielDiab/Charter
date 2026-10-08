---
titulo: Evaluación antes de publicar y monitoreo en producción
dueno: equipo-ia
vigente_desde: 2026-10-01
clasificacion: interna
---

## La compuerta de evaluación
Antes de publicar, la compuerta corre tres capas. Capa 1, la suite propia del agente: sus casos, con checks deterministas (qué herramienta llamó, si la cifra coincide con el sistema, si retuvo la escritura) y, opcionalmente, un juez con rúbrica. Capa 2, las suites comunes de seguridad (inyección, datos personales, alcance), que deben pasar completas. Capa 3, costo y latencia contra el presupuesto del manifiesto. Si no supera el umbral de su riesgo, vuelve a borrador con el reporte.

## El juez
Lo verificable no necesita juicio: se revisa con código. Para lo que requiere criterio se usa un juez con rúbricas binarias. El juez tiene sesgos de posición, verbosidad y familia, por eso se usa uno de otra familia que el agente y se mide su acuerdo con etiquetas humanas antes de confiar en él.

## Monitoreo en producción
En producción se miden por agente cinco dimensiones: calidad (retroalimentación y escalamientos), seguridad (bloqueos e incidentes de datos, que suspenden el agente automáticamente), costo (por conversación y por área), operación (latencia p95 y errores de herramientas) y adopción (conversaciones). Un agente puede degradarse sin que nadie lo toque porque cambian las preguntas, los documentos o el modelo. Cada falla en producción se convierte en un caso nuevo de la suite. Se consultan con charter metricas.

## Cuando sale un modelo mejor
No se cambia en ningún agente: se cambia detrás de un alias. Antes pasa por cinco etapas: capacidades (herramientas, JSON, contexto, español), suites offline de todos los agentes del alias, sombra con tráfico real sin responder, canario con 5 a 10 por ciento del tráfico, y mover el alias dejando el anterior para reversión en un paso. Al mover el alias, todo agente que lo usa vuelve a la compuerta por re-certificación.
