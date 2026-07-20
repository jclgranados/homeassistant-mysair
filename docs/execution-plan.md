# Plan de ejecución — Estabilización

> Roadmap operativo de las tareas acordadas. Estado vivo: se actualiza al avanzar.
> Rama de trabajo: `stabilization`. Ninguna tarea envía peticiones a producción.
> Referencia amplia: `docs/development-roadmap.md`. Bugs de contexto: `CLAUDE.md §11`.

## Estado

| # | Tarea | Archivos | Prioridad | Estado |
|---|---|---|---|---|
| 1 | Corregir unload + gestionar tarea periódica (A1+A2) | `__init__.py` | 🔴 Crítica | ✅ Hecho (intervalo 120 s) |
| 2 | Limpiar `requirements` y preload de paho (A4) | `manifest.json`, `__init__.py` | 🟠 Alta | ✅ Hecho |
| 3 | Eliminar o reescribir `select.py` (A3) | `select.py`, `__init__.py` | 🔴 Crítica | ✅ Hecho (eliminado) |
| 4 | Refactor de testabilidad (B1) | `status_parser.py`, `api.py` | 🟠 Alta | ✅ Hecho |
| 5 | Primeros tests P0/P1 + fixtures (B2/B3) | `tests/` | 🟠 Alta | ✅ Hecho (57 tests verdes) |
| 6 | Reestructurar a `custom_components/mysair/` (G1) | todo el paquete | 🟡 Media | ✅ Hecho (desbloquea pytest + HACS) |
| 7 | Corregir codificación de modo/encendido (A5) | `status_parser.py`, `climate.py`, `sensor.py`, `switch.py` | 🔴 Crítica | ✅ Hecho (confirmado con app oficial) |
| 8 | Robustez MQTT: client_id único, refresco creds, topic dinámico (#20/#22/#5) | `mqtt_handler.py`, `api.py` | 🔴 Crítica | ✅ Hecho (69 tests verdes) |
| 9 | Modernización HA: `unique_id` (C2), password fuera de la config entry (A6), reauth flow (C3) | `config_flow.py`, `api.py`, `__init__.py` | 🟠 Alta | ✅ Hecho (78 tests verdes) |

> Nota: A1 y A2 se ejecutan juntas porque el cierre limpio del unload depende de poder cancelar la tarea periódica.
> A5 quedó **desbloqueada** al analizar el bundle oficial de la app (`docs/protocol-findings.md`): `e`=encendido, `m`=modo (par=calor, impar=frío). Credenciales (A6/A7) siguen pendientes de `docs/known-unknowns.md` #22.

## Detalle

### Tarea 1 — Unload + tarea periódica (A1+A2)
- Mover `async_unload_entry` a **nivel de módulo** con firma estándar `(hass, entry)`.
- Orden de cierre: `async_unload_platforms` → parar MQTT → limpiar `hass.data`.
- Eliminar el registro erróneo `entry.add_update_listener(async_unload_entry)`.
- Convertir la tarea de refresco en cancelable (`entry.async_create_background_task`) para que HA la cancele en unload.
- Eliminar el no-op `getattr(api, "close", ...)` (api no tiene `close`).
- Alinear intervalo de refresco con el comentario (decisión de intervalo pendiente de confirmar).

### Tarea 2 — Requirements + preload (A4)
- `manifest.json`: dejar `requests` y `websocket-client==1.8.0`; quitar `aiohttp`, `paho-mqtt`, `boto3`.
- Eliminar el preload `__import__("paho.mqtt.client")` de `__init__.py`.

### Tarea 3 — select.py (A3)
- Decisión: eliminar (código muerto, no cargado) o reescribir alineado. Por defecto: **eliminar** salvo indicación contraria.

### Tarea 4 — Refactor testabilidad (B1)
- Extraer `parse_status_payload(payload) -> dict` a módulo puro e importable.
- Permitir inyección de `requests.Session` en `MySairAPI` para poder mockear.

### Tarea 5 — Tests P0/P1 (B2/B3)
- `pytest` + fixtures sanitizadas (`docs/testing-strategy.md`).
- Cobertura: builders MQTT, firma SigV4 (reloj fijo), parser de status, login/instruction HTTP.
- Tests con harness de HA (config flow, entidades) pendientes de HA + Python ≥3.12.

### Tarea 7 — Codificación de modo/encendido (A5)
- Fuente de verdad: `docs/protocol-findings.md` (bundle oficial `app.09acea34.js`).
- `status_parser.py`: `e`→`is_on`/`is_standby`; `m`→`is_heat`/`is_cool`/`is_ac`/`is_floor` (`parse_mode`); añadidos `humidity`, `fan_mode`, capacidades `allow_*`.
- `climate.py`: OFF si `e=="0"`; si no, HEAT/COOL por paridad de `m`; standby (`e=="2"`)→`HVACAction.IDLE`.
- `sensor.py` (modo): OFF/HEAT/COOL derivado de `is_on` + paridad de `m`.
- `switch.py`: `turn_on` deja de forzar frío; envía `mode` preservando el último modo AC conocido (por defecto calor `"0"`); `is_on` desde `e`.
- Tests: reescrito `test_status_parser` a la semántica correcta (57 tests verdes).

### Tarea 8 — Robustez MQTT (#20/#22/#5)
- Fuente: `docs/protocol-findings.md §6b` (bundle oficial).
- `mqtt_handler.build_client_id()`: clientId único por conexión `mqtt-client_{accessKey}_{ts}_{rand}` (antes `aws_mqtt_user` → colisión con la app).
- `mqtt_handler.build_status_topic()`: topic desde `aws_base_topic` (fallback `pro/v1/`).
- `api.refresh_aws_credentials`: captura `aws_base_topic` y `aws_expires_at`.
- `api.aws_credentials_expired()`: refresco proactivo por `aws_expires_at`; el `_run` de MQTT lo consulta en cada intento (antes solo si faltaban).
- Seguridad: el log de conexión ya no imprime la URL firmada (solo host + clientId).
- Tests: `tests/test_mqtt_connection.py` (client_id único/formato, topic, expiración). 69 tests verdes.

### Tarea 9 — Modernización HA: unique_id, password fuera de la config entry, reauth (C2/A6/C3)
- `config_flow.py`: `async_set_unique_id(email.lower())` + `_abort_if_unique_id_configured()` en `async_step_user` (evita entradas duplicadas de la misma cuenta).
- `config_flow.py`: la config entry solo guarda `email` + `refresh_token`; el `password` se usa solo en memoria durante el flujo y nunca se persiste.
- `api.py`: `login()`/`refresh_tokens()` lanzan `MySairAuthError` (credenciales/refresh_token inválidos) o `MySairConnectionError` (red/backend) en vez de una `Exception` genérica o `return False`. `MySairAPI` acepta `password=None` (ya no obligatorio) y un callback opcional `on_tokens_refreshed(access_token, refresh_token)` invocado tras cada login/refresh (el refresh_token rota en cada renovación).
- `__init__.py`: `async_setup_entry` ya no hace `login()` con password; renueva la sesión con `api.refresh_tokens()` a partir del `refresh_token` guardado. `MySairAuthError` → `ConfigEntryAuthFailed` (dispara reauth en la UI de HA); `MySairConnectionError` / sin ubicaciones / sin instalaciones → `ConfigEntryNotReady` (HA reintenta con backoff). El callback `on_tokens_refreshed` persiste el nuevo `refresh_token` en la config entry vía `hass.loop.call_soon_threadsafe`.
- **Migración automática:** en el primer arranque correcto tras esta actualización, si la config entry todavía tiene `password`/`access_token` de instalaciones previas, se eliminan de `entry.data`.
- `config_flow.py`: `async_step_reauth` / `async_step_reauth_confirm` piden la contraseña de nuevo y renuevan el `refresh_token` con `async_update_reload_and_abort` (recarga la entrada automáticamente).
- Tests: 9 nuevos en `test_api.py` (excepciones tipadas, callback de rotación de tokens). 78 tests verdes.
- **Limitación conocida:** `config_flow.py` y `__init__.py` (unique_id, reauth, `ConfigEntryAuthFailed`/`NotReady`) no tienen tests automatizados — requieren `pytest-homeassistant-custom-component` + Python ≥3.12, no disponibles en este entorno (ver `docs/testing-strategy.md`). Verificado manualmente en producción por el usuario (cuenta real, 2026-07-20) para el camino feliz (login inicial + arranque normal); el camino de reauth (refresh_token inválido) no se ha probado en producción todavía.

### Pendiente (no bloqueado, siguiente)
- Features desde hallazgos: sensor de humedad (`hm`), ventilador (`fanspeed`/`vv`), disponibilidad heat/cool (`c`/`f`).
- Robustez del parser de frame MQTT (#6, requiere dump real).
