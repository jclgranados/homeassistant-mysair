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
| Client ID (MQTT) | `aws_mqtt_user` (ej. `web####`) | Confirmado (`mqtt_handler.py:125,161`) |
| Username (MQTT) | `aws_mqtt_user` | Confirmado (`mqtt_handler.py:126`) |
| Password (MQTT) | `aws_security_token` ⚠️ | Confirmado (`mqtt_handler.py:127`) |
| Keepalive (MQTT) | 60 s (en CONNECT) | Confirmado (`mqtt_handler.py:42`) |
| Ping WebSocket | `ping_interval=30`, `ping_timeout=10` | Confirmado (`mqtt_handler.py:144`) |
| Clean session | **Sí** (connect flags `0xC2` = CleanSession+User+Pass) | Confirmado (`mqtt_handler.py:41`) |
| Protocolo MQTT | v3.1.1 (protocol level `0x04`, nombre `MQTT`) | Confirmado (`mqtt_handler.py:39-40`) |
| QoS suscripción | 0 (byte final `0x00` en SUBSCRIBE) | Confirmado (`mqtt_handler.py:60`) |
| Retain | No aplicable (no se publica) | Confirmado |

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
| `pro/v1/get/ctl/{installation_ref}/#` | **Suscripción** | Recibir todo lo publicado bajo el controlador (incluye `.../status`) | `mqtt_handler.py:176` | Confirmado |
| `.../status` (sufijo) | Recepción (publish del broker) | Estado de las zonas del controlador | `__init__.py:75`, `climate.py:178` | Confirmado (sufijo); ruta completa Inferida |
| Otros bajo `pro/v1/get/ctl/{ref}/*` | Recepción | Desconocido (el callback los reenvía crudos) | `__init__.py:127-133` | Desconocido |

- **Wildcard:** `#` (multinivel) al final de la suscripción. **Confirmado**.
- **QoS:** 0 (sin PUBACK). **Confirmado**.
- **Se suscribe con packet_id incremental** `i` (1-based) por instalación (`mqtt_handler.py:174`). **Confirmado**.

> **Desconocido:** la ruta completa del topic de estado. El código deduce el topic del **prefijo del payload** (`(topic){...}`), no de la cabecera MQTT real. Ver §4.

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

**Campos por zona en `t[]` (Confirmado que se leen — semántica Inferida):**

| Campo | Interpretación en el código | Tipo | Certeza |
|---|---|---|---|
| `rf` | id/referencia de zona (`zone_id`) | str | Confirmado se usa; nombre Inferido |
| `n` | nombre de zona | str | Inferido |
| `tr` | temperatura real/actual (`temp_actual`) | float | Inferido |
| `tc` | temperatura consigna (`temp_target`) | float | Inferido |
| `tmm` | temperatura mínima (`temp_min`) | float | Inferido |
| `tmx` | temperatura máxima (`temp_max`) | float | Inferido |
| `e` | modo/estado: `0`=off, `1`=heat, `2`=cool | int | Confirmado el mapeo en código; semántica real Desconocida |
| `m` | (usado solo en `select.py`, código roto) modo `1`=calor | ? | Hipótesis / contradice `e` |

> ⚠️ **Contradicción no resuelta:** `select.py:78` lee `thermostat["m"]` con `1`=Calor, mientras el callback principal usa `e` con `1`=heat, `2`=cool. Y los **comandos** usan `0`=calor,`1`=frío. Tres codificaciones distintas. Ver `docs/known-unknowns.md`.

### 4.3 Ejemplo sanitizado de payload `status`
Mensaje crudo aproximado en el WebSocket (**Inferido**, valores ficticios):
```
(pro/v1/get/ctl/INST_REF/status){"ctl":"INST_REF","value":"{\"t\":[{\"rf\":\"DEV1\",\"n\":\"Salon\",\"tr\":22.5,\"tc\":21.0,\"tmm\":10.0,\"tmx\":30.0,\"e\":1}]};"}
```
JSON anidado ya parseado:
```json
{ "t": [ { "rf":"DEV1", "n":"Salon", "tr":22.5, "tc":21.0, "tmm":10.0, "tmx":30.0, "e":1 } ] }
```
Estructura normalizada que se emite al event bus como `mysair_update.data` (**Confirmado** — `__init__.py:110-113`):
```json
{ "ctl":"INST_REF",
  "zones":[ { "ctl":"INST_REF","zone_id":"DEV1","zone_name":"Salon",
              "temp_actual":22.5,"temp_target":21.0,"temp_min":10.0,"temp_max":30.0,"mode":1 } ] }
```

