# API HTTP de MySair

> Base URL: `https://api.mysair.es/v1` — **Confirmado** (`api.py:18`).
> Toda la información procede de **ingeniería inversa del código de esta integración**, no de documentación oficial. Certeza: **Confirmado** = la petición existe en el código; los campos de respuesta marcados **Inferido/Desconocido** solo se conocen por lo que el código consume.
> ⚠️ No se incluyen valores reales de tokens, cookies ni credenciales. Los ejemplos están **sanitizados**.

---

## Resumen de endpoints

| Grupo | Método | Ruta | Función que lo usa | Certeza |
|---|---|---|---|---|
| Auth | POST | `/user/login` | `MySairAPI.login` | Confirmado |
| Auth | PUT | `/user/refreshtokens` | `MySairAPI.refresh_tokens` | Confirmado |
| Auth | PUT | `/user/refreshawscredentials` | `MySairAPI.refresh_aws_credentials` | Confirmado |
| Descubrimiento | GET | `/locations` | `MySairAPI.get_locations` | Confirmado |
| Descubrimiento | GET | `/installations?location_id=&validated=1` | `MySairAPI.get_installations` | Confirmado |
| Descubrimiento | GET | `/devices?installation_ref=` | `MySairAPI.get_devices` | Confirmado |
| Comandos | POST | `/send/instruction` | `MySairAPI.send_instruction` | Confirmado |

**Autenticación general (Confirmado):** todos los endpoints salvo `/user/login` y `/user/refreshtokens` usan header `Authorization: Bearer <access_token>`.
**Timeouts (Confirmado):** login 15 s, refreshtokens 10 s, refreshawscredentials 15 s, locations/installations/devices 10 s, send/instruction 10 s.
**Reintentos (Confirmado):** solo `send_instruction` reintenta **una vez** ante `401` tras refrescar tokens (`api.py:205-213`). El resto no reintenta.
**Formato de respuesta común (Inferido):** las respuestas encapsulan datos en una clave `entity` (objeto o lista) y, en instrucciones, `msg`/`error`.

---

## 1. Autenticación

### 1.1 `POST /user/login` — **Confirmado**
- **Finalidad:** obtener `access_token` y `refresh_token`.
- **Auth:** ninguna.
- **Headers:** `Content-Type: application/json` (implícito por `json=`).
- **Body:**
  ```json
  { "email": "<EMAIL>", "password": "<PASSWORD>" }
  ```
- **Respuesta esperada (200):**
  ```json
  { "entity": { "access_token": "<REDACTED_JWT>", "refresh_token": "<REDACTED>" } }
  ```
- **Campos consumidos:** `entity.access_token`, `entity.refresh_token` (`api.py:42-44`). El resto de `entity` se guarda en `self.entity` pero **no se usa**.
- **Errores:** cualquier `status_code != 200` → `Exception("Login error: <code> <text>")` (`api.py:38-39`). Sin distinción 401 vs 500.
- **Usado por:** `config_flow.async_step_user` y `async_setup_entry`.
- **Certeza campos:** estructura `entity` **Inferida**; presencia de tokens **Confirmada** (se validan).

### 1.2 `PUT /user/refreshtokens` — **Confirmado**
- **Finalidad:** renovar tokens con el `refresh_token`.
- **Auth:** ninguna (el refresh_token va en el body).
- **Body:** `{ "refresh_token": "<REDACTED>" }`
- **Respuesta (200):** `{ "entity": { "access_token": "...", "refresh_token": "..." } }`
- **Campos consumidos:** `entity.access_token`, `entity.refresh_token` (`api.py:78-79`).
- **Errores:** `!=200` → excepción; el método **devuelve `False`** en vez de propagar (`api.py:87-89`).
- **Usado por:** `send_instruction` en el reintento 401.

### 1.3 `PUT /user/refreshawscredentials` — **Confirmado**
- **Finalidad:** obtener credenciales temporales de **AWS IoT** para la conexión MQTT.
- **Auth:** `Authorization: Bearer <access_token>`.
- **Body:** ninguno.
- **Respuesta (200):**
  ```json
  {
    "entity": {
      "aws_mqtt_host": "<REDACTED>.iot.<region>.amazonaws.com",
      "aws_default_region": "<REGION>",
      "aws_access_key_id": "<REDACTED>",
      "aws_secret_access_key": "<REDACTED>",
      "aws_security_token": "<REDACTED>",
      "aws_mqtt_user": "web####"
    }
  }
  ```
