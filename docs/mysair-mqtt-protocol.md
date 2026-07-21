# Protocolo MQTT de MySair (sobre WebSocket / AWS IoT)

> Toda la información procede de `mqtt_handler.py` y del callback en `__init__.py`. Certeza marcada explícitamente.
> ⚠️ La integración implementa MQTT **a mano** sobre WebSocket (no usa `paho`). Solo construye paquetes **CONNECT** y **SUBSCRIBE**; nunca **PUBLISH**. La conexión es **solo de recepción**.

---

## 1. Parámetros de conexión

| Parámetro | Valor / origen | Certeza |
|---|---|---|
| Transporte | WebSocket seguro (`wss://`) contra AWS IoT | Confirmado (`api.py:327`) |
| Broker (host) | `aws_credentials["aws_mqtt_host"]` (de `PUT /user/refreshawscredentials`) | Confirmado (`mqtt_handler.py:120`) |
| Puerto | 443 (implícito en `wss://`, sin puerto explícito) | Inferido |
| TLS | Sí (WSS) | Confirmado |
| Ruta WS | `/mqtt` | Confirmado (`api.py:308,327`) |
| Subprotocolo WS | Header `Sec-WebSocket-Protocol: mqtt` | Confirmado (`mqtt_handler.py:134`) |
| Autenticación | **AWS SigV4** en la query string de la URL (`X-Amz-*`) | Confirmado (`api.py:288-329`) |
| Servicio SigV4 | `iotdevicegateway` | Confirmado (`api.py:292`) |
| Client ID (MQTT) | **Único por conexión** `mqtt-client_{accessKey}_{ts}_{rand}` (`build_client_id`) — como la app oficial; ya no `aws_mqtt_user` | ✅ Confirmado / corregido (#20) |
| Username (MQTT) | `aws_mqtt_user` | Confirmado (`mqtt_handler.py`) |
| Password (MQTT) | `aws_security_token` ⚠️ | Confirmado (`mqtt_handler.py:127`) |
| Keepalive (MQTT) | 60 s (en CONNECT) | Confirmado (`mqtt_handler.py:42`) |
| Ping WebSocket | `ping_interval=30`, `ping_timeout=10` | Confirmado (`mqtt_handler.py:144`) |
| Clean session | **Sí** (connect flags `0xC2` = CleanSession+User+Pass) | Confirmado (`mqtt_handler.py:41`) |
| Protocolo MQTT | v3.1.1 (protocol level `0x04`, nombre `MQTT`) | Confirmado (`mqtt_handler.py:39-40`) |
| QoS suscripción | 0 (byte final `0x00` en SUBSCRIBE) | Confirmado (`mqtt_handler.py:60`) |
| Retain | No aplicable (no se publica) | Confirmado |
| Base del topic | `aws_base_topic` (=`pro/v1/`), con fallback histórico (`build_status_topic`) | ✅ Confirmado / corregido (#5) |
| Expiración credenciales | `aws_expires_at` (unix s); refresco proactivo antes de expirar (`aws_credentials_expired`) | ✅ Confirmado / corregido (#22) |

> **Nota (Inferido):** en AWS IoT con SigV4 por WebSocket, la autenticación real va en la firma de la URL; enviar `aws_security_token` como *password* MQTT es probablemente **redundante o ignorado** por el broker. **Desconocido** si el broker lo exige.

### Firma de URL (Confirmado — `api.py:288-329`)
- Algoritmo `AWS4-HMAC-SHA256`, método `GET`, ruta `/mqtt`, `SignedHeaders=host`.
- Usa `datetime.datetime.utcnow()` (**obsoleto** en Python ≥3.12) para `X-Amz-Date`.
- La firma tiene validez temporal → si se reutiliza tras caducar, la conexión será rechazada. Ver §6.

---

## 2. Ciclo de conexión (Confirmado)

```
1. _run(): obtiene aws_credentials (si faltan → refresh_aws_credentials)
2. aws_sign_url() → wss://host/mqtt?X-Amz-...
3. WebSocketApp.run_forever(ping_interval=30, ping_timeout=10)
4. on_open  → envía CONNECT (0x10) binario
5. on_message:
     - 0x20 CONNACK → connected=True → envía SUBSCRIBE por cada instalación
     - 0x90 SUBACK  → log
     - 0x30 PUBLISH → parsea y llama message_callback
6. on_close/on_error → connected=False → sleep(10) → reintenta
```

Detección de tipo de paquete por **primer byte** del frame (`message.startswith(b"\x20"/b"\x90"/b"\x30")`). **Confirmado** (`mqtt_handler.py:171-187`).

---

## 3. Topics

| Patrón del topic | Dirección | Finalidad | Origen | Certeza |
|---|---|---|---|---|
| `{aws_base_topic}get/ctl/{ref}/#` (=`pro/v1/get/ctl/{ref}/#`) | **Suscripción** | Recibir todo lo publicado bajo el controlador (incluye `.../status`) | `build_status_topic` | ✅ Confirmado |
| `pro/v1/get/ctl/{ref}/status` | Recepción (publish del broker) | Estado de las zonas del controlador | callback | ✅ Confirmado |
| `pro/v1/get/usr/{aws_mqtt_user}/feedback` | **Suscripción** | ACK de instrucciones con `orderId` | `build_feedback_topic`, `protocol-findings.md §8` | ✅ Confirmado (topic/mecanismo); 🟡 forma exacta del payload sin capturar en producción (`known-unknowns` #23) |

- **Estructura del topic:** `env/version/method/type/device/property` (p. ej. `pro/v1/get/ctl/{ref}/status`). **Confirmado** (app oficial).
- **Base:** `aws_base_topic` (=`pro/v1/`), con fallback histórico. **Confirmado**.
- **Wildcard:** `#` (multinivel) al final de la suscripción de estado; el topic de feedback no lleva wildcard (topic exacto). **Confirmado**.
- **QoS:** 0 (sin PUBACK). **Confirmado**.
- **Se suscribe con packet_id incremental** `i` (1-based): primero una suscripción por instalación, luego una más para el topic de feedback. **Confirmado**.

> ✅ **Resuelto** (#5): la ruta completa del topic de estado es `pro/v1/get/ctl/{ref}/status`. Nuestro parser deduce el topic del prefijo del payload (`(topic){...}`); el formato binario exacto del frame (#6) sigue pendiente de dump real.

---

## 4. Formato del payload y parsing

### 4.1 Extracción del frame PUBLISH (Confirmado — frágil)
`mqtt_handler._on_message` para paquetes `0x30`:
1. `payload = message.split(b"\x00", 2)[-1]` — separa por bytes nulos y toma el último trozo. ⚠️ **Frágil**: asume una estructura fija de cabecera; un topic con bytes nulos o longitudes distintas rompería el split.
2. Decodifica UTF-8 (ignora errores).
3. Extrae la subcadena entre el primer `{` y el último `}` como JSON.
4. Deduce el `topic` si el texto empieza por `(` : `topic = decoded[1:decoded.find("{")].strip(" )")`. Si no, `topic = "unknown"`.

**Inferido:** el mensaje en el WS tiene forma aproximada `(<topic>){<json>}` o similar, y por eso se parsea así. **Desconocido** el formato binario exacto de la cabecera MQTT (longitud de topic, packet id).

### 4.2 Payload de `status` (Confirmado parcialmente)
El callback (`__init__.py:74-122`) espera un JSON con:
```json
{
  "ctl": "<INSTALLATION_REF>",
  "value": "<STRING con JSON anidado, posible ';' final>"
}
```
- `value` es un **string** que contiene JSON anidado; se limpia un `;` final antes de `json.loads` (`__init__.py:83-87`).
- El JSON anidado contiene `t` = lista de termostatos/zonas.

**Campos por zona en `t[]` (semántica CONFIRMADA desde la app oficial — ver `docs/protocol-findings.md`):**

| Campo | Significado | Valores | Certeza |
|---|---|---|---|
| `rf` | referencia de zona (`zone_id`) | str | Confirmado |
| `n` | nombre de zona | str | Confirmado |
| `e` | **ENCENDIDO** (no es el modo) | `"0"`=off, `"1"`=on, `"2"`=standby | ✅ Confirmado |
| `m` | **MODO** | `0`-`5`: par=calor, impar=frío; {0,1,4,5}=AC, {2,3,4,5}=suelo | ✅ Confirmado |
| `tr` | temperatura real/actual (`temp_actual`) | num | Confirmado |
| `tc` | temperatura consigna (`temp_target`) | num | Confirmado |
| `tmm` / `tmx` | temperatura mín / máx | num | Confirmado |
| `hm` | humedad | num | Confirmado |
| `vv` | modo/velocidad de ventilador actual | str | Confirmado |
| `tzv` | valor de temporizador actual | str | Confirmado |
| `sv` | suelo radiante encendido/apagado | `"0"`/`"1"` | ✅ Confirmado (`setFloor`, re-verificado 2026-07-21) |
| `c` / `f` | capacidad: permite calor / frío | `"1"`/`"0"` | Confirmado |
| `v` / `s` | capacidad: permite ventilador / suelo | `"1"`/`"0"` | Confirmado |
| `tz` / `hp` | capacidad: permite temporizador / programas | `"1"`/`"0"` | Confirmado |
| `pl` | zona principal | flag | Confirmado |

> ✅ **Resuelto** (antes marcado como contradicción): `e` es el estado de encendido, **no** el modo. El modo real es `m` (0-5). La app deriva calor/frío de la **paridad de `m`** y AC/suelo de los conjuntos indicados. Ver tabla de `m` en `docs/protocol-findings.md §4`.

### 4.3 Ejemplo sanitizado de payload `status`
Mensaje crudo aproximado en el WebSocket (**Inferido**, valores ficticios):
```
(pro/v1/get/ctl/INST_REF/status){"ctl":"INST_REF","value":"{\"t\":[{\"rf\":\"DEV1\",\"n\":\"Salon\",\"e\":\"1\",\"m\":\"0\",\"tr\":22.5,\"tc\":21.0,\"tmm\":10.0,\"tmx\":30.0,\"hm\":45}]};"}
```
JSON anidado ya parseado (zona encendida, AC en calor):
```json
{ "t": [ { "rf":"DEV1", "n":"Salon", "e":"1", "m":"0", "tr":22.5, "tc":21.0, "tmm":10.0, "tmx":30.0, "hm":45 } ] }
```
Estructura normalizada que emite `parse_status_payload` al event bus como `mysair_update.data` (**Confirmado** — `status_parser.py`):
```json
{ "ctl":"INST_REF",
  "zones":[ { "ctl":"INST_REF","zone_id":"DEV1","zone_name":"Salon",
              "temp_actual":22.5,"temp_target":21.0,"temp_min":10.0,"temp_max":30.0,"humidity":45.0,
              "power":"1","is_on":true,"is_standby":false,
              "mode_raw":"0","is_heat":true,"is_cool":false,"is_ac":true,"is_floor":false,
              "fan_mode":null,"allow_heat":false,"allow_cool":false,"allow_fan":false,"allow_floor":false } ] }
```

### 4.4 Mensajes no-status
- Topic `.../feedback` (ACK de instrucciones): parseado con `parse_feedback_payload` y reenviado como evento propio `mysair_feedback` (no `mysair_update`). Lo consumen `climate.py`/`switch.py` vía `command_feedback.CommandFeedbackMixin` para loguear confirmación/timeout de comandos (ver §5 y `protocol-findings.md §8`). **Confirmado**.
- Cualquier otro topic (no `/status` ni `/feedback`) se reenvía **crudo** al event bus `mysair_update` (`__init__.py`). Ninguna entidad los consume. **Confirmado** → efectivamente ignorados.

---

## 5. Correlación comando↔respuesta

- **La app oficial correlaciona** mediante el topic `pro/v1/get/usr/{aws_mqtt_user}/feedback`, que devuelve un ACK con `orderId` por instrucción (`_sendInstruction` → `reciveInstruction_{orderId}` → `reciveStatus_{ctl}`). ✅ Confirmado.
- **Nuestra integración ahora también correlaciona** (parcialmente): `api.extract_order_id` lee el `orderId` de la respuesta de `/send/instruction`; `climate.py`/`switch.py` lo guardan y, al llegar el evento `mysair_feedback` con el mismo `orderId`, lo registran como confirmado por log. Si no llega en `FEEDBACK_TIMEOUT_SECONDS` (5 s, igual que `VUE_APP_OUTSERVICE_MILISECOND` de la app), se loguea un aviso. **No se revierte el estado optimista todavía** (pendiente de validar la forma real del payload de `feedback` en producción, `known-unknowns` #23).
- La reconciliación de **estado** (no de comandos) sigue siendo por **estado completo**: tras un comando, el estado optimista local se sobrescribe cuando llega el siguiente `status` (refresco de 120 s o cambio en el dispositivo). **Inferido**.

---

## 6. Reconexión, resuscripción, orden y condiciones de carrera

| Aspecto | Comportamiento | Certeza |
|---|---|---|
| Reconexión | Bucle `_run` con `sleep(10s)` tras `on_close`/`on_error` | Confirmado |
| Resuscripción | Al recibir CONNACK se re-suscribe a **todos** los topics | Confirmado |
| Backoff | Fijo 10 s (sin exponencial) | Confirmado |
| Refresco de credenciales AWS en reconexión | ✅ **Corregido (#22):** en cada intento se llama `aws_credentials_expired()` (usa `aws_expires_at`) y se refresca si faltan o van a expirar | Confirmado |
| Client ID en reconexión | ✅ **Corregido (#20):** se regenera único por conexión (`build_client_id`), evitando expulsiones | Confirmado |
| Sesión limpia | CleanSession=1 → sin cola offline; los mensajes perdidos durante la desconexión **no se recuperan** (se compensa con el refresco periódico) | Confirmado |
| Deduplicación | Ninguna. Cada `status` reescribe el estado; las entidades comparan valor antes de escribir (`sensor.py:84`) | Confirmado |
| Orden de mensajes | QoS 0, sin garantía de orden; un `status` viejo podría sobrescribir uno nuevo | Inferido ⚠️ |
| Frames parciales/multi-PUBLISH | ✅ **Resuelto (E2, 2026-07-21):** `_recv_buffer` acumula bytes entre llamadas y drena en bucle tantos paquetes completos como haya, distinguiendo "incompleto" (esperar más bytes) de "malformado" (varint de longitud nunca válido) | Confirmado |
| PINGREQ/PINGRESP MQTT | No se envían; se confía en el ping del WebSocket | Confirmado |
| Client ID compartido | Igual que el `aws_mqtt_user` que usa la app web → posible expulsión mutua si ambos conectan | Hipótesis ⚠️ |

**Condiciones de carrera / riesgos:**
1. Estado optimista de una entidad vs `status` en vuelo → parpadeo de estado. (Abierto, bajo impacto.)
2. ~~Reconexión que reutiliza firma caducada → desconexión indefinida.~~ ✅ **Mitigado (#22):** `aws_credentials_expired()` refresca según `aws_expires_at`.
3. ~~`client_id` compartido con la app oficial → desconexiones mutuas.~~ ✅ **Mitigado (#20):** `client_id` único por conexión.
4. ~~Frames parciales / bytes del frame (#6)~~ ✅ **Resuelto (E2):** reensamblado por longitud (`_recv_buffer`/`_next_packet_length`), con el heurístico `split`/`{...}` reservado como respaldo cuando la trama no encaja en el framing MQTT estándar.

---

## 7. Resumen de certezas

- **Confirmado:** transporte WSS+SigV4, CONNECT/SUBSCRIBE manuales, topic de suscripción `pro/v1/get/ctl/{ref}/#`, detección por primer byte, parsing de `status`, mapeo `e`→modo, reconexión con backoff fijo.
- **Inferido:** semántica de campos `tr/tc/tmm/tmx/n/rf`, formato `(topic){json}` del frame, redundancia del password MQTT.
- **Desconocido:** ruta completa de los topics de estado, existencia de otros topics/eventos/heartbeats, formato binario exacto de la cabecera MQTT, si el broker valida el password, semántica real del campo `e`/`m`.
