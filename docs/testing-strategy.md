# Estrategia de tests

> Documento originalmente escrito como propuesta antes de implementar nada; se
> mantiene en presente/futuro como registro del razonamiento, con notas "✅
> Implementado" donde ya existe. Estado actual real (2026-07-21): **229 tests**
> (157 P0/P1 sin HA + 72 P2 con harness de HA vía Docker). Ver
> `docs/execution-plan.md` (28 tareas) para el detalle completo de cada tanda;
> las referencias puntuales de más abajo solo cubren las tareas que crearon
> la cobertura original (5, 12, 13) y no se han mantenido actualizadas tarea
> a tarea desde entonces — para "qué se implementó cuándo" usar
> `execution-plan.md`, no este documento.

---

## 0. Cómo ejecutar los tests (actualizado)

**P0/P1 (sin Home Assistant, Python 3.9+, en la máquina del desarrollador):**
```bash
python -m venv .venv-test && source .venv-test/bin/activate
pip install -r requirements-test.txt
pytest
```

**P2 (con harness de Home Assistant, vía Docker — no instala nada en tu máquina):**
```bash
docker compose run --rm test-ha
```
Requiere Docker. La imagen (`Dockerfile.test`) instala Python 3.12 +
`pytest-homeassistant-custom-component` (`requirements-test-ha.txt`) en un
contenedor aislado; el código se monta como volumen, así que no hay que
reconstruir la imagen al editar tests o código.

> ⚠️ **Techo de versión conocido:** PyPI no publica `homeassistant` más allá de
> `2025.1.4` (más antiguo que el `2025.10.0` mínimo documentado en el README —
> `hassfest` no permite declarar la clave `homeassistant` en el
> `manifest.json`); `pytest-homeassistant-custom-component` fija esa versión
> internamente. Las APIs que usamos (`ConfigEntryAuthFailed`,
> `_get_reauth_entry`, `async_update_reload_and_abort`, `async_set_unique_id`)
> ya existían en 2025.1.4, así que los tests siguen siendo válidos, pero no
> validan contra la versión mínima exacta que declaramos soportar.

Ambos conjuntos conviven en el mismo directorio `tests/`: los ficheros P2
(`test_config_flow.py`, `test_init_setup_unload.py`, `test_ha_harness_smoke.py`)
usan `pytest.importorskip("homeassistant")`, así que al correr `pytest` sin
Docker se saltan limpiamente en vez de fallar.

---

## 1. Situación previa (antes de este trabajo)

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

### P0 — Funciones puras (sin HA, sin red) — ✅ Implementado (`test_mqtt_builders.py`, `test_aws_sign.py`, `test_status_parser.py`)
| Test | Qué valida | Notas |
|---|---|---|
| `encode_varint`/`decode_varint` | Codificación/decodificación de longitudes, roundtrip | Ampliado con `_next_packet_length` (E2, Tarea 26): distingue paquete incompleto de malformado |
| `build_mqtt_connect` | Cabecera fija 0x10, flags 0xC2, keepalive 60, campos client/user/pass | Bytes exactos |
| `build_mqtt_subscribe` | Cabecera 0x82, packet_id, topic, QoS 0 | Bytes exactos |
| `aws_sign_url` (reloj fijo) | Estructura de la URL, presencia de `X-Amz-*`, firma determinista | `freezegun`; no valida contra AWS |
| `parse_status_payload`/`parse_feedback_payload` | `value` string→JSON, limpieza `;`, mapeo `t[]`→zonas, `e`→mode, rechazo (`None`) de payloads no-dict (E4) | Extraído a `status_parser.py` (módulo puro, sin HA) |
| `parse_mqtt_publish` | Decodificación conforme al estándar MQTT (remaining length + Topic Name + payload) | E1, con heurística de texto como respaldo |
| `compute_mode_value` | Inversa de `parse_mode`: calcula `m` dado calor/frío + AC + suelo | F4, para el control de suelo radiante |
| `compute_backoff_delay` | Backoff exponencial con jitter, tope, nunca negativo | E3 |

