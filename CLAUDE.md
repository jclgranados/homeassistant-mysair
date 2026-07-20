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

Comando de entidad → api.send_zone_command → POST /send/instruction
   → backend reenvía al dispositivo → estado vuelve por MQTT (reconciliación)
```

Detalle completo: `docs/architecture.md`. **Los comandos van por HTTP, el estado por MQTT.**

---

## 3. Comandos

Este repo **no tiene** entorno, tests, lint ni CI configurados todavía. Convenciones recomendadas (aún no presentes):

```bash
# Tests P0/P1 (NO requieren Home Assistant): se ejecutan tal cual
python -m venv .venv-test && source .venv-test/bin/activate
pip install -r requirements-test.txt
pytest                      # 42 tests: parser, builders MQTT, firma SigV4, cliente HTTP

# Lint / formato (recomendado: ruff; aún no configurado en el repo)
ruff check custom_components/mysair tests
ruff format custom_components/mysair tests
```

- Los tests **puros** (parser, builders MQTT, firma SigV4, `MySairAPI` con `session` inyectada)
  corren sin HA porque `tests/conftest.py` añade `custom_components/mysair` a `sys.path` e importa
  esos módulos como top-level (no ejecutan el `__init__.py` del paquete).
- Los tests con **harness de HA** (config flow, setup/unload, entidades) están pendientes:
  requieren `homeassistant` + `pytest-homeassistant-custom-component` (Python ≥3.12). Ver
  `docs/testing-strategy.md` y `docs/execution-plan.md`.

> ⚠️ **Nunca** ejecutes el código contra servidores reales de MySair para "probar".

---

## 4. Estructura de archivos

El código de la integración vive en `custom_components/mysair/` (layout estándar HA/HACS).
Los tests y la documentación están en la raíz del repo.

| Archivo (`custom_components/mysair/`) | Rol |
|---|---|
| `__init__.py` | Setup/unload, callback MQTT, refresco periódico. `async_unload_entry` a nivel de módulo |
| `api.py` | `MySairAPI`: HTTP síncrono (`requests`, `session` inyectable) + firma AWS SigV4 |
| `status_parser.py` | Parser **puro** del payload `status` (`parse_status_payload`), sin dependencia de HA |
| `mqtt_handler.py` | `MySairMQTTClient`: MQTT crudo sobre WebSocket (`websocket-client`) |
| `climate.py` | `MySairThermostat` (ClimateEntity) |
| `sensor.py` | 3 sensores por zona (temp actual, consigna, modo) |
| `switch.py` | `MySairSwitch` (power on/off) |
| `config_flow.py` | Config flow (email + password) |
| `const.py` | Constantes (algunas sin uso: `HVAC_MODES` con `auto`, `SCAN_INTERVAL`) |
| `manifest.json` | Manifiesto (`requirements`: solo `requests` y `websocket-client`) |

| Raíz del repo | Rol |
|---|---|
| `tests/` | Tests P0/P1 (no requieren HA) + `conftest.py` con fixtures sanitizadas |
| `pytest.ini`, `requirements-test.txt` | Configuración y dependencias de test |
| `docs/` | Documentación de arquitectura, protocolos, dominio, tests, seguridad |

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
1. El parsing vive en `mqtt_message_callback` (`__init__.py:67`). Hoy solo procesa `.../status` leyendo `payload["value"]` (string JSON) → `t[]`.
2. Para un topic/tipo nuevo: añadir una rama según sufijo de topic, parsear y emitir en `mysair_update` con una estructura `data` normalizada.
3. Actualizar las entidades que deban consumirlo y documentar el topic/payload en `docs/mysair-mqtt-protocol.md`.
4. Recuerda: el frame se recibe en `mqtt_handler._on_message` (`mqtt_handler.py:167`) — parsing frágil por `split`/`{...}`.

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

Pendientes (requieren validación, ver `docs/known-unknowns.md`):
- 🟠 **Reconexión MQTT reutiliza credenciales/firma caducadas** (`mqtt_handler.py`, refresca solo si `aws_credentials` es falsy) — #22.
- 🟠 **`password` en claro** en la config entry (`config_flow.py`) — A6.
- 🟠 **`client_id` compartido** con la app oficial → posibles expulsiones — #20.
