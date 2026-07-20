# CLAUDE.md — Guía para sesiones de Claude Code

Integración **custom de Home Assistant** para el sistema de zonificación de aire acondicionado **MySair**. Construida por ingeniería inversa de la app web oficial (API HTTP + AWS IoT MQTT). Toda la documentación de referencia está en `docs/`.

---

## 1. Propósito del proyecto

Controlar y monitorizar zonas de climatización MySair desde Home Assistant:
- **Descubrimiento** de topología por HTTP: `Location → Installation (ctl) → Device (zona)`.
- **Estado en tiempo real** recibido por **MQTT sobre WebSocket** (AWS IoT).
- **Comandos** (temperatura, modo, encendido) enviados por **HTTP** a `POST /send/instruction` (NO por MQTT).

Dominio HA: `mysair`. Tipo: `hub`. `iot_class`: `cloud_push` (híbrido: push MQTT + refresco HTTP cada 60 s).

---

## 2. Arquitectura resumida

```
config_flow.py ──login──► api.py (MySairAPI, HTTP síncrono con requests)
__init__.py (async_setup_entry):
   login → get_locations → get_installations → get_devices
   → hass.data[DOMAIN][entry_id] = {api, devices, installations, mqtt}
   → MySairMQTTClient.start()  (hilo daemon, WSS a AWS IoT)
   → forward a plataformas: climate, sensor, switch
   → refresh_status_periodic()  (task, POST status cada 60 s)

MQTT (mqtt_handler.py) recibe .../status
   → mqtt_message_callback (en __init__.py) parsea t[] → zonas
   → hass.bus.async_fire("mysair_update", {topic, data})
   → cada entidad escucha, filtra por ctl+zone_id, actualiza estado

Comando de entidad → api.send_zone_command → POST /send/instruction (devuelve orderId)
   → backend reenvía al dispositivo → estado vuelve por MQTT (reconciliación)
   → ACK vuelve por MQTT en .../usr/{aws_mqtt_user}/feedback (orderId, ctl)
   → hass.bus.async_fire("mysair_feedback", {order_id, ctl, raw})
   → CommandFeedbackMixin (command_feedback.py, climate.py/switch.py) loguea
     confirmación, o aviso si no llega en FEEDBACK_TIMEOUT_SECONDS (5 s)
```

Detalle completo: `docs/architecture.md`. **Los comandos van por HTTP, el estado por MQTT.**

---

## 3. Comandos

Lint y CI todavía no están configurados. Tests, sí, en dos niveles:

```bash
# Tests P0/P1 (NO requieren Home Assistant, Python 3.9+, en la máquina local)
python -m venv .venv-test && source .venv-test/bin/activate
pip install -r requirements-test.txt
pytest                      # ~89 tests: parser, builders MQTT, firma SigV4, cliente HTTP
                             # (los ficheros P2 se saltan aquí vía pytest.importorskip)

# Tests P2 (harness de Home Assistant): vía Docker, no toca la máquina del desarrollador
docker compose run --rm test-ha    # 166 tests en total (P0/P1 + config flow + setup/unload + entidades + feedback + disponibilidad + fan_mode + refresco proactivo MQTT + revert optimista + parser MQTT estricto)

# Lint / formato (recomendado: ruff; aún no configurado en el repo)
ruff check custom_components/mysair tests
ruff format custom_components/mysair tests
```

- Los tests **puros** (parser, builders MQTT, firma SigV4, `MySairAPI` con `session` inyectada)
  corren sin HA porque `tests/conftest.py` añade `custom_components/mysair` a `sys.path` e importa
  esos módulos como top-level (no ejecutan el `__init__.py` del paquete).
- Los tests con **harness de HA** (`test_config_flow.py`, `test_init_setup_unload.py`,
  `test_entities.py`) requieren `homeassistant` + `pytest-homeassistant-custom-component`
  (Python ≥3.12), instalados solo dentro de `Dockerfile.test` — no en el entorno local. PyPI no
  publica `homeassistant` más reciente que `2025.1.4` (techo conocido del ecosistema, no de este
  repo). Ver `docs/testing-strategy.md`.

