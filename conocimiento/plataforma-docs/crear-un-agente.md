---
titulo: Cómo crear un agente sin escribir prompts
dueno: equipo-ia
vigente_desde: 2026-10-01
clasificacion: interna
---

## La idea
A quien crea un agente no se le pide un prompt. Se le pide lo que sí sabe: la tarea, qué está bien y qué está mal, y ejemplos reales. El Arquitecto lo entrevista; la plataforma compila las instrucciones desde plantillas curadas, hereda los controles y convierte los ejemplos en la primera suite de pruebas. El usuario aporta el negocio; la plataforma, la técnica.

## Los ocho pasos
Uno, escoger un arquetipo. Dos, la entrevista: tarea, límites, ejemplos buenos y malos. Tres, la especificación: el Arquitecto la redacta y el usuario confirma. Cuatro, la compilación: plantilla curada más políticas heredadas. Cinco, los casos de prueba: los ejemplos del usuario más casos adversos. Seis, el sandbox: el usuario conversa con datos de prueba. Siete, la compuerta: suite propia y suites comunes con el umbral de su riesgo. Ocho, la publicación, con revisión del dueño de los datos si el riesgo es medio o alto.

## Los cuatro arquetipos
Pregunta sobre documentos: responde citando colecciones; ejemplo, procedimientos internos; riesgo bajo. Asistente con datos: conversa con herramientas de lectura; ejemplo, el asistente de facturación; riesgo medio. Redactor: produce textos que un humano revisa; ejemplo, cobranza; riesgo medio a alto. Extractor o clasificador: convierte texto libre en datos estructurados; ejemplo, resúmenes de llamadas de ventas; riesgo bajo.

## Cómo se escoge el modelo
Primero el dato y después la tarea. Si ve datos restringidos, no va al modelo. Si ve datos de clientes, solo modelos con retención cero y acuerdo de datos. Si la tarea es estrecha y de alto volumen (clasificar, extraer, resumir), tier rapido. Si planifica varios pasos o razona, tier razonamiento. Si es una conversación con herramientas, tier estandar.

## Comandos para crear y publicar
bia arquitecto abre la entrevista. Con el nombre del agente creado (por ejemplo ventas-resumen-de-llamadas): bia chat ventas-resumen-de-llamadas --sandbox prueba el borrador; bia evaluar ventas-resumen-de-llamadas corre la compuerta; bia aprobar ventas-resumen-de-llamadas --rol dueno --quien lider.ventas@bia.app registra una aprobación; bia publicar ventas-resumen-de-llamadas lo publica si pasó la compuerta y tiene las aprobaciones. bia inventario muestra los inventarios de agentes, modelos y orquestación.
