# Plan de ejecución — Estabilización

> Roadmap operativo de las tareas acordadas. Estado vivo: se actualiza al avanzar.
> Flujo de ramas: ramas de feature cortas desde `develop` → PR y merge contra `develop` → cuando se quiera, merge de `develop` a `main`. Ninguna tarea envía peticiones a producción.
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
| 10 | Empaquetado: `hacs.json` (G1), README completo (G2), `LICENSE` (MIT) | `hacs.json`, `README.md`, `LICENSE` | 🟡 Media | ✅ Hecho |
| 11 | Versionado + CHANGELOG (G3), retirar `quality_scale` no justificado (G4), ampliar `.gitignore` (G5) | `manifest.json`, `CHANGELOG.md`, `.gitignore` | 🟢 Baja | ✅ Hecho |
| 12 | Tests P2 con harness real de HA vía Docker (config flow, setup/unload) | `Dockerfile.test`, `docker-compose.yml`, `tests/` | 🟠 Alta | ✅ Hecho (93 tests verdes) |
| 13 | Tests P2 de entidades y eventos MQTT (climate/sensor/switch) | `tests/test_entities.py` | 🟡 Media | ✅ Hecho (103 tests verdes) |
| 14 | CI GitHub Actions: pytest P0/P1, pytest P2 (Docker), hassfest (B5) | `.github/workflows/tests.yml` | 🟡 Media | ✅ Hecho (verificado en PR #6, 3 jobs en verde) |
| 15 | Features de protocolo: sensor de humedad, disponibilidad heat/cool, min/max temp reales (F1/C8) | `sensor.py`, `climate.py` | 🟢 Baja | ✅ Hecho (107 tests verdes) |

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
- **Limitación en su momento, resuelta en la Tarea 12:** `config_flow.py` y `__init__.py` (unique_id, reauth, `ConfigEntryAuthFailed`/`NotReady`) no tenían tests automatizados por falta de Python ≥3.12 en el entorno de desarrollo. Verificado manualmente en producción por el usuario (cuenta real, 2026-07-20) para el camino feliz (login inicial + arranque normal); el camino de reauth (refresh_token inválido) no se ha probado en producción todavía.

### Tarea 10 — Empaquetado HACS y README (G1/G2)
- `hacs.json` en la raíz (`name`, `render_readme`, `homeassistant` mínimo) — habilita añadir el repo como repositorio personalizado de tipo Integración en HACS. La estructura `custom_components/mysair/` ya cumplía el layout esperado (Tarea 6).
- `README.md` reescrito: qué hace, entidades expuestas, instalación (HACS + manual), configuración (incluye la política de no guardar password tras A6), limitaciones conocidas (#15, #6, sin fan/auto), enlaces a `docs/` y `CLAUDE.md`, aviso de integración no oficial.
- `LICENSE` (MIT) añadido — el repo no tenía licencia formal pese a que el README original decía "feel free to use and modify it".
- **No incluido en esta tarea** (fuera de alcance, quedan en el roadmap): G3 (versionado semántico/CHANGELOG), G4 (revisar si `quality_scale: silver` en `manifest.json` está justificado), G5 (ampliar `.gitignore`).

### Tarea 11 — Versionado, quality_scale, .gitignore (G3/G4/G5)
- `CHANGELOG.md` (Keep a Changelog + SemVer): reconstruido desde `git log`, con `[2.0.0]` marcando el trabajo de estabilización/seguridad/empaquetado como cambio incompatible respecto a `1.0.0` (layout de instalación, corrección de `e`/`m`, password fuera de la config entry).
- `manifest.json`: `version` `1.0.0` → `2.0.0`; `quality_scale: silver` **retirado** (no estaba justificado: sin cobertura de tests con harness de HA, sin traducciones/`strings.json` (C4), sin icono de marca en `home-assistant/brands`). Se puede reclamar un nivel real cuando se cumplan esos requisitos.
- `.gitignore` ampliado: higiene de proyecto (`.DS_Store`, `.vscode/`, `.idea/`, `.ruff_cache`, `.coverage`, `dist/`, `build/`, `*.egg-info/`) y más patrones de capturas/dumps de protocolo (`*.pcap`, `*.pcapng`, `*.mitm`, `.env.*`, `scratchpad/`).

### Tarea 12 — Tests P2 con harness real de HA vía Docker
- **Contexto:** para evitar instalar Python 3.12 + `homeassistant` + `pytest-homeassistant-custom-component` en la máquina del desarrollador, se optó por Docker (decisión del usuario) en vez de un venv local — mismo resultado, sin ensuciar el host, reutilizable como imagen de CI (roadmap B5).
- **Hallazgo de ecosistema:** PyPI no publica `homeassistant` más reciente que `2025.1.4` (más antiguo que el `2025.10.0` mínimo documentado en el README); `pytest-homeassistant-custom-component==0.13.205` (la más reciente en PyPI) fija esa versión internamente vía `Requires-Dist`. Las APIs usadas por el código (`ConfigEntryAuthFailed`, `_get_reauth_entry`, `async_update_reload_and_abort`, `async_set_unique_id`) ya existían en 2025.1.4, así que los tests son válidos aunque no cubren la versión mínima exacta declarada.
- **Ajuste de `manifest.json` durante esta tarea:** `hassfest` (job del CI, Tarea 14) rechazó la clave `"homeassistant": "2025.10.0"` con `extra keys not allowed` — esa clave solo es válida para integraciones del repo core de HA, no para integraciones custom. Se retiró de `manifest.json`; el mínimo de versión sigue documentado en el README y en `hacs.json` (cuyo esquema sí la admite).
- `Dockerfile.test` + `docker-compose.yml` (servicio `test-ha`): Python 3.12-slim, código montado como volumen (no copiado — no hace falta reconstruir la imagen al editar).
- `requirements-test-ha.txt`: `pytest-homeassistant-custom-component==0.13.205` + `requests`/`websocket-client` (dependencias propias de la integración).
- **Bug de descubrimiento resuelto:** el fixture `hass` de `pytest-homeassistant-custom-component` importa su propio paquete `custom_components` de prueba (regular, no namespace) durante el setup, cacheando en `sys.modules` un `__path__` que apunta solo a su carpeta interna — nuestro `custom_components/mysair` nunca se encontraba pese a estar en `sys.path`. Solución en `tests/conftest.py`: un fixture `autouse` (activo solo si `pytest_homeassistant_custom_component` está instalado) que añade nuestra carpeta real al `__path__` ya cacheado.
- `tests/conftest.py`: import guardado (`try/except ImportError`) para que el fixture anterior no rompa el entorno P0/P1 sin HA; añadido `sys.path.insert(0, _REPO_ROOT)` para que `import custom_components` funcione como paquete namespace.
- `tests/test_ha_harness_smoke.py`: smoke test que confirma que `mysair` se descubre como custom component.
- `tests/test_config_flow.py` (6 tests): flujo feliz, `invalid_auth`, `cannot_connect`, `unique_id` duplicado (`already_configured`), reauth feliz (rota `refresh_token`, recarga la entrada), reauth con credenciales inválidas.
- `tests/test_init_setup_unload.py` (8 tests): setup feliz (entidades creadas, `refresh_token` rotado persistido), migración A6 (limpia `password`/`access_token` heredados), sin `refresh_token` → `ConfigEntryAuthFailed`, sesión inválida → `ConfigEntryAuthFailed`, error de conexión → `ConfigEntryNotReady`, sin ubicaciones/instalaciones → `ConfigEntryNotReady`, unload limpio.
- `MySairAPI`/`MySairMQTTClient` parcheados con `monkeypatch` en los tests (sin red real, sin hilos/websockets reales), consistente con `docs/testing-strategy.md` §2.1 ("sin red real").
- **Comandos:** `docker compose run --rm test-ha` (93 tests: 79 P0/P1 + 14 P2). El entorno local (`.venv-test`, Python 3.9) sigue en 78 pasados + 3 saltados (los 3 ficheros P2, vía `pytest.importorskip("homeassistant")`).

### Tarea 13 — Tests de entidades y eventos MQTT (climate/sensor/switch)
- `tests/test_entities.py` (10 tests), reutilizando el patrón de mocks de la Tarea 12: setup completo de la entry, luego `hass.bus.async_fire(f"{DOMAIN}_update", {...})` con payloads ya normalizados (`{"ctl", "zones": [...]}`, mismas claves que produce `parse_status_payload`).
- Cubre: climate (temp actual/consigna, `hvac_mode`/`hvac_action` según `is_on`/`is_cool`/`is_heat`/`is_standby`), los 3 sensores, switch (`is_on` + memoria del último modo AC), filtro por `ctl` (evento de otra instalación se ignora), y los comandos (`climate.set_hvac_mode`, `climate.set_temperature` en OFF sin enviar comando, `switch.turn_on`/`turn_off` preservando modo) verificando los argumentos exactos pasados a `send_zone_command` (parcheado, sin red real).
- Todos los tests pasaron a la primera ejecución en Docker — el diseño se basó en una lectura completa de `climate.py`/`sensor.py`/`switch.py` antes de escribirlos, sin iteración de depuración.
- 103 tests verdes en total (78 P0/P1 + 25 P2).
- **Pendiente (menor, no bloqueante):** reload sin tareas duplicadas, reintento tras credenciales caducadas en un comando (401), mensajes MQTT duplicados/fuera de orden (tabla P3 de `docs/testing-strategy.md`).

### Tarea 14 — CI GitHub Actions (B5)
- `.github/workflows/tests.yml`, disparado en `push`/`pull_request` contra `main` y `develop` (encaja con el flujo de ramas: feature → PR contra `develop` → CI corre solo).
- Tres jobs independientes: `pure-tests` (pytest P0/P1, Python 3.12 en el runner), `ha-harness-tests` (`docker compose run --rm test-ha`, reutiliza `Dockerfile.test` de la Tarea 12 tal cual), `hassfest` (acción oficial `home-assistant/actions/hassfest@master`, valida `manifest.json` y la estructura de `custom_components/mysair/`).
- **`ruff` deliberadamente fuera de esta tarea:** activarlo en CI sin tenerlo configurado localmente arriesga sacar a la luz una ola de hallazgos de lint sin triar en el mismo cambio que "añadir CI" — se deja como tarea separada (config de `ruff` + limpieza del código existente antes de exigirlo en CI).
- **Verificado en PR #6:** `hassfest` encontró dos problemas reales de `manifest.json` que ni el análisis anterior había detectado — la clave `homeassistant` no es válida en el manifest de una integración custom (solo aplica al repo core de HA), y las claves deben ir ordenadas (`domain`, `name`, alfabético). Corregidos ambos; los 3 jobs pasan en verde.

### Tarea 15 — Features de protocolo: humedad, disponibilidad heat/cool, min/max temp (F1/C8)
- `sensor.py`: nueva `MySairHumiditySensor` (`SensorDeviceClass.HUMIDITY`) por zona, leyendo `zone["humidity"]` (`hm`) — mismo patrón que los otros 3 sensores.
- `climate.py`: `_attr_hvac_modes` deja de ser fijo `[OFF, HEAT, COOL]` a nivel de clase; se recalcula por entidad en cada `mysair_update` según `allow_heat`/`allow_cool` (`c`/`f`), siempre incluyendo `OFF`. Antes del primer status MQTT se usan los 3 modos como valor por defecto razonable.
- `climate.py` (C8): `_attr_min_temp`/`_attr_max_temp` pasan de constantes de clase (10/30) a atributos de instancia actualizados desde `zone["temp_min"]`/`zone["temp_max"]` (`tmm`/`tmx`) cuando llegan por MQTT.
- **Hallazgo real durante el testing:** HA (2025.1.4, la versión pinneada del harness) todavía solo **avisa** por log si se pide un `hvac_mode` fuera de `hvac_modes` de la entidad ("dejará de funcionar en 2025.4 y lanzará un error") — no lo rechaza a nivel de servicio todavía. El rechazo real lo hace nuestro propio guard en `climate.async_set_hvac_mode` (`if hvac_mode not in self._attr_hvac_modes: return`), que ya existía. Documentado por si en una versión de HA posterior a 2025.4 el comportamiento cambia a excepción dura.
- Tests: 4 nuevos en `test_entities.py` (humedad, min/max temp dinámico, `hvac_modes` restringido, comando rechazado cuando el modo no está permitido) + `_zone()` (fixture compartida) actualizada con capacidades realistas por defecto. 107 tests verdes en total.
- **Fuera de alcance deliberadamente:** control real de ventilador/velocidad de fan (`vv`, comando `fanspeed`) y suelo radiante — solo se expone la disponibilidad de calor/frío ya parseada, no se implementan comandos nuevos.

### Pendiente (no bloqueado, siguiente)
- Features desde hallazgos: sensor de humedad (`hm`), ventilador (`fanspeed`/`vv`), disponibilidad heat/cool (`c`/`f`).
- Robustez del parser de frame MQTT (#6, requiere dump real).
- Traducciones/`strings.json` (C4) — desbloquearía poder reclamar `quality_scale` de nuevo.