> ⚠️ **Nunca** ejecutes el código contra servidores reales de MySair para "probar".

---

## 4. Estructura de archivos

El código de la integración vive en `custom_components/mysair/` (layout estándar HA/HACS).
Los tests y la documentación están en la raíz del repo.

| Archivo (`custom_components/mysair/`) | Rol |
|---|---|
| `__init__.py` | Setup/unload, callback MQTT, refresco periódico. `async_unload_entry` a nivel de módulo |
| `api.py` | `MySairAPI`: HTTP síncrono (`requests`, `session` inyectable) + firma AWS SigV4 |
| `status_parser.py` | Parsers **puros** de `status` (`parse_status_payload`) y `feedback` (`parse_feedback_payload`), sin dependencia de HA |
| `mqtt_handler.py` | `MySairMQTTClient`: MQTT crudo sobre WebSocket (`websocket-client`) |
| `command_feedback.py` | `CommandFeedbackMixin`: correlación de comandos con el ACK de `mysair_feedback` (climate/switch) |
| `availability.py` | `AvailabilityMixin`: `should_poll=False` + `available` según frescura del último status MQTT (todas las entidades) |
| `climate.py` | `MySairThermostat` (ClimateEntity) |
| `sensor.py` | 4 sensores por zona (temp actual, consigna, modo, humedad) |
| `switch.py` | `MySairSwitch` (power on/off) |
| `config_flow.py` | Config flow (email + password) |
| `const.py` | Constantes (algunas sin uso: `HVAC_MODES` con `auto`, `SCAN_INTERVAL`) |
| `manifest.json` | Manifiesto (`requirements`: solo `requests` y `websocket-client`) |

| Raíz del repo | Rol |
|---|---|
| `tests/` | Tests P0/P1 (no requieren HA) + `conftest.py` con fixtures sanitizadas |
| `pytest.ini`, `requirements-test.txt` | Configuración y dependencias de test |
| `docs/` | Documentación de arquitectura, protocolos, dominio, tests, seguridad |
| `hacs.json` | Metadatos para instalar el repo como repositorio personalizado de HACS |
| `README.md` | Instalación, configuración, entidades, limitaciones (cara pública del proyecto) |
| `CHANGELOG.md` | Historial de versiones (Keep a Changelog + SemVer) |
| `LICENSE` | MIT |

> Nota: `select.py` fue **eliminado** en estabilización (código muerto/roto). Ver `docs/execution-plan.md`.

---

## 5. Convenciones de código (observadas)

- Cliente HTTP **síncrono** (`requests`) SIEMPRE invocado desde el loop vía `hass.async_add_executor_job(...)`. No introducir llamadas de red bloqueantes en el event loop.
- MQTT corre en **hilo daemon**; para volver al loop se usa `hass.loop.call_soon_threadsafe(...)`.
- Entidades se comunican con los datos vía el **event bus** (`mysair_update`), no directamente con el cliente MQTT.
- Handlers de evento decorados con `@callback`.
- Logs con prefijos `[MySair ...]` y emojis (estilo existente; mantener consistencia si editas cerca).
- Español en comentarios y mensajes de log.

---

## 6. Restricciones importantes (LEER antes de tocar nada)

1. **No hacer peticiones a producción.** No ejecutar `login`, `send_instruction`, ni conectar MQTT contra `api.mysair.es` / AWS IoT reales durante el desarrollo asistido.
2. **No cambiar el estado de una instalación real.** Los comandos (`mode`, `temp`, `power`) afectan hardware físico.
3. **Secretos:** no imprimir ni commitear `password`, `access_token`, `refresh_token`, `aws_secret_access_key`, `aws_security_token`, ni URLs firmadas. Ver `docs/security-and-privacy.md`.
4. **Protocolo no documentado:** no inventar campos ni endpoints. Marcar suposiciones con `# TODO(validar)` y consultar `docs/known-unknowns.md`.
5. **Codificación de modo sin confirmar** (comando `0/1` vs status `0/1/2`): NO cambiar la lógica de modo sin resolver `known-unknowns` #1/#2/#4.

