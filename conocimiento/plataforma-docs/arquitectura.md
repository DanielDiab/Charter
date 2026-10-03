---
titulo: Arquitectura de la plataforma de agentes de Bia
dueno: equipo-ia
vigente_desde: 2026-10-01
clasificacion: interna
---

## Resumen de la arquitectura
La plataforma tiene dos planos y una capa transversal. El plano de control decide qué puede existir: registro de agentes, catálogos de modelos, herramientas y colecciones, el constructor con el Arquitecto, la compuerta de evaluación y las políticas. El plano de ejecución decide cómo corre: la API de agentes, el runtime, el gateway de modelos y los servidores de herramientas y conocimiento. La observabilidad registra todo (trazas, costos, incidentes) y devuelve señales al plano de control.

## Los seis principios
P1. El agente es configuración declarativa, no código. P2. Existe un solo camino a producción, y es el más fácil. P3. Los agentes piden capacidades, no modelos. P4. Lo que se recupera (documentos, resultados de herramientas) es dato, nunca instrucción. P5. Nada se publica ni cambia sin evaluación. P6. La solución más simple que funcione.

## El camino pavimentado
Para llegar a producción todo agente pasa por tres puntos de control obligatorios: el registro (qué es, de quién es y qué toca), la compuerta de evaluación (si funciona y es seguro para su riesgo) y el gateway (con qué modelo corre, qué datos ve y cuánto cuesta). Un atajo con una herramienta externa y llaves propias no tiene llaves corporativas, ni herramientas internas, ni datos de clientes.

## Componentes y tecnología
El runtime es LangGraph: convierte cada manifiesto en un grafo. La API y el plano de control usan FastAPI y Pydantic, y la API es compatible con OpenAI, así que cada agente publicado aparece como un modelo. El gateway de modelos es LiteLLM en producción (en el prototipo, un módulo propio con la misma función). Las herramientas se exponen por servidores MCP, uno por sistema. Los datos viven en PostgreSQL con pgvector (en el prototipo, SQLite y un índice local). La observabilidad es Langfuse con OpenTelemetry (en el prototipo, una tabla de trazas).

## El gateway de modelos
El gateway es el único componente con llaves de proveedores. Resuelve el alias que pide el agente al modelo concreto del catálogo, revisa que el modelo sea elegible para la clasificación de datos del agente, aplica el presupuesto por conversación y el tope mensual, intenta con el modelo de respaldo si el principal falla, y registra tokens, costo y latencia de cada llamada atribuidos al agente y al área. Así la pregunta "cuánto cuesta cada agente" es una consulta.

## Seguridad en seis capas
Cada petición atraviesa seis capas que ningún creador puede quitar. Uno, identidad: el cliente sale de la sesión, nunca del texto. Dos, guard de entrada: detecta inyección y preguntas fuera de alcance. Tres, permisos y autonomía: solo las herramientas declaradas y las escrituras requieren confirmación. Cuatro, lo recuperado es dato: los resultados de herramientas y documentos se marcan como no confiables. Cinco, guard de salida por bloques: verifica que cada cifra venga de una herramienta, que no haya datos de otro cliente y que no haya promesas. Seis, trazas y presupuestos: la PII se enmascara antes de guardar y hay topes de costo.

## Clasificación de datos
Hay cuatro niveles. Pública (tarifas publicadas, preguntas frecuentes): cualquier modelo del catálogo. Interna (procedimientos): proveedores con acuerdo empresarial. Confidencial (facturas, consumo, contacto de clientes): solo modelos con retención cero y acuerdo de datos, y trazas con PII enmascarada. Restringida (datos bancarios, credenciales, cédulas): nunca va al modelo; se enmascara o se resuelve dentro de una herramienta. La clasificación se decide antes que el modelo.

## Inventarios
Los inventarios de agentes, modelos y orquestación no son hojas de cálculo: son vistas que se llenan solas desde el registro, los catálogos y las trazas. El de agentes responde cuántos hay y qué tocan; el de modelos, con qué corren; el de orquestación, qué herramientas y colecciones puede usar cada uno. Se consultan con el comando bia inventario.
