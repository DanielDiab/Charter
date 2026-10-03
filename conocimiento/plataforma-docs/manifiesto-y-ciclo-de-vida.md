---
titulo: Qué es un agente, el manifiesto y su ciclo de vida
dueno: equipo-ia
vigente_desde: 2026-10-01
clasificacion: interna
---

## Qué es un agente
Un agente es un manifiesto: un archivo declarativo y versionado que la plataforma sabe ejecutar. Dice para qué existe, de quién es, qué capacidades pide a los catálogos, qué datos ve, cuánta autonomía tiene, cómo se prueba y cuánto puede gastar. No contiene código ni nombres de modelos. Lo que no está en el manifiesto, el agente no lo puede hacer.

## Partes del manifiesto
metadata: identificador, versión, dueño, área y arquetipo. purpose: para qué existe. model: el alias (rapido, estandar o razonamiento) y un respaldo opcional. instructions: la plantilla curada, el tono, lo que debe hacer siempre (must) y lo que no debe hacer nunca (must_not). tools: las herramientas MCP; las de escritura llevan requires_confirmation. knowledge: las colecciones de conocimiento. data: la clasificación y de dónde sale el cliente (session.cliente_id). autonomy: nivel L1 a L4. quality: la suite, el umbral y las suites heredadas. budget: costo máximo por conversación y tope mensual.

## Niveles de autonomía
L1 operador: el usuario dirige cada paso. L2 colaborador: el agente propone y el usuario confirma cada acción. L3 consultor: el agente lidera y consulta. L4 aprobador: el humano aprueba lo riesgoso. L5 observador: solo supervisa; no está disponible. En las fases 1 y 2 la autonomía máxima es L4.

## Riesgo y umbral
El riesgo lo calcula la plataforma, no el creador. Bajo: agente interno de solo lectura, umbral de la compuerta 85 por ciento, lo aprueba el dueño. Medio: toca datos de clientes, umbral 90 por ciento, lo aprueban el dueño y el equipo de IA. Alto: actúa con autonomía o redacta para clientes, umbral 95 por ciento, aprueban además datos y cumplimiento.

## Ciclo de vida
Un agente nace como borrador en el sandbox. Se envía a evaluación y si pasa la compuerta y tiene las aprobaciones de su riesgo, se publica. Si falla vuelve a borrador con el reporte. Un agente publicado vuelve a evaluación automáticamente cuando cambia algo de lo que depende (el modelo detrás de su alias, una herramienta, una colección, su plantilla o las políticas): eso es la re-certificación. Se suspende por un incidente de datos. Se depreca cuando sale una versión nueva o tras 90 días sin uso. Un manifiesto publicado no se edita: se sube la versión.
