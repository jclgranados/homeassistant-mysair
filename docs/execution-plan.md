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