### P1 — Cliente HTTP (`requests` mockeado) — ✅ Implementado (`test_api.py`)
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

### P1 — Config flow (harness HA) — ✅ Implementado (`tests/test_config_flow.py`)
| Test | Escenario |
|---|---|
| Flujo feliz | login OK → `async_create_entry` con `email` + `refresh_token` (sin password) |
| Auth inválida | `MySairAuthError` → error `invalid_auth` |
| Fallo de conexión | `MySairConnectionError` → error `cannot_connect` |
| unique_id duplicado | misma cuenta (email normalizado) → abort `already_configured` |
| Reauth feliz | `async_step_reauth_confirm` → `refresh_token` actualizado, abort `reauth_successful` |
| Reauth con credenciales inválidas | error `invalid_auth`, `refresh_token` no se toca |

### P2 — MQTT (sin broker real) — mayormente ✅ Implementado (`test_mqtt_connection.py`, P0/P1 — no requiere HA pese al nombre "P2" original)
| Test | Escenario | Estado |
|---|---|---|
| CONNACK → SUBSCRIBE | Simular frame `0x20`; verificar SUBSCRIBE a `pro/v1/get/ctl/{ref}/#` por instalación | ✅ Implementado |
| SUBACK | Frame `0x90` → sin efectos secundarios | ✅ Implementado |
| PUBLISH status | Frame `0x30` con `(topic){json}` → callback recibe `{topic,payload}` | ✅ Implementado |
| Payload sin JSON | Frame sin `{` → warning, sin crash, contabilizado en `parse_error_count` (D4) | ✅ Implementado |
| Payload con `;` final | Se limpia y parsea | ✅ Implementado |
| Frame partido / multi-paquete | Paquete MQTT partido entre dos mensajes WS, o varios coalescidos en uno | ✅ Implementado (E2, Tarea 26) — con bytes sintéticos; **falta confirmar con una captura real de producción** |
| `connected=False` en `on_close`, backoff puro | Componentes verificados por separado (`_on_close`, `compute_backoff_delay`) | ✅ Implementado |
| Reconexión end-to-end | Ciclo completo `_run()`: `on_close` → espera con backoff → reconecta → CONNACK | 🟡 No testeado como flujo íntegro — `_run()` es un bucle bloqueante, difícil de testear sin arrancar hilos reales; solo sus piezas se prueban sueltas |
| Resuscripción tras reconectar | Tras una reconexión, se vuelve a mandar SUBSCRIBE a todos los topics | 🟡 Se cumple por diseño (cada `_run()` repite CONNECT→CONNACK→SUBSCRIBE), pero sin un test dedicado que lo verifique como escenario de reconexión |
| Mensaje duplicado | Dos `status` iguales → entidad no reescribe (comparación de valor) | 🔴 Pendiente |
| Mensaje fuera de orden | `status` con consigna vieja tras una nueva → documentar comportamiento actual (sobrescribe) | 🔴 Pendiente |

### P2 — Ciclo de vida del setup (harness HA) — ✅ Implementado (`tests/test_init_setup_unload.py`)
| Test | Escenario |
|---|---|
| Setup entry feliz | `refresh_tokens` OK + HTTP mockeado → entry `LOADED`, entidades creadas, `refresh_token` rotado persistido |
| Migración A6 | Entry con `password`/`access_token` heredados de antes → se eliminan en el primer setup correcto |
| Sin `refresh_token` guardado | Setup falla, entry `SETUP_ERROR` (dispara reauth) |
| Sesión inválida (`MySairAuthError`) | Setup falla, entry `SETUP_ERROR` (dispara reauth) |
| Fallo de conexión (`MySairConnectionError`) | Setup falla, entry `SETUP_RETRY` (HA reintenta solo) |
| Sin ubicaciones / sin instalaciones | Setup falla, entry `SETUP_RETRY` |
| Unload | MQTT `stop()` llamado, `hass.data[DOMAIN]` limpio, entry `NOT_LOADED` |

