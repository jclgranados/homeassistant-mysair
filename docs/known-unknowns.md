# Known unknowns — preguntas abiertas

> Cada fila: pregunta · contexto · evidencia disponible · hipótesis · cómo validar · riesgo de asumir mal.
> **Regla:** no modificar el protocolo hasta responder las filas marcadas 🔴 en "Riesgo".

---

## 1. Codificación de modo — ✅ RESUELTO (fuente: app oficial `app.09acea34.js`)

Análisis del bundle de la app web MySair (clases de modelo `te`/`ie` y mixin de instrucciones).
Ver `docs/protocol-findings.md` para el detalle con las citas del JS.

| # | Pregunta | Respuesta CONFIRMADA |
|---|---|---|
| 1 | Codificación del **comando** `mode` | `value = {mode:"0".."5", temperature:"<tc>"}`. `m` base: 0=AC, 2=Suelo, 4=AC+Suelo; **+1 si frío**. Par=calor, impar=frío. Para solo-aire: **0=calor, 1=frío** → nuestro comando ya es correcto. |
| 2 | ¿Qué significa `e` en el **status**? | `e` NO es el modo: es el **encendido**. `"0"`=off, `"1"`=on, `"2"`=standby (`isOn()=="0"!=e`, `isStanby()=="2"==e`). |
| 3 | ¿Por qué `select.py` usaba `m`? | Tenía razón en el campo: el modo real es `m` (0-5), no `e`. El resto de `select.py` estaba roto (ya eliminado). |
| 4 | ¿Asimetría comando(0/1) ↔ status? | No hay asimetría real: el comando manda `m` y el status devuelve `m`. La confusión venía de que nuestro parser leía `e` (encendido) como si fuera el modo. |

**Corrección pendiente en el código (A5):** el parser de estado debe leer **on/off de `e`** y **calor/frío de la paridad de `m`**, no interpretar `e` como modo. `switch.turn_on` no debe encender con `mode:"1"` (fuerza frío).

---

## 2. Payload MQTT

| # | Pregunta | Evidencia | Hipótesis | Cómo validar | Riesgo |
|---|---|---|---|---|---|
| 5 | ¿Cuál es la ruta **completa** del topic de estado? | Solo se conoce sufijo `/status` (`__init__.py:75`) y suscripción `pro/v1/get/ctl/{ref}/#` | `pro/v1/get/ctl/{ref}/status` | Loguear el topic real de la cabecera MQTT | 🟡 Medio |
| 6 | ¿Formato binario exacto del frame PUBLISH? | Parsing por `split(b"\x00",2)[-1]` y `{...}` (`mqtt_handler.py:189-206`) | Cabecera MQTT estándar + payload `(topic){json}` | Volcar bytes crudos de un frame | 🔴 Alto: el parser es frágil |
| 7 | ¿Existen otros topics/eventos además de `status`? | Callback reenvía "otros" crudos, nadie los consume (`__init__.py:127`) | Podría haber eventos de conexión/error | Suscribir y loguear todo bajo `#` | 🟡 Medio |
| 8 | ¿Significado de `tmm`/`tmx`? | Parseados como min/max, no usados (`__init__.py:105-106`) | temp mínima/máxima permitidas | Comparar con límites de la app oficial | 🟢 Bajo |
| 9 | ¿Por qué el `value` de status lleva `;` final? | Se limpia antes de `json.loads` (`__init__.py:84-85`) | Terminador del firmware | — | 🟢 Bajo |
| 10 | ¿El broker exige el `password` MQTT (=security_token)? | `mqtt_handler.py:127` | Redundante con SigV4 | Probar CONNECT sin password | 🟢 Bajo |
| 11 | ¿Hay heartbeat/keepalive a nivel de aplicación? | No observado; solo ping WS | No | Observar tráfico prolongado | 🟡 Medio (afecta detección de caídas) |

---

## 3. HTTP y descubrimiento

| # | Pregunta | Evidencia | Hipótesis | Cómo validar | Riesgo |
|---|---|---|---|---|---|
| 12 | ¿Qué campos tiene un `device` además de `reference`/`name`? | Fallbacks `rf`/`id` (`climate.py:25`) sugieren incertidumbre | Puede incluir tipo, capacidades, estado online | Inspeccionar respuesta `/devices` | 🟡 Medio |
| 13 | ¿El campo correcto es `reference` o `rf`/`id`? | Fallback en cadena | `reference` | Ver respuesta real | 🟡 Medio |
| 14 | ¿Qué hace `validated=1`? | Query fija (`api.py:161`) | Filtra instalaciones validadas | Probar con `validated=0` | 🟢 Bajo |
| 15 | ¿Puede una cuenta tener varias `Location`? El código usa solo la primera. | `__init__.py:39` | Sí; se pierden las demás | Cuenta con 2 ubicaciones | 🟡 Medio: instalaciones no visibles |
| 16 | ¿Cuánto dura el `access_token`? ¿Y el `refresh_token`? | Solo se refresca ante 401 | Access corto, refresh largo | Medir caducidad | 🟡 Medio (estrategia de reauth) |
| 17 | ¿`command:"temp"` acepta `value` string o requiere dict? | `api.py:261` envía string; `mode` envía dict | String válido para temp | Probar contra dispositivo | 🟡 Medio |
| 18 | ¿Existe endpoint HTTP para leer estado (sin MQTT)? | No en el código | No | Explorar API | 🟢 Bajo |
| 19 | ¿Hay rate limiting en `/send/instruction`? | Refresco 60 s por instalación | Desconocido | Observar respuestas 429 | 🟡 Medio |

---

## 4. Conexión / infraestructura

| # | Pregunta | Evidencia | Hipótesis | Cómo validar | Riesgo |
|---|---|---|---|---|---|
| 20 | ¿Compartir `client_id` (=aws_mqtt_user) con la app oficial causa expulsiones? | `mqtt_handler.py:125` | Sí, AWS IoT expulsa client_id duplicados | Conectar app + integración a la vez | 🔴 Alto: desconexiones intermitentes |
| 21 | ¿Cada `refreshawscredentials` da un `aws_mqtt_user` distinto? | — | Estable por cuenta | Comparar dos llamadas | 🟡 Medio (relacionado con #20) |
| 22 | ¿Cuánto duran las credenciales AWS temporales? | Reutilizadas hasta fallar (`mqtt_handler.py:110`) | ~1 h (típico STS) | Medir hasta rechazo de firma | 🔴 Alto: reconexión con firma caducada = desconexión indefinida |

---

## 5. Cómo obtener las respuestas de forma segura

- Preferir la **app web oficial** con las herramientas de desarrollador del navegador (Network + WebSocket frames) sobre una cuenta propia de prueba.
- Capturar payloads, **redactar** tokens/credenciales antes de guardarlos, y derivar de ahí fixtures sanitizadas.
- Para MQTT crudo: añadir temporalmente un log a nivel DEBUG que vuelque bytes en hex del frame PUBLISH **en un entorno de laboratorio**, nunca en producción de terceros.
- No enviar comandos de escritura contra una instalación en uso; usar una zona/hora en la que un cambio sea inocuo y reversible.

---

## 6. Resumen: bloqueantes antes de tocar el protocolo

Responder **obligatoriamente** #1, #2, #4 (codificación de modo), #6 (formato de frame), #20 y #22 (estabilidad de conexión) antes de modificar el envío de comandos o el parsing MQTT. El resto puede documentarse como asunción con `# TODO(validar)` en el código.