- **Campos consumidos (Confirmado, todos requeridos):** las 6 claves de `required_keys` (`api.py:107-114`). Si falta alguna → `Exception("Credenciales AWS incompletas o inválidas")`.
- **Errores:** `!=200` → excepción propagada.
- **Usado por:** `MySairMQTTClient._run` (directa o indirectamente).
- **Nota de seguridad:** estas credenciales son secretas y temporales; **no** deben loguearse. El código loguea el `aws_mqtt_user` (`api.py:130`) — ver `docs/security-and-privacy.md`.

---

## 2. Descubrimiento de sistemas (topología)

### 2.1 `GET /locations` — **Confirmado**
- **Finalidad:** listar ubicaciones de la cuenta.
- **Auth:** Bearer.
- **Respuesta (200):** `{ "entity": [ { "id": <LOCATION_ID>, ... }, ... ] }`
- **Campos consumidos:** solo `entity[0].id` (`__init__.py:39-40`). **Solo se usa la primera ubicación.** ⚠️ Ver hallazgos.
- **Errores:** `!=200` → excepción interna, pero el método **devuelve `[]`** (`api.py:151-153`), lo que el setup interpreta como "sin ubicaciones" → `return False`.
- **Certeza:** existencia **Confirmada**; campos distintos de `id` **Desconocidos**.

### 2.2 `GET /installations?location_id=<id>&validated=1` — **Confirmado**
- **Finalidad:** instalaciones (sistemas) dentro de una ubicación.
- **Auth:** Bearer.
- **Parámetros query:** `location_id` (requerido), `validated=1` (fijo — **Inferido:** filtra instalaciones validadas).
- **Respuesta (200):** `{ "entity": [ { "reference": "<INST_REF>", ... }, ... ] }`
- **Campos consumidos:** `entity[].reference` (`__init__.py:51`). El `reference` actúa como **`ctl`** (controlador) en MQTT y comandos.
- **Errores:** `!=200` → excepción; método devuelve `[]`.

### 2.3 `GET /devices?installation_ref=<ref>` — **Confirmado**
- **Finalidad:** dispositivos/termostatos (zonas) de una instalación.
- **Auth:** Bearer.
- **Parámetros query:** `installation_ref` (requerido).
- **Respuesta (200):** `{ "entity": [ { "reference": "<DEV_REF>", "name": "<ZONA>", ... }, ... ] }`
- **Campos consumidos:** `dev.reference` (o fallback `rf`/`id`) y `dev.name` (`climate.py:25-26`, `sensor.py:20-21`, `switch.py:19-20`).
- **Certeza:** los fallbacks `rf`/`id` sugieren que el nombre de campo **no está confirmado** al 100% → **Inferido**.

---

## 3. Envío de comandos e instrucciones

### 3.1 `POST /send/instruction` — **Confirmado**
- **Finalidad:** enviar **una o varias** instrucciones (comandos de control o solicitud de estado). El backend las traduce y las entrega a los dispositivos; el estado resultante vuelve por **MQTT**.
- **Auth:** Bearer.
- **Body:** array JSON de objetos instrucción.

**Estructura de instrucción (Confirmado — `api.py:269-276`, `__init__.py:156-163`):**
```json
[
  {
    "sender": "WEB",
    "ctl": "<INSTALLATION_REFERENCE>",
    "app": "<aws_mqtt_user o 'web0077'>",
    "device": "<DEVICE_REFERENCE o ''>",
    "command": "<mode|temp|power|status>",
    "value": "<depende del comando>"
  }
]
```

**Catálogo completo de comandos (CONFIRMADO desde la app oficial — ver `docs/protocol-findings.md`):**

