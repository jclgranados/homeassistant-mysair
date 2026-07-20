# Estrategia de tests

> Estado actual: **no existen tests, fixtures ni configuración de test**. **Confirmado.**

---

## 1. Situación actual

| Elemento | Estado |
|---|---|
| Tests unitarios | ❌ ninguno |
| Tests de integración | ❌ ninguno |
| Fixtures | ❌ ninguno |
| Mocks | ❌ ninguno |
| CI (GitHub Actions) | ❌ ausente |
| `pytest`/`pytest-homeassistant-custom-component` | ❌ no declarado |
| Facilidad de ejecución | N/A — no hay nada que ejecutar |

**Barreras para testear el código tal cual:**
- `MySairAPI` usa `requests` directamente sin inyección de sesión → hay que parchear `requests.*`.
- `MySairMQTTClient` construye MQTT a mano sobre `websocket.WebSocketApp` → difícil de mockear; conviene testear los *builders* puros (`encode_varint`, `build_mqtt_connect`, `build_mqtt_subscribe`) y el parsing por separado.
- El parsing de estado está **acoplado** dentro de `mqtt_message_callback` (una función anidada en `__init__.py`) → no es importable directamente. Refactor recomendado: extraer `parse_status_payload(payload) -> dict` a un módulo puro.
- Las entidades dependen del **event bus**; se testean con el harness `hass` de `pytest-homeassistant-custom-component`.

---

## 2. Principios de la estrategia propuesta

1. **Sin red real:** todo mockeado. Ningún test toca `api.mysair.es` ni AWS IoT.
2. **Fixtures derivadas solo del código:** los payloads de ejemplo usan **únicamente** campos que el código lee (`rf,n,tr,tc,tmm,tmx,e`; `entity`, `reference`, `name`, `id`, `aws_*`). **No inventar campos.**
3. **Priorizar funciones puras primero** (builders MQTT, parser de status, firma SigV4 con reloj fijo) — alto valor, bajo coste.
4. **Luego el ciclo de vida** con el harness de HA.
5. Marcar como **pendientes/skip** los tests que requieran confirmar semántica desconocida (p. ej. codificación real de modo).

---

## 3. Herramientas recomendadas

- `pytest`, `pytest-asyncio`
- `pytest-homeassistant-custom-component` (proporciona `hass`, `MockConfigEntry`, `aioclient_mock`)
- `responses` o `requests-mock` para el cliente `requests` síncrono
- `freezegun` para fijar el reloj en tests de firma SigV4

Estructura sugerida:
```
tests/
├── conftest.py            # hass, config entry mock, fixtures de payloads
├── fixtures/
│   ├── login.json
│   ├── locations.json
│   ├── installations.json
│   ├── devices.json
│   ├── aws_credentials.json
│   └── mqtt_status.json
├── test_api.py
├── test_mqtt_builders.py
├── test_mqtt_parsing.py
├── test_config_flow.py
├── test_init_setup_unload.py
├── test_climate.py
├── test_sensor.py
└── test_switch.py
```

---

## 4. Casos de prueba priorizados

### P0 — Funciones puras (sin HA, sin red)
| Test | Qué valida | Notas |
|---|---|---|
| `encode_varint` | Codificación de longitudes (0, 127, 128, 16383, 16384) | Confirmable contra spec MQTT |
| `build_mqtt_connect` | Cabecera fija 0x10, flags 0xC2, keepalive 60, campos client/user/pass | Bytes exactos |
| `build_mqtt_subscribe` | Cabecera 0x82, packet_id, topic, QoS 0 | Bytes exactos |
| `aws_sign_url` (reloj fijo) | Estructura de la URL, presencia de `X-Amz-*`, firma determinista | `freezegun`; no valida contra AWS |
| `parse_status_payload` (**tras extraer**) | `value` string→JSON, limpieza `;`, mapeo `t[]`→zonas, `e`→mode | Requiere refactor previo |

### P1 — Cliente HTTP (`requests` mockeado)
| Test | Escenario |
|---|---|
| Login OK | 200 con `entity.access_token` → token asignado |
| Login credenciales inválidas | 401 → excepción |
| Login sin token en respuesta | 200 sin `access_token` → excepción |
| `get_locations` OK / error | 200 lista / 500 → `[]` |
| `get_installations` con query correcta | Verifica `location_id` y `validated=1` en la URL |
| `get_devices` OK | Devuelve lista `entity` |
| `send_instruction` 201 `Creado` | Éxito |
| `send_instruction` respuesta con `error` no vacío | Excepción "rejected" |
| `send_instruction` 401 → refresh → reintento | Mock 401 luego 201; verifica `refreshtokens`+`refreshawscredentials` llamados |
| `send_instruction` timeout | `requests.exceptions.Timeout` → excepción |
| `refresh_aws_credentials` incompleto | Falta una `aws_*` key → excepción |
| `send_zone_command` mode/temp/power | Construcción correcta del `value` por tipo |

### P1 — Config flow (harness HA)
| Test | Escenario |
|---|---|
| Flujo feliz | login OK → `async_create_entry` con datos |
| Auth inválida | login sin token → error `invalid_auth` |
| Fallo de conexión | excepción en login → error `cannot_connect` |
| (Futuro) unique_id | evitar duplicados (tras arreglar el bug) |

