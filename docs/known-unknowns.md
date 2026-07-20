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
| 6 | Formato binario exacto del frame PUBLISH | 🟡 Abierto | La app usa una librería MQTT (no revela nuestro parseo crudo). Estructura de topic conocida. Sigue frágil (`split`/`{...}`) → validar con dump real. 🔴 para robustez. |
| 7 | ¿Otros topics/eventos? | ✅ Resuelto | Bajo `ctl/{ref}/#` solo `status`. Existe topic aparte `pro/v1/get/usr/{aws_mqtt_user}/feedback` (ack con `orderId`) que la app usa y nosotros no. |
| 8 | Significado de `tmm`/`tmx` | ✅ Resuelto | temp mínima/máxima. |
| 9 | ¿`;` final en `value`? | ✅ Resuelto | La app hace `value.slice(0,-1)` (terminador); se recorta antes de `json.loads`. |
| 10 | ¿El broker exige el `password` MQTT? | 🟢 Abierto | Bajo (SigV4 en la URL). La app usa el SDK AWS IoT (creds en la firma). |
| 11 | ¿Heartbeat de aplicación? | ✅ Resuelto | No; el SDK/WS gestiona keepalive. Nuestro ping WS (30s) es suficiente. |

---

## 3. HTTP y descubrimiento

| # | Pregunta | Evidencia | Hipótesis | Cómo validar | Riesgo |
|---|---|---|---|---|---|
| 12 | ¿Qué campos tiene un `device` además de `reference`/`name`? | Fallbacks `rf`/`id` (`climate.py:25`) sugieren incertidumbre | Puede incluir tipo, capacidades, estado online | Inspeccionar respuesta `/devices` | 🟡 Medio |
| 13 | ¿El campo correcto es `reference` o `rf`/`id`? | Fallback en cadena | `reference` | Ver respuesta real | 🟡 Medio |
| 14 | ¿Qué hace `validated=1`? | Query fija (`api.py:161`) | Filtra instalaciones validadas | Probar con `validated=0` | 🟢 Bajo |
| 15 | ¿Puede una cuenta tener varias `Location`? El código usa solo la primera. | `__init__.py:39` | Sí; se pierden las demás | Cuenta con 2 ubicaciones | 🟡 Medio: instalaciones no visibles |
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

- ✅ **Resueltos desde el bundle oficial** (`docs/protocol-findings.md`): #1-5, #7-9, #11, #16-17, #20-22.
- 🟡 **Abiertos (menores / requieren captura real):** #6 (bytes del frame — robustez del parser), #10 (password MQTT), #12/#13 (campos HTTP de `/devices`), #14 (`validated`), #15 (multi-location), #18/#19 (endpoints/rate limiting).

**Correcciones de código pendientes derivadas (ver roadmap):**
- 🔴 `client_id` MQTT único (#20) · 🔴 refrescar credenciales con `aws_expires_at` (#22)
- 🟡 base del topic desde `aws_base_topic` (#5) · 🟡 refresco proactivo del token (#16) · 🟡 soporte multi-location (#15)