| `command` | `value` | Semántica | Implementado |
|---|---|---|---|
| `mode` | `{"mode":"0".."5","temperature":"<tc>"}` | **Encender / fijar modo.** `m`: par=calor, impar=frío; {0,1,4,5}=AC, {2,3,4,5}=suelo | ✅ (solo `0`/`1`, AC) |
| `power` | `"0"` | **Apagar** (no existe `power:"1"`; encender se hace con `mode`) | ✅ |
| `temp` | `"<temperatura>"` (string) | Cambio de consigna | ✅ |
| `status` | `"sync"` (con `device:""`) | Solicitar estado | ✅ |
| `fanspeed` | `"<n>"` (string) | Velocidad de ventilador | ❌ (oportunidad) |
| `temporizer` | `<timer>` | Temporizador | ❌ (oportunidad) |
| `stop` | `"1"` | Parar instalación | ❌ |
| `programs` | `""` | Leer programas | ❌ |

> ✅ **Resuelto:** la codificación de modo del **comando** (`0`=calor, `1`=frío para AC) **es correcta** en la integración. La antigua "inconsistencia" venía de que el parser de estado leía `e` (encendido) como si fuera el modo; corregido en `status_parser.py` (usa `e` para on/off y la paridad de `m` para calor/frío). `switch.turn_on` ya no fuerza frío: enciende con `mode` preservando el último modo (por defecto calor). Ver `docs/protocol-findings.md §7`.

- **Respuesta esperada (201):**
  ```json
  { "msg": "Creado", "error": [] }
  ```
- **Validación (Confirmado, `api.py:216-223`):** exige `status_code == 201`, `msg == "Creado"` y `error` vacío; en otro caso lanza excepción.
- **Errores conocidos:**
  - `401` → refresca tokens + credenciales AWS y **reintenta una vez** (`api.py:205-213`).
  - Cualquier otro `!=201` → `Exception("Instruction error: ...")`.
  - `msg != "Creado"` o `error` no vacío → `Exception("Instruction rejected: ...")`.
- **Timeout:** 10 s. **Reintentos:** 1 (solo 401).
- **Usado por:** `send_zone_command` (climate/switch) y `refresh_status_periodic`.

**Ejemplo sanitizado — poner zona en calor a 21°:**
```json
[{ "sender":"WEB", "ctl":"INST_REF", "app":"webXXXX", "device":"DEV_REF",
   "command":"mode", "value":{"mode":"0","temperature":"21.0"} }]
```
**Ejemplo sanitizado — solicitar estado:**
```json
[{ "sender":"WEB", "ctl":"INST_REF", "app":"webXXXX", "device":"",
   "command":"status", "value":"sync" }]
```

---

## 4. Endpoints auxiliares / no confirmados

- No existen otros endpoints en el código.
- **Desconocido:** endpoints para escenas, programación horaria, velocidad de ventilador, apertura de compuertas, o lectura directa de estado por HTTP (el estado solo llega por MQTT).

---

## 5. Errores y robustez (observaciones)

| Aspecto | Situación | Certeza |
|---|---|---|
| Distinción de códigos HTTP | No se distingue 401/403/5xx salvo en `send_instruction` | Confirmado |
| Reautenticación proactiva | No hay; el `access_token` no se refresca hasta un 401 en instrucciones | Confirmado |
| `get_locations/installations/devices` tragan la excepción y devuelven `[]` | Puede enmascarar fallos de red como "sin datos" | Confirmado |
| `refresh_tokens` devuelve `False` en error | El llamador debe comprobarlo (lo hace) | Confirmado |
| Sin validación de esquema de respuesta | Se asume `entity` presente | Confirmado |

---

## 6. Ejemplo de sesión sanitizada (flujo completo)

```
POST /user/login                     → 200 {entity:{access_token, refresh_token}}
GET  /locations                      → 200 {entity:[{id:...}]}
GET  /installations?location_id=..   → 200 {entity:[{reference:...}]}
GET  /devices?installation_ref=..    → 200 {entity:[{reference, name}]}
PUT  /user/refreshawscredentials     → 200 {entity:{aws_*}}        (para MQTT)
POST /send/instruction  [status]     → 201 {msg:"Creado"}
POST /send/instruction  [mode/temp]  → 201 {msg:"Creado"}
```