### 4.4 Mensajes no-status
Cualquier mensaje cuyo topic no termine en `/status` se reenvía **crudo** al event bus (`__init__.py:127-133`). Ninguna entidad los consume (todas filtran por `/status`). **Confirmado** → efectivamente ignorados.

---

## 5. Correlación comando↔respuesta

- **No hay correlación explícita.** Los comandos salen por **HTTP**; el estado llega por MQTT sin identificador que los enlace. **Confirmado**.
- La reconciliación es por **estado completo**: tras un comando, el estado optimista local se sobrescribe cuando llega el siguiente `status` (provocado por el refresco de 60 s o por el propio dispositivo). **Inferido**.
- No hay mensajes de ACK, error ni heartbeat a nivel de aplicación MQTT observados. **Desconocido** si existen.

---

## 6. Reconexión, resuscripción, orden y condiciones de carrera

| Aspecto | Comportamiento | Certeza |
|---|---|---|
| Reconexión | Bucle `_run` con `sleep(10s)` tras `on_close`/`on_error` | Confirmado |
| Resuscripción | Al recibir CONNACK se re-suscribe a **todos** los topics | Confirmado |
| Backoff | Fijo 10 s (sin exponencial) | Confirmado |
| Refresco de credenciales AWS en reconexión | **Solo si** `aws_credentials` es falsy → si ya existen, se reutiliza firma potencialmente caducada | Confirmado ⚠️ |
| Sesión limpia | CleanSession=1 → sin cola offline; los mensajes perdidos durante la desconexión **no se recuperan** (se compensa con el refresco periódico) | Confirmado |
| Deduplicación | Ninguna. Cada `status` reescribe el estado; las entidades comparan valor antes de escribir (`sensor.py:84`) | Confirmado |
| Orden de mensajes | QoS 0, sin garantía de orden; un `status` viejo podría sobrescribir uno nuevo | Inferido ⚠️ |
| Frames parciales/multi-PUBLISH | No se gestionan: se asume 1 frame WS = 1 paquete MQTT completo con 1 JSON | Confirmado ⚠️ |
| PINGREQ/PINGRESP MQTT | No se envían; se confía en el ping del WebSocket | Confirmado |
| Client ID compartido | Igual que el `aws_mqtt_user` que usa la app web → posible expulsión mutua si ambos conectan | Hipótesis ⚠️ |

**Condiciones de carrera potenciales (Inferido):**
1. Estado optimista de una entidad vs `status` en vuelo → parpadeo de estado.
2. Reconexión que reutiliza firma caducada → bucle de reconexión fallida hasta que algo ponga `aws_credentials=None` (nada lo hace salvo un `refresh_aws_credentials` desde un 401 HTTP). Riesgo de **quedar desconectado indefinidamente**.
3. `client_id` compartido con la app oficial → desconexiones mutuas.

---

## 7. Resumen de certezas

- **Confirmado:** transporte WSS+SigV4, CONNECT/SUBSCRIBE manuales, topic de suscripción `pro/v1/get/ctl/{ref}/#`, detección por primer byte, parsing de `status`, mapeo `e`→modo, reconexión con backoff fijo.
- **Inferido:** semántica de campos `tr/tc/tmm/tmx/n/rf`, formato `(topic){json}` del frame, redundancia del password MQTT.
- **Desconocido:** ruta completa de los topics de estado, existencia de otros topics/eventos/heartbeats, formato binario exacto de la cabecera MQTT, si el broker valida el password, semántica real del campo `e`/`m`.