---

## 7. Recetas de desarrollo

### Añadir una entidad (nueva plataforma)
1. Crear `nueva_plataforma.py` con `async_setup_entry(hass, entry, async_add_entities)`.
2. Leer `data = hass.data[DOMAIN][entry.entry_id]`; iterar `data["devices"]` (dict `inst_ref → [device,...]`).
3. En la entidad: `unique_id` estable `mysair_<tipo>_{inst_ref}_{device_id}`, `device_info` con `identifiers={(DOMAIN, f"{inst_ref}_{device_id}")}`.
4. Suscribir a `mysair_update` en `async_added_to_hass`; desuscribir en `async_will_remove_from_hass`.
5. En el handler `@callback`, filtrar `topic.endswith("/status")`, `data["ctl"]==inst_ref`, y `zone["zone_id"]==device_id`.
6. **Añadir la plataforma a `PLATFORMS` en `__init__.py:14`** (error común: olvidarlo, como pasó con `select`).

### Añadir un comando
1. En `api.MySairAPI.send_zone_command` (`api.py:236`) añadir un nuevo `command_type` construyendo el `value` adecuado.
2. La instrucción es `[{sender:"WEB", ctl, app, device, command, value}]` a `POST /send/instruction`.
3. Llamar desde la entidad con `await hass.async_add_executor_job(api.send_zone_command, inst_ref, device_id, tipo, ...)`.
4. Estado optimista opcional + reconciliación por MQTT. Documentar el `value` en `docs/mysair-http-api.md`.

### Añadir soporte para un mensaje MQTT
1. El parsing vive en `mqtt_message_callback` (`__init__.py`). Hoy procesa `.../status` (→ `mysair_update`) y `.../feedback` (→ `mysair_feedback`, ver `status_parser.parse_feedback_payload`).
2. Para un topic/tipo nuevo: añadir una rama según sufijo de topic, parsear y emitir en su propio evento (no reutilices `mysair_update`/`mysair_feedback` para algo distinto) con una estructura `data` normalizada.
3. Si hace falta suscribirse a un topic nuevo (no solo procesar uno que ya llega): añadir un `build_<algo>_topic()` puro en `mqtt_handler.py` y suscribir en el handler de CONNACK (ver `build_feedback_topic`/su uso como ejemplo).
4. Actualizar las entidades que deban consumirlo y documentar el topic/payload en `docs/mysair-mqtt-protocol.md`.
5. Recuerda: el frame se recibe en `mqtt_handler._on_message` — parsing frágil por `split`/`{...}`.

### Modificar la API HTTP
1. Todos los endpoints están en `api.py`. Añade el método siguiendo el patrón: header `Authorization: Bearer`, `timeout`, comprobación de `status_code`, extracción de `entity`.
2. Invócalo siempre desde el loop con `async_add_executor_job`.
3. Documenta el endpoint en `docs/mysair-http-api.md` con su nivel de certeza.

### Trabajar sin un dispositivo real
- Usa las **fixtures sanitizadas** de `docs/testing-strategy.md` (§5).
- Mockea `requests` (con `requests-mock`) y los frames MQTT (bytes construidos con los builders).
- Prueba las funciones puras: `encode_varint`, `build_mqtt_connect`, `build_mqtt_subscribe`, `aws_sign_url` (con reloj fijo), y el parser de status (tras extraerlo).

---

## 8. Checklist antes de MODIFICAR código

- [ ] ¿He leído la doc relevante en `docs/` (arquitectura + protocolo afectado)?
- [ ] ¿El cambio evita llamadas a producción y cambios de estado real?
- [ ] ¿Toca la codificación de modo? Si sí, ¿están resueltos `known-unknowns` #1/#2/#4?
- [ ] ¿Añade red bloqueante? Debe ir por `async_add_executor_job`.
- [ ] ¿Registra recursos (hilos, tasks, listeners)? Deben poder cancelarse en unload.
- [ ] ¿Introduce logs con secretos? No.

## 9. Checklist antes de un COMMIT

