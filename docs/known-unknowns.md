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
| 6 | Formato binario exacto del frame PUBLISH | ✅ Resuelto (2026-07-20, E1) | **Bug real encontrado y corregido primero** con una captura de producción: el prefijo del topic no siempre viene entre paréntesis `(topic){json}` — a veces es `topic{json}` sin paréntesis (el topic de `feedback`, por ejemplo), y la heurística anterior solo reconocía la forma con paréntesis, clasificando el resto como `"unknown"`. Esto rompía por completo la confirmación de comandos (#23). Investigando el porqué del `(` se encontró la explicación real: **no era un envoltorio de la app**, sino el byte bajo del campo de longitud de 2 bytes (big-endian) que precede al Topic Name en cualquier PUBLISH MQTT estándar — visible como texto solo cuando coincide con un ASCII imprimible (los dos topics `.../status` capturados miden exactamente 40 caracteres → `chr(40)='('`; el de `feedback` mide 31 → no imprimible, de ahí que no se viera nada). Confirmado por coincidencia exacta entre la longitud real del string del topic y el carácter observado, cruzando **dos capturas reales distintas** con topics de igual longitud. Implementado `mqtt_handler.parse_mqtt_publish`: decodificador conforme al estándar MQTT 3.1.1 (remaining length varint + Topic Name de 2 bytes + Packet Identifier solo si QoS>0, que no es nuestro caso ya que suscribimos con QoS 0). Se usa como método primario; si no es concluyente (estructura inesperada), cae automáticamente a la heurística de texto anterior como red de seguridad — no hay captura de bytes en crudo (hex dump) que confirme el 100% de los casos límite, así que se mantiene el fallback por prudencia. |
| 7 | ¿Otros topics/eventos? | ✅ Resuelto | Bajo `ctl/{ref}/#` solo `status`. Existe topic aparte `pro/v1/get/usr/{aws_mqtt_user}/feedback` (ack con `orderId`) — **ahora consumido** (ver `execution-plan.md` Tarea 16). |
| 8 | Significado de `tmm`/`tmx` | ✅ Resuelto | temp mínima/máxima. |
| 9 | ¿`;` final en `value`? | ✅ Resuelto | La app hace `value.slice(0,-1)` (terminador); se recorta antes de `json.loads`. |
| 10 | ¿El broker exige el `password` MQTT? | 🟢 Abierto | Bajo (SigV4 en la URL). La app usa el SDK AWS IoT (creds en la firma). |
| 11 | ¿Heartbeat de aplicación? | ✅ Resuelto | No; el SDK/WS gestiona keepalive. Nuestro ping WS (30s) es suficiente. |
| 23 | Forma exacta del payload del topic `feedback` (¿plano `{orderId,ctl,...}` o envuelto en `value` como `status`?) | ✅ Resuelto | **Confirmado con captura real de producción (2026-07-20):** plano, tal como sugería el JS — `{"version":1,"orderId":"5b1ae0","type":null,"sender":"CTL","ctl":"MYS...","app":"web0077","command":"","value":"OK","qos":0,"retain":0,"ws":"#CTL#..."}`. `status_parser.parse_feedback_payload` ya probaba esta forma primero; el fallback anidado sigue ahí por si acaso, pero no hace falta. **Bug real encontrado en la misma captura** (no en el parseo del payload, sino en la extracción del topic): ver #6. |
| 24 | Significado de los valores de `vv` (velocidad de ventilador) | ✅ Resuelto | Encontrado en el componente **real** de una instalación (no en la página de demo/storybook de componentes UI, que tenía valores de ejemplo `{"auto":["A"]}`/`{"manual":["1","2","3"]}` que resultaron ser **datos ficticios de la demo**, no del wire real — cuidado al citar ese hallazgo anterior). Definición real: `fanGroups:[{key:"auto",values:{4:"A"}},{key:"manual",values:{1:"1",2:"2",3:"3"}}]` y `hasFanMode(){return "0"!=this.vv}`. Mapeo confirmado: `vv="0"`→sin modo de ventilador, `vv="1"/"2"/"3"`→velocidad manual 1/2/3, `vv="4"`→automático (mostrado como "A"). Desbloquea F2. |
| 25 | Nombre real del campo de humedad en el JSON de zona | ✅ Resuelto | **Bug real encontrado con captura de producción (2026-07-20):** el campo es `hum`, no `hm`. El getter de la app `getHumidity(){return this.hm}` lee una propiedad **interna** del objeto de estado (`this.hm`), no el nombre del campo en el JSON crudo de la zona — la captura real muestra `"hum":"0"` en el payload, sin ninguna clave `hm`. Esto rompía el sensor de humedad (F1) por completo: `status_parser` leía `t.get("hm")`, que siempre daba `None`. Corregido a `t.get("hum", t.get("hm"))` (con `hm` como fallback defensivo). |
| 26 | Significado del campo `sv` en el JSON de zona | ✅ Resuelto (2026-07-21) | **Historial de idas y venidas dentro de este mismo proyecto:** la sesión que escribió `protocol-findings.md` (2026-07-19) documentó `sv`="estado de suelo actual" bajo el nivel de certeza global "Confirmado" del documento, pero sin citar un getter concreto para esa fila. La sesión de la Tarea 22 (2026-07-20), con una captura de producción real, buscó `sv` en el bundle y **no encontró nada**, así que lo marcó como campo sin interpretar — pero `domain-model.md`/`mysair-mqtt-protocol.md` seguían diciendo "Confirmado" sin que nadie lo revisara, dejando tres documentos contradictorios sobre el mismo campo. Al descargar de nuevo `app.09acea34.js` (2026-07-21, mismo hash que el análisis original) y repetir la búsqueda sí aparece: `setFloor(e){this.sv=e?"1":"0"}`, usado por `toggleRadiatingFloor:function(e){this.status.setFloor(e),...}` sobre el objeto de estado en vivo de la zona (el mismo donde residen `e`/`m`/`tc`). Confirmado: `sv`="0"/"1" = suelo radiante encendido/apagado (distinto de la capacidad estática `s`). La búsqueda de la Tarea 22 fue un fallo de búsqueda, no una refutación real — la lección es no fiarse de "no encontrado en el bundle" sin repetir la búsqueda con variantes (`.sv`, `setFloor`, etc.) antes de degradar una certeza ya documentada. | |

---

## 3. HTTP y descubrimiento

| # | Pregunta | Evidencia | Hipótesis | Cómo validar | Riesgo |
|---|---|---|---|---|---|
| 12 | ¿Qué campos tiene un `device` además de `reference`/`name`? | Fallbacks `rf`/`id` (`climate.py:25`) sugieren incertidumbre | Puede incluir tipo, capacidades, estado online | 🟡 Reforzado (2026-07-20, sin cerrar): no hay dump crudo de `/devices`, pero producción real muestra las entidades emparejando correctamente cada actualización MQTT con su dispositivo, lo que implica que la cadena de fallback resuelve bien el campo. El JS (`updateDevice`/`deleteDevice`) usa consistentemente `e.reference`, nunca `rf`/`id` — esos alias parecen defensivos, no observados en el wire. Sigue sin descartarse que existan campos adicionales (tipo, capacidades) no usados hoy. | 🟡 Medio |
| 13 | ¿El campo correcto es `reference` o `rf`/`id`? | Fallback en cadena | `reference` | 🟡 Reforzado (2026-07-20): mismo hallazgo que #12 — el JS de la app usa siempre `reference`, nunca `rf`/`id`, en las operaciones que identifican un device (`updateDevice`, `deleteDevice`). Sin una respuesta HTTP cruda que lo confirme al 100%, se mantiene el fallback en el código por prudencia. | 🟡 Medio |
| 14 | ¿Qué hace `validated=1`? | Query fija (`api.py:161`) | Filtra instalaciones validadas | ✅ Resuelto (2026-07-20): la app llama `updateInstallation({...,validated:1,...})` tras el primer `status` recibido con éxito de una instalación — `validated` marca las instalaciones que ya han confirmado conectividad al menos una vez. El filtro `validated=1` en `get_installations` por tanto excluye instalaciones que nunca han llegado a conectarse (p.ej. recién dadas de alta y aún no emparejadas). | 🟢 Bajo |
| 15 | ¿Puede una cuenta tener varias `Location`? El código usa solo la primera. | `__init__.py:39` | Sí; se pierden las demás | ✅ Validado en producción con cuenta real (2026-07-20): el flujo funciona correctamente con una `Location`. **Decisión de alcance:** se mantiene deliberadamente solo la primera `Location`; multi-location queda fuera de alcance salvo que un usuario lo necesite. | 🟢 Bajo (aceptado) |
| 16 | Duración del `access_token` | ✅ Resuelto | El login trae `expires_at` (unix s). La app refresca con timer; nosotros solo ante 401. Oportunidad de refresco proactivo. |
| 17 | ¿`command:"temp"` acepta `value` string? | ✅ Resuelto | String (`setTemp` envía `""+i`). |
| 18 | ¿Endpoint HTTP para leer estado? | ✅ Resuelto (2026-07-20) | No existe. Confirmado en el bundle: la app usa el mismo patrón que nosotros — enviar `command:"status"` por HTTP (`POST /send/instruction`) y esperar la respuesta real por MQTT (`.../status`). No hay ningún endpoint GET que devuelva el estado directamente. |
| 19 | ¿Rate limiting en `/send/instruction`? | 🟡 Abierto | Desconocido; `VUE_APP_OUTSERVICE_MILISECOND=5000` (timeout de la app, no rate limit). |

---

## 4. Conexión / infraestructura

| # | Pregunta | Evidencia | Hipótesis | Cómo validar | Riesgo |
|---|---|---|---|---|---|
| 20 | ¿`client_id` compartido causa expulsiones? | ✅ Resuelto | Sí lo causaría: la app usa clientId **único** `mqtt-client_{accessKeyId}_{ts}`. Nuestra integración usa `aws_mqtt_user` → **bug**: debe usar un clientId único. |
| 21 | ¿`aws_mqtt_user` cambia por refresco? | ✅ Resuelto | `aws_mqtt_user` es el id de cuenta (estable) y NO se usa como clientId MQTT. Sin relación con #20. |
| 22 | Duración de las credenciales AWS | ✅ Resuelto (completado 2026-07-20) | Traen `aws_expires_at` (unix s). La app refresca antes de expirar (`getMqttExpirationTime`) con un `setTimeout` — **antes** de que la conexión se caiga, no solo al reconectar después. La implementación original (tarea 8) solo cubría la mitad: refrescaba credenciales caducadas *al reconectar*, pero nunca evitaba que AWS IoT cortara la conexión activa cuando el token expiraba mientras seguía conectada. **Confirmado como causa real de desconexiones "sistemáticas"** vistas en producción (patrón regular, no aleatorio): sin refresco proactivo, la conexión vive exactamente hasta que caduca el token de sesión y entonces AWS la cierra unilateralmente (`code=None, msg=None` en los logs), tras lo cual esperábamos 10s fijos para reconectar — ventana en la que se pueden perder ACKs de `feedback` en tránsito (ver #23). Corregido: `mqtt_handler` programa un `threading.Timer` que cierra y reconecta la sesión proactivamente ~60s antes de `aws_expires_at`, y reconecta **sin** los 10s de espera fija cuando el refresco es planificado (créditos ya frescos). |

---

## 5. Cómo obtener las respuestas de forma segura

- Preferir la **app web oficial** con las herramientas de desarrollador del navegador (Network + WebSocket frames) sobre una cuenta propia de prueba.
- Capturar payloads, **redactar** tokens/credenciales antes de guardarlos, y derivar de ahí fixtures sanitizadas.
- Para MQTT crudo: añadir temporalmente un log a nivel DEBUG que vuelque bytes en hex del frame PUBLISH **en un entorno de laboratorio**, nunca en producción de terceros.
- No enviar comandos de escritura contra una instalación en uso; usar una zona/hora en la que un cambio sea inocuo y reversible.

---

## 6. Resumen

- ✅ **Resueltos desde el bundle oficial** (`docs/protocol-findings.md`): #1-5, #7-9, #11, #14, #16-18, #20-22, #24.
- ✅ **Resueltos con captura real de producción (2026-07-20):** #23 (payload `feedback` plano), #25 (`hum`, no `hm`) y #6 (formato del frame PUBLISH, deducido por coincidencia de longitud de topic entre capturas — sin necesitar un hex dump).
- ✅ **Resuelto tras re-verificación del bundle (2026-07-21):** #26 (`sv`=suelo encendido/apagado) — se había marcado erróneamente como no encontrado en la Tarea 22; repetir la búsqueda en el bundle sí localizó el getter (`setFloor`). Ver detalle en la fila #26.
- 🟡 **Abiertos (menores / requieren captura real):** #10 (password MQTT), #19 (rate limiting). #12/#13 (campos HTTP de `/devices`) reforzados con evidencia indirecta (2026-07-20) pero no cerrados del todo: no hay dump crudo de `/devices`, aunque el comportamiento en producción y el JS de la app apuntan consistentemente a `reference`.
- 🟢 **Aceptados por decisión de alcance:** #15 (multi-location — fuera de alcance, validado en producción con una `Location`).
- ⚫ **Investigado sin resultado, certeza reforzada (2026-07-20, re-confirmado 2026-07-21 — `sv` es la excepción, ver #26):** los campos `vf`, `hmh`, `mh`, `ps`, `p` observados en JSON de zona de producción real no aparecen como acceso a propiedad en ninguna parte del bundle JS de la app. Re-verificado el 2026-07-21: la clase de estado en vivo de zona (`class te`) hace `Object.assign(this,t)` en el constructor, copiando **todos** los campos crudos del JSON sobre la instancia sin excepción — así que si estos campos llegan en el payload, existen como `this.vf`/`this.hmh`/etc., pero ningún getter/setter de toda la clase (ni de ningún otro sitio del bundle) los lee por nombre jamás. Esto no resuelve su *significado*, pero sube la certeza de "no hay ningún uso oculto que se nos escapara": la propia app oficial los recibe y los ignora igual que nosotros. Por la regla del proyecto de no inventar campos, siguen sin interpretar hasta encontrar evidencia externa (otra versión del bundle, o inspección de red con DevTools en un flujo que los muestre en uso real).

**Correcciones de código pendientes derivadas (ver roadmap):**
- 🔴 `client_id` MQTT único (#20) · 🔴 refrescar credenciales con `aws_expires_at` (#22)
- 🟡 base del topic desde `aws_base_topic` (#5) · 🟡 refresco proactivo del token (#16)
