# Decisiones de implementación

Este repositorio es la pieza ejecutable de la propuesta
[*Agentes como configuración gobernada*](propuesta-arquitectura-agentes-v5.pdf). No
es la plataforma completa. Es un corte vertical que atraviesa todas las capas
del documento, del manifiesto a la API, para comprobar con un modelo real que
las decisiones de la arquitectura se sostienen.

Todo corre en local con Ollama, sin llaves de API. El paso a modelos cerrados
con retención cero, que es la propuesta para producción, está descrito como
referencia en `catalogos/modelos.yaml`. Ese cambio se hace en el catálogo, no
en el código.

El documento está organizado así:

1. **Del documento al código:** dónde vive cada pieza de la arquitectura.
2. **Prototipo y producción:** qué se simplificó y por qué.
3. **Cómo tomé las decisiones:** el método de trabajo, con ejemplos de cómo usé Claude Code.
4. **Las decisiones:** cada una con el dato que la respaldó.
5. **Resultados de la compuerta.**
6. **Próximos pasos.**

---

## 1. Del documento al código

| Documento | Dónde vive | Qué hace |
|---|---|---|
| P1 · El agente es un manifiesto | `manifiestos/*.yaml`, `plataforma/manifiesto.py` | Esquema Pydantic más reglas contra los catálogos. El riesgo lo calcula la plataforma, no el creador. |
| Inventario de agentes | `plataforma/registro.py`, `plataforma/inventario.py` | Registro con ciclo de vida (borrador → evaluación → publicado → suspendido o deprecado) y aprobaciones según el riesgo. |
| Inventario de modelos · P3 | `catalogos/modelos.yaml` | Tres alias: `rapido`, `estandar` y `razonamiento`. Ningún manifiesto nombra un modelo. |
| Inventario de orquestación | `catalogos/herramientas.yaml`, `colecciones.yaml`, `arquetipos.yaml` | Herramientas de lectura, deterministas y de escritura; colecciones con dueño; un patrón por arquetipo. |
| Gateway, único con llaves | `plataforma/gateway.py` | Resuelve el alias, aplica la política de datos y el presupuesto, usa el modelo de respaldo y atribuye el costo. Ningún otro módulo importa el cliente del modelo. |
| Runtime LangGraph | `plataforma/runtime.py` | Un solo grafo para todos los agentes: guard de entrada → recuperación → agente ↔ herramientas → guard de salida. |
| Seis capas de seguridad (fig. 7) | `plataforma/guards.py`, `runtime.py` | Identidad desde la sesión, escrituras con confirmación, lo recuperado tratado como dato y salida revisada por bloques. |
| Herramientas MCP | `mcp_servers/` | Un servidor por sistema (facturación, medición, tarifas, soporte, conocimiento, plataforma), sobre datos sintéticos. |
| RAG con vigencia (fig. 11 y 12) | `plataforma/conocimiento.py`, `conocimiento/` | Filtra por vigencia y permisos antes de buscar; búsqueda híbrida BM25 + vectores con fusión RRF; top 5 con cita. |
| Constructor y Arquitecto (sec. 4) | `plataforma/arquitecto.py`, `constructor.py` | Las preguntas sobre la plataforma las atiende un agente con RAG; la creación de agentes es un flujo guiado de cinco preguntas. |
| Compuerta (sec. 5) | `plataforma/evaluacion.py`, `evals/` | Suite propia con umbral según el riesgo, suites comunes de seguridad al 100 %, y costo y latencia contra el presupuesto. |
| Re-certificación y caducidad | `registro.verificar_recertificacion` | Si cambia algo de lo que depende un agente publicado, vuelve a evaluación de forma automática. |
| Observabilidad | `plataforma/trazas.py`, `monitoreo.py` | Spans con agente, versión, modelo, tokens, costo y latencia; la PII se enmascara antes de guardar. |
| API compatible con OpenAI | `plataforma/api.py` | Cada agente publicado aparece como un "modelo"; el token define la sesión; streaming por bloques validados. |
| Caso aplicado (sec. 6) | `manifiestos/sac-asistente-facturacion.yaml` | El manifiesto del apéndice A, ejecutable. |

El registro trae tres agentes, distintos a propósito para ejercitar la
plataforma:

- **Asistente de facturación:** asistente con datos, riesgo medio. Es el caso de la sección 6.
- **Procedimientos internos:** pregunta sobre documentos, riesgo bajo.
- **El Arquitecto:** también es un manifiesto. Corre por el mismo runtime, los mismos guards y el mismo gateway, y tiene su propia compuerta.

## 2. Prototipo y producción