### P2 — MQTT (sin broker real)
| Test | Escenario |
|---|---|
| CONNACK → SUBSCRIBE | Simular frame `0x20`; verificar SUBSCRIBE a `pro/v1/get/ctl/{ref}/#` por instalación |
| SUBACK | Frame `0x90` → sin efectos secundarios |
| PUBLISH status | Frame `0x30` con `(topic){json}` → callback recibe `{topic,payload}` |
| Payload sin JSON | Frame sin `{` → warning, sin crash |
| Payload con `;` final | Se limpia y parsea |
| Reconexión | `on_close` → `connected=False` → reintento tras backoff (mock `sleep`) |
| Resuscripción | Tras reconectar, re-SUBSCRIBE a todos los topics |
| Mensaje duplicado | Dos `status` iguales → entidad no reescribe (comparación de valor) |
| Mensaje fuera de orden | `status` con consigna vieja tras una nueva → documentar comportamiento actual (sobrescribe) |
| Frame partido | (Documentar limitación: hoy no se soporta) |

### P2 — Entidades y ciclo de vida (harness HA)
| Test | Escenario |
|---|---|
| Setup entry | Con HTTP mockeado, crea N entidades por zona |
| `mysair_update` → climate | Actualiza current/target temp y hvac_mode/action según `e` |
| `mysair_update` → sensores | Actualizan native_value; no reescriben si igual |
| `mysair_update` → switch | `is_on` según `mode in [1,2]` |
| Comando climate set_hvac_mode | Llama `send_zone_command` con args correctos; estado optimista |
| Comando set_temperature en OFF | No envía comando, solo local |
| Comando switch on/off | Envía mode/power correctos |
| Filtro por `ctl`/`zone_id` | Evento de otra instalación no afecta a la entidad |
| Unload (**tras arreglar bug**) | MQTT parado, tarea cancelada, `hass.data` limpio |
| Reload (**tras arreglar bug**) | Sin tareas duplicadas |
| Credenciales caducadas | 401 en comando → refresh y reintento |

### P3 — Escenarios avanzados / robustez
| Test | Escenario |
|---|---|
| Payload incompleto | `t[]` sin `tr`/`tc` → usa `0.0` por defecto (documentar) |
| Payload desconocido | Campos extra ignorados sin error |
| Migración de config | `async_migrate_entry` (cuando exista VERSION>1) |
| Cambio de topología | Zona nueva/eliminada entre reinicios → entidades huérfanas (documentar) |
| Varios sistemas en una cuenta | 2 instalaciones → suscripción y entidades por cada una |
| Sin ubicaciones | `get_locations` `[]` → setup `return False` |

---

## 5. Fixtures sanitizadas propuestas (solo campos usados)

> Valores ficticios; **no** contienen datos reales.

`fixtures/login.json`
```json
{ "entity": { "access_token": "TEST_ACCESS", "refresh_token": "TEST_REFRESH" } }
```
`fixtures/locations.json`
```json
{ "entity": [ { "id": 1001 } ] }
```
`fixtures/installations.json`
```json
{ "entity": [ { "reference": "INST_A" } ] }
```
`fixtures/devices.json`
```json
{ "entity": [ { "reference": "DEV_1", "name": "Salon" },
              { "reference": "DEV_2", "name": "Dormitorio" } ] }
```
`fixtures/aws_credentials.json`
```json
{ "entity": {
  "aws_mqtt_host": "test.iot.eu-west-1.amazonaws.com",
  "aws_default_region": "eu-west-1",
  "aws_access_key_id": "TESTKEYID",
  "aws_secret_access_key": "TESTSECRET",
  "aws_security_token": "TESTTOKEN",
  "aws_mqtt_user": "web0000"
} }
```
`fixtures/mqtt_status.json` (el `value` es un string con JSON anidado, como en producción)
```json
{ "ctl": "INST_A",
  "value": "{\"t\":[{\"rf\":\"DEV_1\",\"n\":\"Salon\",\"tr\":22.5,\"tc\":21.0,\"tmm\":10.0,\"tmx\":30.0,\"e\":1}]};" }
```

---

## 6. Tests frágiles a evitar / vigilar

- Cualquier aserción sobre la **semántica** de `e`/`m` (modo) hasta confirmarla con dispositivo real → marcar `xfail`/`skip` con nota.
- Aserciones sobre bytes exactos de la firma SigV4 sin fijar reloj → usar `freezegun`.
- Tests que dependan del `sleep(10)` real de reconexión → mockear `time.sleep`.
- Tests de timing del refresco de 60 s → controlar el reloj del loop, no dormir de verdad.

---

## 7. Orden de implementación sugerido

1. Refactor mínimo para testabilidad (extraer `parse_status_payload`; inyectar `requests.Session`). *(cambio de código — fuera de fase 1)*
2. P0 (funciones puras).
3. P1 (HTTP + config flow).
4. P2 (MQTT + entidades + ciclo de vida) — **después** de corregir el bug de unload.
5. P3 (robustez).
6. CI con GitHub Actions (`pytest` + `hassfest` + `ruff`).
