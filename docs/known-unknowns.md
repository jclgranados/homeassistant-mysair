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

| # | Pregunta | Estado | Respuesta / evidencia |
|---|---|---|---|
| 5 | Ruta **completa** del topic de estado | ✅ Resuelto | `pro/v1/get/ctl/{ref}/status`. Estructura `env/version/method/type/device/property`; base = `aws_base_topic` (=`pro/v1/`). Ver `protocol-findings.md §6b`. |
| 6 | Formato binario exacto del frame PUBLISH | 🟡 Abierto (parcialmente) | La app usa una librería MQTT (no revela nuestro parseo crudo). Sigue frágil (`split`/`{...}`) → decodificar la cabecera MQTT real (longitud de topic, packet id) en vez de heurísticas de texto sigue pendiente (E1). **Bug real encontrado y corregido (2026-07-20)** con una captura de producción: el prefijo del topic no siempre viene entre paréntesis `(topic){json}` — a veces es `topic{json}` sin paréntesis (el topic de `feedback`, por ejemplo), y la heurística anterior solo reconocía la forma con paréntesis, clasificando el resto como `"unknown"`. Esto rompía por completo la confirmación de comandos (#23), ya que la rama `elif topic.endswith("/feedback")` nunca se activaba. Corregido en `mqtt_handler._on_message` extrayendo todo lo anterior al primer `{` y despojando paréntesis/espacios opcionales, sin asumir su presencia. |
| 7 | ¿Otros topics/eventos? | ✅ Resuelto | Bajo `ctl/{ref}/#` solo `status`. Existe topic aparte `pro/v1/get/usr/{aws_mqtt_user}/feedback` (ack con `orderId`) — **ahora consumido** (ver `execution-plan.md` Tarea 16). |
| 8 | Significado de `tmm`/`tmx` | ✅ Resuelto | temp mínima/máxima. |
| 9 | ¿`;` final en `value`? | ✅ Resuelto | La app hace `value.slice(0,-1)` (terminador); se recorta antes de `json.loads`. |
| 10 | ¿El broker exige el `password` MQTT? | 🟢 Abierto | Bajo (SigV4 en la URL). La app usa el SDK AWS IoT (creds en la firma). |
| 11 | ¿Heartbeat de aplicación? | ✅ Resuelto | No; el SDK/WS gestiona keepalive. Nuestro ping WS (30s) es suficiente. |
| 23 | Forma exacta del payload del topic `feedback` (¿plano `{orderId,ctl,...}` o envuelto en `value` como `status`?) | ✅ Resuelto | **Confirmado con captura real de producción (2026-07-20):** plano, tal como sugería el JS — `{"version":1,"orderId":"5b1ae0","type":null,"sender":"CTL","ctl":"MYS...","app":"web0077","command":"","value":"OK","qos":0,"retain":0,"ws":"#CTL#..."}`. `status_parser.parse_feedback_payload` ya probaba esta forma primero; el fallback anidado sigue ahí por si acaso, pero no hace falta. **Bug real encontrado en la misma captura** (no en el parseo del payload, sino en la extracción del topic): ver #6. |
| 24 | Significado de los valores de `vv` (velocidad de ventilador) | ✅ Resuelto | Encontrado en el componente **real** de una instalación (no en la página de demo/storybook de componentes UI, que tenía valores de ejemplo `{"auto":["A"]}`/`{"manual":["1","2","3"]}` que resultaron ser **datos ficticios de la demo**, no del wire real — cuidado al citar ese hallazgo anterior). Definición real: `fanGroups:[{key:"auto",values:{4:"A"}},{key:"manual",values:{1:"1",2:"2",3:"3"}}]` y `hasFanMode(){return "0"!=this.vv}`. Mapeo confirmado: `vv="0"`→sin modo de ventilador, `vv="1"/"2"/"3"`→velocidad manual 1/2/3, `vv="4"`→automático (mostrado como "A"). Desbloquea F2. |
| 25 | Nombre real del campo de humedad en el JSON de zona | ✅ Resuelto | **Bug real encontrado con captura de producción (2026-07-20):** el campo es `hum`, no `hm`. El getter de la app `getHumidity(){return this.hm}` lee una propiedad **interna** del objeto de estado (`this.hm`), no el nombre del campo en el JSON crudo de la zona — la captura real muestra `"hum":"0"` en el payload, sin ninguna clave `hm`. Esto rompía el sensor de humedad (F1) por completo: `status_parser` leía `t.get("hm")`, que siempre daba `None`. Corregido a `t.get("hum", t.get("hm"))` (con `hm` como fallback defensivo). |

---

## 3. HTTP y descubrimiento

| # | Pregunta | Evidencia | Hipótesis | Cómo validar | Riesgo |
|---|---|---|---|---|---|
| 12 | ¿Qué campos tiene un `device` además de `reference`/`name`? | Fallbacks `rf`/`id` (`climate.py:25`) sugieren incertidumbre | Puede incluir tipo, capacidades, estado online | Inspeccionar respuesta `/devices` | 🟡 Medio |
| 13 | ¿El campo correcto es `reference` o `rf`/`id`? | Fallback en cadena | `reference` | Ver respuesta real | 🟡 Medio |
| 14 | ¿Qué hace `validated=1`? | Query fija (`api.py:161`) | Filtra instalaciones validadas | Probar con `validated=0` | 🟢 Bajo |
| 15 | ¿Puede una cuenta tener varias `Location`? El código usa solo la primera. | `__init__.py:39` | Sí; se pierden las demás | ✅ Validado en producción con cuenta real (2026-07-20): el flujo funciona correctamente con una `Location`. **Decisión de alcance:** se mantiene deliberadamente solo la primera `Location`; multi-location queda fuera de alcance salvo que un usuario lo necesite. | 🟢 Bajo (aceptado) |
| 16 | Duración del `access_token` | ✅ Resuelto | El login trae `expires_at` (unix s). La app refresca con timer; nosotros solo ante 401. Oportunidad de refresco proactivo. |
| 17 | ¿`command:"temp"` acepta `value` string? | ✅ Resuelto | String (`setTemp` envía `""+i`). |
| 18 | ¿Endpoint HTTP para leer estado? | 🟢 Abierto | No observado; el estado llega por MQTT. |
| 19 | ¿Rate limiting en `/send/instruction`? | 🟡 Abierto | Desconocido; `VUE_APP_OUTSERVICE_MILISECOND=5000` (timeout de la app, no rate limit). |

---

## 4. Conexión / infraestructura

| # | Pregunta | Evidencia | Hipótesis | Cómo validar | Riesgo |
|---|---|---|---|---|---|
| 20 | ¿`client_id` compartido causa expulsiones? | ✅ Resuelto | Sí lo causaría: la app usa clientId **único** `mqtt-client_{accessKeyId}_{ts}`. Nuestra integración usa `aws_mqtt_user` → **bug**: debe usar un clientId único. |
| 21 | ¿`aws_mqtt_user` cambia por refresco? | ✅ Resuelto | `aws_mqtt_user` es el id de cuenta (estable) y NO se usa como clientId MQTT. Sin relación con #20. |
| 22 | Duración de las credenciales AWS | ✅ Resuelto | Traen `aws_expires_at` (unix s). La app refresca antes de expirar (`getMqttExpirationTime`). Nuestra integración debe leer `aws_expires_at` y refrescar proactivamente. |

---

## 5. Cómo obtener las respuestas de forma segura

- Preferir la **app web oficial** con las herramientas de desarrollador del navegador (Network + WebSocket frames) sobre una cuenta propia de prueba.
- Capturar payloads, **redactar** tokens/credenciales antes de guardarlos, y derivar de ahí fixtures sanitizadas.
- Para MQTT crudo: añadir temporalmente un log a nivel DEBUG que vuelque bytes en hex del frame PUBLISH **en un entorno de laboratorio**, nunca en producción de terceros.
- No enviar comandos de escritura contra una instalación en uso; usar una zona/hora en la que un cambio sea inocuo y reversible.

---

## 6. Resumen

- ✅ **Resueltos desde el bundle oficial** (`docs/protocol-findings.md`): #1-5, #7-9, #11, #16-17, #20-22, #24.
- ✅ **Resueltos con captura real de producción (2026-07-20):** #23 (payload `feedback` plano) y #25 (`hum`, no `hm`); de paso se encontró y corrigió un bug real en la extracción del topic (#6, parcial).
- 🟡 **Abiertos (menores / requieren captura real):** #6 (bytes del frame — robustez del parser, en lo que no se resolvió), #10 (password MQTT), #12/#13 (campos HTTP de `/devices`), #14 (`validated`), #18/#19 (endpoints/rate limiting).
- 🟢 **Aceptados por decisión de alcance:** #15 (multi-location — fuera de alcance, validado en producción con una `Location`).

**Correcciones de código pendientes derivadas (ver roadmap):**
- 🔴 `client_id` MQTT único (#20) · 🔴 refrescar credenciales con `aws_expires_at` (#22)
- 🟡 base del topic desde `aws_base_topic` (#5) · 🟡 refresco proactivo del token (#16)