| En la propuesta | En este repositorio | Motivo |
|---|---|---|
| LiteLLM | `gateway.py` | La misma responsabilidad (alias, costo, tope, respaldo) sin un proxy adicional que levantar. |
| Modelos cerrados con retención cero | Ollama local: qwen2.5 3B y 7B, qwen3 8B | El prototipo corre 100 % local, sin llaves de API. El costo reportado es un **costo de referencia**: el precio de un modelo comercial de tamaño equivalente, para que el presupuesto se pueda demostrar. |
| PostgreSQL + pgvector | SQLite y un índice JSON en `.estado/` | Sin instalación; se regenera con `charter iniciar`. |
| Langfuse + OpenTelemetry | Tabla `spans` | Tiene los mismos campos que un span GenAI. Cambiar el destino es tocar una sola función. |
| SSO corporativo | `datos/sesiones.json` | Simula lo esencial: el cliente y el dueño salen de la sesión, nunca del texto. |
| Consola web | CLI `charter` | El mismo recorrido, sin un frontend que mantener. |
| Servidores MCP por HTTP | MCP por stdio | Es el mismo protocolo con otro transporte. |
| Juez de otra familia | Juez opcional con `qwen3:8b` | Localmente solo hay modelos Qwen disponibles. |

## 3. Cómo tomé las decisiones

Trabajé con un ciclo corto y repetible, apoyado en Claude Code:

1. **Construir la pieza** siguiendo el documento.
2. **Medirla con el modelo real**, con la compuerta o con una conversación de punta a punta.
3. **Leer la traza** del caso que no salió como se esperaba.
4. **Decidir dónde va la solución.** La pregunta siempre fue la misma: ¿esto lo debe resolver el modelo, una herramienta o la plataforma?
5. **Dejar una prueba** que fije el comportamiento.

La regla que guió el paso 4 viene de la propia propuesta: **lo que se puede
decidir con código o con datos de la sesión no se le pregunta al modelo.** El
modelo se reserva para entender lenguaje natural.

### Ejemplos de prompts que usé con Claude Code

Estos son ejemplos representativos de cómo lo dirigí en cada etapa del ciclo.

**Para arrancar desde el documento:**

> compuerta y el Arquitecto. Reutiliza la base de agentes que ya tenemos y deja corriendo los tests

**Para medir:**

> Corre la compuerta del asistente de facturación con Ollama y muéstrame
los casos que no pasan, con la respuesta y las herramientas que llamó.

**Para diagnosticar desde la traza:**

> Abre las trazas de esa conversación y dime qué cifra marcó el guard de salida y de qué herramienta debería haber salido.

**Para separar lo que es del modelo y lo que es nuestro:**

> Reproduce esa llamada directamente contra Ollama, sin el runtime, para saber si el comportamiento viene del modelo o de cómo armamos los mensajes.

**Para decidir el tier con datos:**

> Evalúa la misma versión del agente con el alias rapido y con estandar y
compárame suite propia, seguridad, costo y latencia.

**Para validar el PLUS de punta a punta:**

> Simula una entrevista completa con el Arquitecto como lo haría alguien de ventas que no sabe escribir prompts, y verifica que el borrador quede
registrado, con su dueño y su suite.

## 4. Las decisiones

### 4.1 Las cifras las calcula una herramienta y el guard las verifica

Para explicar por qué subió una factura, el agente necesita porcentajes: qué
parte del aumento viene del consumo y qué parte de la tarifa. La herramienta
`calcular_desglose` entrega esos porcentajes ya calculados (77,6 % y 22,4%
en el caso de prueba), junto con un `resumen` en español con las cifras en
formato colombiano. El guard de salida verifica que toda cifra de la respuesta
aparezca en un resultado de herramienta de esa misma conversación.

La regla de comparación distingue dos casos:

- **Cifras visiblemente redondeadas** ("5,37 millones") aceptan una tolerancia de 0,5 %.
- **Montos escritos completos** ("4.833.195") tienen que coincidir exactamente.

Así se aceptan redondeos honestos y se detecta cualquier cifra que no venga
del sistema.

**Principio:** si el modelo necesita un número, la herramienta debe dárselo.
Junto con los ajustes de 4.4 y 4.6, la suite del asistente de facturación
pasó de 80 % a 100 %.

### 4.2 El alcance se decide en dos pasos, del más barato al más caro

El guard de entrada decide si un mensaje está dentro del propósito del agente
con dos pasos:

1. **Paso léxico, sin costo.** Si el mensaje comparte vocabulario con el
   terreno del agente (su propósito, sus herramientas y el texto de sus
   colecciones), pasa sin gastar una llamada al modelo.
2. **Clasificador LLM.** Solo los mensajes que no comparten nada van al
   clasificador del tier `rapido`.

Lo medí sobre 18 mensajes. El clasificador solo acertó 13, tanto con el modelo
de 3B como con el de 7B. Con los dos pasos acertó 17. El diseño prefiere dejar
pasar un mensaje dudoso antes que bloquear a un cliente: el agente sigue
acotado por sus herramientas y por la política heredada "fuera de mi
propósito".