### P2 — Entidades y eventos MQTT (harness HA) — ✅ Implementado (`tests/test_entities.py`)
| Test | Escenario |
|---|---|
| `mysair_update` → climate | Actualiza current/target temp y hvac_mode/action según `is_on`/`is_cool`/`is_heat`/`is_standby` |
| `mysair_update` → climate (off/standby) | OFF si `is_on=False`; standby → `HVACAction.IDLE` con modo preservado |
| `mysair_update` → sensores | Actualizan native_value (temp actual, consigna, modo OFF/HEAT/COOL) |
| `mysair_update` → switch | `is_on` según `is_on`; recuerda el último modo AC (`mode_raw`) |
| Filtro por `ctl` | Evento de otra instalación no afecta a la entidad |
| Comando climate set_hvac_mode | Llama `send_zone_command` con `mode`/`0`|`1` y la consigna actual |
| Comando set_temperature en OFF | No envía comando, solo actualiza estado local |
| Comando switch on/off | Envía `mode` (preservando último modo AC) / `power` |
| Switch preserva modo tras MQTT | `turn_on` reusa el `mode_raw` recibido por MQTT, no fuerza calor |

### P2 — Pendiente
| Test | Escenario |
|---|---|
| Mensaje duplicado / fuera de orden | Ver tabla P3 más abajo |

> ✅ **"Credenciales caducadas: 401 en comando → refresh y reintento"** ya está implementado y testeado
> (`test_send_instruction_401_refreshes_and_retries` en `test_api.py`) — quitado de esta tabla.
> ✅ **"Reload"** ya está implementado y testeado (`test_reload_entry_does_not_duplicate_entities_or_service`
> en `test_init_setup_unload.py`, Tarea 30) — quitado de esta tabla.

### P3 — Escenarios avanzados / robustez
| Test | Escenario | Estado |
|---|---|---|
| Payload incompleto | `t[]` sin `tr`/`tc` → campo queda `None` (no `0.0`: corregido, la implementación real usa `_to_float` que devuelve `None` ante valores ausentes/no convertibles) | ✅ Implementado (comportamiento ya cubierto en `test_status_parser.py`) |
| Payload desconocido | Campos extra ignorados sin error | ✅ Implementado (E4, Tarea 26): deliberadamente permisivo ante claves nuevas del backend, ver `known-unknowns.md` |
| Migración de config | `async_migrate_entry` (cuando exista VERSION>1) | 🔴 Pendiente (no ha hecho falta todavía; la única migración real hasta ahora, A6, se hace a mano en `async_setup_entry`, no vía `async_migrate_entry`; con `VERSION` todavía en `1` no hay nada a lo que migrar, ver Tarea 30) |
| Cambio de topología | Zona nueva/eliminada entre reinicios → limpieza automática | ✅ Implementado (Tarea 31, `test_topology_change_removes_orphaned_zone_device_and_entities`) — `_cleanup_stale_zone_devices` (`__init__.py`) elimina el dispositivo (y todas sus entidades) de una zona que ya no aparece en `get_devices()`, comparando contra el `device_registry` en cada setup/reload; la zona nueva se crea con normalidad. Sustituye el comportamiento huérfano documentado en la Tarea 30. |
| Varios sistemas en una cuenta | 2 instalaciones → suscripción y entidades por cada una | ✅ Implementado (Tarea 30, `test_setup_entry_multiple_installations`) |
| Sin ubicaciones | `get_locations` `[]` → setup `return False` | ✅ Implementado (`test_init_setup_unload.py`, aunque el comportamiento real hoy es `ConfigEntryNotReady`, no `return False`) |

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