- [ ] Sin credenciales, tokens ni capturas reales en el diff.
- [ ] `ruff check` y `ruff format` limpios (si el entorno los tiene).
- [ ] Tests relevantes pasan (`pytest`), o se explica por qué no aplica.
- [ ] Documentación en `docs/` actualizada si cambió el protocolo o la arquitectura.
- [ ] Si añadiste plataforma: está en `PLATFORMS`.
- [ ] Mensaje de commit descriptivo.
- [ ] Rama distinta de `main` si se pedirá PR (no commitear en `main` sin permiso del usuario).

### Flujo de ramas (origin)

Solo existen `main` y `develop` en `origin`; no dejar ramas de feature huérfanas tras el merge.

1. Crear una rama de feature corta **desde `develop`** (nombre descriptivo, p. ej. `mqtt-robustness`).
2. Commits + PR **contra `develop`**; borrar la rama al fusionar (`gh pr merge --delete-branch` o equivalente).
3. `develop` se fusiona contra `main` **cuando el usuario lo pida o lo considere necesario** (release), no automáticamente en cada PR.

---

## 10. Enlaces a la documentación generada

- Arquitectura y diagramas: `docs/architecture.md`
- API HTTP: `docs/mysair-http-api.md`
- Protocolo MQTT: `docs/mysair-mqtt-protocol.md`
- Modelo de dominio: `docs/domain-model.md`
- Ciclo de vida en HA + evaluación: `docs/home-assistant-integration.md`
- Estrategia de tests + fixtures: `docs/testing-strategy.md`
- Seguridad y privacidad: `docs/security-and-privacy.md`
- Incógnitas abiertas: `docs/known-unknowns.md`
- Roadmap: `docs/development-roadmap.md`

---

## 11. Estado de bugs conocidos