### 4.3 El tier lo propone el árbol y lo confirma la compuerta

El agente de procedimientos empezó con `rapido` (3B), como indica la figura 9
para una tarea estrecha. La compuerta guió dos decisiones:

| Versión | Configuración | Suite propia | Seguridad | Costo por conversación |
|---|---|---|---|---|
| 1.0.0 | `rapido`, el modelo decide si busca | 71 % | 4/4 | — |
| 1.0.0 | `rapido`, el runtime busca siempre | 100 % | 3/4 | US$0,00015 |
| 1.1.0 | `estandar`, el runtime busca siempre | 100 % | 4/4 | US$0,00055 |

- **La búsqueda la hace el runtime.** En un agente que solo responde desde
  documentos, buscar no es opcional. Los arquetipos *pregunta sobre
  documentos* y *asistente de plataforma* declaran `recuperar_siempre`, y el
  runtime busca antes de llamar al modelo. Es la regla del documento: donde
  importa, el flujo lo decide el código.
- **La documentación declara qué no sabe.** Buscar siempre tiene un efecto
  secundario: si lo recuperado *parece* una respuesta, el modelo deja de
  llamar a la herramienta con el dato vivo. Al Arquitecto le pasaba con
  "¿qué modelos hay disponibles hoy en el catálogo?": recuperaba la sección de
  clasificación de datos ("cualquier modelo del catálogo") y respondía con
  eso sin llamar a `consultar_catalogo`, en todas las corridas. La corrección fue
  en el conocimiento, no en el prompt: la sección de inventarios de
  `plataforma-docs/arquitectura.md` dice que la lista vigente no está en la
  documentación y qué herramienta la entrega. Pasó a 5 de 5 y la suite del
  Arquitecto volvió a 10/10 en dos corridas completas.
- **Se publica la 1.1.0.** Este agente lee contenido que la empresa no controla (por
  ejemplo, un foro de clientes), y el modelo de 7B resistió por sí solo la
  inyección indirecta de la suite común. Se paga 3,6 veces más por tener dos
  líneas de defensa en vez de una. Si entra al catálogo un modelo pequeño que
  pase la suite común de forma estable, volver a `rapido` es cambiar una línea
  y pasar la compuerta.

### 4.4 El runtime absorbe las particularidades de los modelos locales

Estas correcciones viven en el runtime, no en el prompt de cada agente. Las
hereda cualquier agente nuevo.

| Comportamiento del modelo | Corrección de la plataforma |
|---|---|
| Tool call con formato que Ollama no reconoce y descarta | Se recupera desde el texto, o se reintenta una vez con una indicación. |
| Anuncia una acción sin ejecutarla ("vamos a consultar…") | Un detector de narración pide la llamada real. |
| Afirma una escritura que no ocurrió | El guard `afirmacion_sin_accion` impide decir "quedó guardado" si ninguna escritura se ejecutó. |
| Resuelve "este mes" con un periodo equivocado | La fecha de hoy va en las instrucciones compiladas, con la regla de no enviar `periodo` si el usuario no lo menciona. |
| Envía un argumento con una forma distinta a la del esquema | Las descripciones llevan un ejemplo concreto ("2026-07") y los errores piden corregir y reintentar. |
| Repite la misma herramienta en bucle | Tope de dos llamadas por herramienta en cada turno. |

Un detalle técnico que vale la pena registrar: con `ChatOllama`, una
corrección enviada como mensaje de sistema al final de la llamada no cambia la
respuesta del modelo. La misma corrección como mensaje de usuario con el
prefijo `[Plataforma]` sí la cambia (3 de 3 en la prueba aislada). Todas las
correcciones del runtime usan ese formato (`runtime._indicacion`).

### 4.5 La creación de agentes es un flujo guiado

Crear un agente es un proceso de pasos fijos (figura 18). Por eso el
Arquitecto aplica el patrón de flujo determinista de la figura 14: el código
decide el orden y el modelo ocupa pasos acotados.

- **Un enrutador en código** separa los dos modos. Las preguntas sobre la
  plataforma van al agente del manifiesto, con RAG, catálogo e inventario. La
  intención de crear un agente va al flujo.
- **El flujo hace cinco preguntas:** tarea, datos, reglas, ejemplos y área.
  En cada paso, el modelo solo **extrae** un JSON de la respuesta del usuario.
- **El código decide todo lo demás:** valida el arquetipo contra el catálogo,
  aplica el árbol de tiers, fija el tipo de tarea según el arquetipo, calcula
  riesgo, umbral y aprobaciones, y pide confirmación antes de guardar.
- **Lo que aporta el usuario viene del usuario.** El dueño sale de la sesión.
  Los ejemplos que no aparecen en lo que el usuario escribió se descartan,
  porque esos ejemplos se convierten en la suite de pruebas del agente.
- **Se puede preguntar en medio de la entrevista** ("¿qué significa el tier
  rápido?"). El agente responde y el flujo retoma la pregunta pendiente.
- **El traspaso entre modos es un objeto tipado** (`Entrevista`), nunca el
  historial de la conversación.

Comparé este diseño con un Arquitecto que conducía la entrevista como agente
libre con herramientas. El flujo guiado terminó la entrevista completa con el
borrador registrado, el dueño correcto y su suite, con turnos de 1 a 9
segundos. El agente libre necesitaba muchas más llamadas y no completaba el
registro de forma consistente. El agente creado en la demo ("resumen de
llamadas de ventas") pasó su compuerta en el primer intento.

**Principio:** el modelo entiende lo que la persona quiso decir; el código
decide qué se hace con eso.


### 4.6 Las escrituras siempre pasan por una persona

`soporte/crear_caso` es la única escritura del asistente de facturación. El
runtime la retiene, muestra los datos que se van a enviar y solo la ejecuta
cuando el usuario responde que sí. Esta regla la impone el catálogo de
herramientas, no el manifiesto, así que ningún creador puede publicar una
escritura sin confirmación. La respuesta incluye el número del caso, que la
herramienta entrega en su `resumen`.

### 4.7 La compuerta gobierna los cambios, no solo las publicaciones

- **Re-certificación automática.** Cada agente publicado guarda la huella de
  todo lo que lo afecta: el modelo de su alias, sus herramientas, sus
  colecciones, su plantilla y las políticas heredadas. Si algo cambia, vuelve
  a evaluación en el siguiente arranque del CLI o de la API. Se comprobó en
  vivo al ajustar la plantilla `asistente-con-datos@4`.
- **Historial completo.** El registro conserva cada evento del ciclo de vida,
  también las compuertas que no pasaron. Esa historia sirve como evidencia de
  auditoría.
- **Advertencia de suite corta.** La compuerta advierte cuando una suite
  propia tiene menos de 15 casos, que es la recomendación del documento.
- **Presupuesto que no rompe la conversación.** Si una conversación agota su
  presupuesto, termina con un mensaje claro al usuario, nunca con un error. Los
  topes se calibraron con mediciones: una entrevista completa con el
  Arquitecto cuesta alrededor de US$0,05 de referencia, y su tope es de 0,15.

## 5. Resultados de la compuerta

Corrida completa desde un estado limpio (`rm -rf .estado` y `charter iniciar`), 3
de octubre de 2026:

| Agente | Modelo | Riesgo (umbral) | Suite propia | Seguridad | Costo por conversación | p95 |
|---|---|---|---|---|---|---|
| sac-asistente-facturacion 1.3.0 | qwen2.5:7b | medio (90 %) | 15/15 | red-team 4/4 · PII 3/3 | US$0,0010 | 8,1 s |
| sac-procedimientos-internos 1.1.0 | qwen2.5:7b | bajo (85 %) | 7/7 | red-team 4/4 | US$0,0009 | 13,5 s |
| plataforma-arquitecto 1.0.0 | qwen2.5:7b | bajo (85 %) | 10/10 | red-team 4/4 | US$0,0008 | 14,8 s |
| ventas-resumen-de-llamadas 0.1.0 (creado con el Arquitecto) | qwen2.5:3b | bajo (85 %) | 2/2 | red-team 4/4 | US$0,00003 | 1,4 s |

Además corren 85 pruebas automáticas sin Ollama. Usan un modelo guionado
contra los catálogos, el registro, los servidores MCP y los guards reales.

## 6. Próximos pasos

Esto es lo que sigue al prototipo, en línea con la hoja de ruta del documento:

- **Juez de otra familia,** calibrado contra etiquetas humanas, para las rúbricas de la compuerta.
- **Ampliar las suites** a 15–30 casos por agente con conversaciones reales. Cada falla en producción se convierte en un caso nuevo.
- **Canario y modo sombra** para el cambio de modelo detrás de un alias (figura 10, fase 2).
- **Re-certificación por versión de la plataforma:** el pipeline de despliegue corre las compuertas de todos los agentes publicados cuando cambia el runtime o los guards.
- **Verificación de unidades en el guard de cifras,** para comparar valor y unidad (pesos, kWh, %), y no solo el valor.
- **Edición de respuestas en el flujo del Arquitecto,** para corregir un paso anterior sin reiniciar la entrevista.
- **Migración a la infraestructura de producción:** LiteLLM, PostgreSQL con pgvector, Langfuse y SSO. Las interfaces del prototipo ya están separadas para que cada pieza se reemplace sin tocar las demás.