Corregidos en el bloque de estabilización + A5 (rama `stabilization`):
- ✅ **Unload:** `async_unload_entry` a nivel de módulo con cierre limpio.
- ✅ **Tarea periódica:** cancelable (`async_create_background_task`), intervalo 120 s.
- ✅ **`select.py`:** eliminado.
- ✅ **Codificación de estado:** `e`=encendido, modo=paridad de `m` (antes se leía `e` como modo). Ver `docs/protocol-findings.md`.
- ✅ **`switch.turn_on`:** ya no fuerza frío; enciende con `mode` preservando el último modo (por defecto calor).
- ✅ **`requirements`:** solo `requests` + `websocket-client`.
- ✅ **`client_id` MQTT único** por conexión (#20; antes `aws_mqtt_user` → expulsiones con la app).
- ✅ **Refresco de credenciales AWS por `aws_expires_at`** en cada reconexión (#22; antes reutilizaba firma caducada).
- ✅ **Topic desde `aws_base_topic`** con fallback (#5); log de conexión ya no filtra la URL firmada.
- ✅ **Validado en producción** (2026-07-20) contra una cuenta real: descubrimiento, MQTT (client_id único sin expulsar la app oficial) y estado en tiempo real funcionan correctamente.
- ✅ **`password` ya no se guarda en claro** (A6): la config entry solo persiste `email` + `refresh_token`; la sesión se renueva en cada arranque con `MySairAPI.refresh_tokens()`. Migración automática elimina `password`/`access_token` de entradas antiguas en el primer arranque tras actualizar.
- ✅ **`unique_id`** en la config entry (C2): evita añadir la misma cuenta dos veces.
- ✅ **Reauth flow** (C3): `ConfigEntryAuthFailed`/`ConfigEntryNotReady` en `async_setup_entry` + `async_step_reauth` en `config_flow.py`. Camino de reauth no probado todavía en producción (ver `docs/execution-plan.md` Tarea 9).
- ✅ **Tests de `config_flow.py`/`__init__.py`** con harness real de HA (unique_id, reauth, `ConfigEntryAuthFailed`/`NotReady`, migración A6, unload) vía Docker (`docker compose run --rm test-ha`) — no requiere instalar nada en la máquina del desarrollador. Ver `docs/execution-plan.md` Tarea 12 y `docs/testing-strategy.md`.
- ✅ **Tests de entidades y eventos MQTT** (climate/sensor/switch reaccionando a `mysair_update`, comandos, filtro por `ctl`) — `tests/test_entities.py`, ver `docs/execution-plan.md` Tarea 13.
- ✅ **Sensor de humedad y disponibilidad real de heat/cool** (F1) + **min/max temp reales** (C8) — ver `docs/execution-plan.md` Tarea 15.
- ✅ **Confirmación de comandos vía topic `feedback`** (E7, parte 1): suscripción, evento `mysair_feedback`, log de confirmación/timeout por entidad. **Sin revertir estado todavía** — pendiente de validar el payload real en producción (#23). Ver `docs/execution-plan.md` Tarea 16.
- ✅ **`datetime.utcnow()` obsoleto** (C6, en la firma SigV4), **`FlowResult`→`ConfigFlowResult`** (C7), y **`should_poll=False` + `available` por frescura de MQTT** (C5, todas las entidades no disponibles hasta el primer status y de nuevo si no llega nada en 360 s). Ver `docs/execution-plan.md` Tarea 17.
- ✅ **Velocidad de ventilador** (F2): `climate.fan_mode`/`fan_modes`, comando `fanspeed`. Mapeo de `vv` confirmado en el JS (#24 resuelto — cuidado, una página de demo/storybook del mismo bundle tenía datos de ejemplo que parecían una pista pero no lo eran). Ver `docs/execution-plan.md` Tarea 18.
- ✅ **Dos bugs reales encontrados con una captura de producción** (2026-07-20, tras probar la Tarea 18): `mqtt_handler._on_message` clasificaba como `"unknown"` cualquier topic que no viniera envuelto en paréntesis — el topic de `feedback` llega sin ellos, así que la confirmación de comandos (Tarea 16) **nunca funcionó** pese a que el ACK sí llegaba. Y `status_parser` leía el campo de humedad como `hm` cuando el real es `hum` — el sensor de humedad (F1) **nunca mostró nada**. Ambos corregidos; #6 y #23 quedan resueltos de paso. Ver `docs/execution-plan.md` Tarea 19.
- ✅ **Causa raíz de las desconexiones MQTT "sistemáticas"** (2026-07-20): nunca refrescábamos la sesión MQTT *antes* de que caducaran las credenciales AWS, solo al reconectar después de que AWS ya la hubiera cortado — de ahí el patrón regular. Corregido con refresco proactivo (`api.seconds_until_aws_credentials_expire` + timer en `mqtt_handler`), igual que hace la app oficial. Además, el aviso de "sin confirmación MQTT" ahora distingue si fue por desconexión o con MQTT activo. **Verificado en producción**: el usuario confirma que las caídas ya no ocurren. Ver `docs/execution-plan.md` Tarea 20.
- ✅ **E7 completo:** si no llega confirmación de un comando a tiempo, se revierte el estado optimista (temperatura/modo/fan_mode/switch) al último valor conocido; se descarta el revert si llega un status real antes. Ver Tarea 21.
- ✅ **E1 (parser MQTT conforme al estándar, `known-unknowns` #6):** investigando el "carácter fantasma" antes del topic en los logs se encontró que era el byte bajo del campo de longitud MQTT estándar (confirmado por coincidencia exacta de longitud entre dos capturas reales), no un envoltorio de la app. `mqtt_handler.parse_mqtt_publish` decodifica el frame conforme al estándar como método primario, con la heurística de texto anterior como fallback si no es concluyente. Ver Tarea 21.

Pendientes:
- 🟡 **Parser de frame MQTT robusto** (#6): decodificar la cabecera MQTT real (longitud de topic, packet id) en vez de heurísticas de texto — sigue pendiente aunque el bug concreto del topic ya se corrigió.
- 🟡 **Reload, reintento tras 401 en comando, mensajes duplicados/fuera de orden** — sin cobertura todavía (menor, ver `docs/testing-strategy.md` §P2/P3 pendiente; los duplicados de `feedback` vistos en producción encajan aquí).

Decisiones de alcance (no son bugs):
- **Solo primera `Location`** (#15) — soportar varias `Location` queda deliberadamente fuera de alcance.
