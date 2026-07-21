# Roadmap de desarrollo

> Propuesta, no implementación. Ordenada por fases; cada ítem indica severidad/valor y referencia de evidencia.
> Prioridad: 🔴 crítica · 🟠 alta · 🟡 media · 🟢 baja.

---

## Fase A — Estabilización (corregir lo que está roto)

| # | Tarea | Prio | Evidencia |
|---|---|---|---|
| A1 | **Arreglar unload:** mover `async_unload_entry` a nivel de módulo con firma estándar; cerrar MQTT, cancelar tarea periódica, `async_unload_platforms`, limpiar `hass.data`. Registrar update listener por separado (opcional). | ✅ Hecho | `__init__.py` |
| A2 | **Gestionar la tarea periódica:** guardarla en `hass.data`/`entry.async_create_background_task` y cancelarla en unload. Corregir intervalo/comentario (60 s vs "5 min"). | ✅ Hecho | `__init__.py` |
| A3 | **Eliminar o reescribir `select.py`** (no cargado y con bugs). Si se reescribe, alinearlo con el resto y añadirlo a `PLATFORMS`. | ✅ Hecho (eliminado) | — |
| A4 | **Limpiar `requirements`:** dejar `requests` y `websocket-client==1.8.0`; quitar `aiohttp`, `paho-mqtt`, `boto3`. Eliminar el preload de paho. | ✅ Hecho | `manifest.json` |
| A5 | **Resolver la codificación de modo** (bloqueante — ver `known-unknowns` #1,#2,#4) y arreglar `switch.async_turn_on` que enciende siempre en "frío". | ✅ Hecho | `status_parser.py`, `switch.py` |
| A6 | **No guardar `password` en claro / tokens no usados** (ver `security-and-privacy` §3). | ✅ Hecho | `config_flow.py`, `api.py`, `__init__.py` |
| A7 | **Refresco proactivo de credenciales AWS** en reconexión MQTT (hoy reutiliza firma caducada). | ✅ Hecho — reforzado (2026-07-20): además de refrescar al reconectar, ahora se refresca **antes de que la conexión se caiga**, como hace la app oficial (`setTimeout`). Causa raíz confirmada de desconexiones "sistemáticas" en producción. | `mqtt_handler.py`, `api.py` |

---

## Fase B — Tests (red mockeada, sin dispositivo)

| # | Tarea | Prio |
|---|---|---|
| B1 | Refactor de testabilidad: extraer `parse_status_payload`, inyectar `requests.Session`. | ✅ Hecho |
| B2 | Añadir `pytest` + `pytest-homeassistant-custom-component` + fixtures sanitizadas (`docs/testing-strategy.md`). | ✅ Hecho |
| B3 | Tests P0/P1 (funciones puras, HTTP, config flow). | ✅ Hecho |
| B4 | Tests P2/P3 (MQTT, entidades, unload/reload) tras Fase A. | 🟠 P2 hecho (config flow, setup/unload, entidades); P3 (robustez MQTT: reconexión, duplicados, frames partidos) pendiente. |
| B5 | CI GitHub Actions: `hassfest`, `pytest` (P0/P1 + P2 vía Docker). | ✅ Hecho (`ruff` queda fuera: no configurado en el repo todavía) |

---

## Fase C — Modernización para Home Assistant

| # | Tarea | Prio |
|---|---|---|
| C1 | Introducir un **almacén central / coordinador** de estado por zona en vez del fan-out por event bus. | ✅ Hecho (2026-07-21) — `coordinator.py`: `MySairCoordinator` escucha `mysair_update` una sola vez por config entry y redistribuye cada zona por separado vía `homeassistant.helpers.dispatcher`; las 6 entidades por zona ya no repiten el filtrado de topic/ctl/zone_id. Sin cambio de comportamiento observable. |
| C2 | Añadir `unique_id` a la config entry (`async_set_unique_id`) para evitar duplicados. | ✅ Hecho |
| C3 | **Reauth flow** (`async_step_reauth`) y uso de `ConfigEntryAuthFailed`/`ConfigEntryNotReady`. | ✅ Hecho |
| C4 | `translations/` + `strings.json` (config flow, servicios). | ✅ Hecho — `strings.json` (inglés, referencia/fallback) + `translations/es.json`; cubre pasos del config flow (`user`/`reauth_confirm`), errores, abort reasons y el servicio `mysair.stop_installation`. **Alcance deliberado:** no incluye nombres de entidad (`climate`/`sensor`/`switch` siguen con nombres hardcodeados en español) — eso requeriría migrar a `has_entity_name`/`translation_key`, un cambio de mayor alcance que cambiaría el nombre visible de entidades ya instaladas; queda fuera de esta tarea. |
| C5 | `_attr_should_poll = False` explícito; `available` basado en frescura de datos MQTT. | ✅ Hecho |
| C6 | Sustituir `datetime.utcnow()` por `datetime.now(timezone.utc)` en la firma SigV4. | ✅ Hecho |
| C7 | Revisar `FlowResult`→`ConfigFlowResult` y otras deprecaciones de la versión objetivo. | ✅ Hecho |
| C8 | Aplicar `tmm`/`tmx` reales a `min_temp`/`max_temp` de climate. | ✅ Hecho |

---

## Fase D — Observabilidad

| # | Tarea | Prio |
|---|---|---|
| D1 | `diagnostics.py` con `async_redact_data` (sin exponer credenciales). | ✅ Hecho — vuelca entry data, instalaciones, devices, sesión API y estado del cliente MQTT; redacta tokens/credenciales (email, password, refresh/access token, credenciales AWS). |
| D2 | Redacción de logs sensibles (URL firmada, tokens) y niveles coherentes (INFO→DEBUG). | ✅ Hecho (2026-07-21) — `_truncate()` en `api.py` (cuerpos de error HTTP), `_redact_client_id()` en `mqtt_handler.py` (enmascara el `aws_access_key_id` embebido en el `client_id`), logs de alta frecuencia bajados a DEBUG. |
| D3 | Sensor/atributo de estado de conexión MQTT (online/offline) y última actualización. | ✅ Hecho (2026-07-21) — `MySairMqttStatusSensor` (`sensor.py`), una entidad por config entry. |
| D4 | Métricas de reconexión y errores de parsing para depuración. | ✅ Hecho (2026-07-21) — mismo sensor: `total_reconnects`, `parse_strict_count`/`parse_fallback_count`/`parse_error_count`, `last_close_code`; también en `diagnostics.py`. |

---

## Fase E — Robustez del protocolo

| # | Tarea | Prio |
|---|---|---|
| E1 | Parser MQTT robusto: decodificar la cabecera MQTT real (longitud de topic, packet id) en vez de `split`/`{...}`. | ✅ Hecho (`known-unknowns` #6 resuelto) — usado como método primario con fallback a la heurística anterior si no es concluyente. |
| E2 | Manejo de frames parciales / múltiples paquetes por frame WS. | 🟡 |
| E3 | Backoff exponencial con jitter en reconexión (hoy fijo 10 s). | ✅ Hecho — `compute_backoff_delay` (base 10 s, tope 120 s, jitter ±20%); se resetea el contador de intentos al reconectar (CONNACK) y los reconectes planificados (refresco de credenciales) siguen sin espera. |
| E4 | Validación de esquema de payloads (rechazar/loguear los inesperados). | 🟡 |
| E5 | Evaluar `client_id` propio distinto del de la app oficial para evitar expulsiones (`known-unknowns` #20). | ✅ Hecho |
| E6 | Evaluar migrar a `paho-mqtt` sobre WebSocket con SigV4, reduciendo código artesanal. Nota: se eliminó de `requirements` en A4 por no usarse; volver a añadirlo si se retoma esta tarea. | 🟡 |
| E7 | Reconciliación de estado optimista con timeout (revertir si no llega confirmación MQTT). | ✅ Hecho — suscripción a `feedback`, correlación por `orderId`, y revert del estado optimista (temperatura/modo/fan_mode/switch) si no llega confirmación a tiempo; se descarta si llega un status real antes. |

---

## Fase F — Nuevas funcionalidades

| # | Tarea | Prio |
|---|---|---|
| F1 | Sensor de humedad (`hm`) y disponibilidad real de heat/cool en `climate.hvac_modes` según capacidades (`c`/`f`). | ✅ Hecho |
| F2 | Exponer velocidad de ventilador (`fanspeed`/`vv`). Desbloqueado: mapeo confirmado en el componente real de la app (`known-unknowns` #24, `protocol-findings.md §9`) — `vv`: `"0"`=sin modo, `"1"/"2"/"3"`=manual, `"4"`=auto. | ✅ Hecho |
| F3 | Modo `auto` si el sistema lo soporta (hoy `const.HVAC_MODES` lo lista pero climate no). | 🟢 |
| F4 | `select` de modo reescrito y funcional. | 🟢 |
| F5 | Servicios propios: `mysair.stop_installation` (comando `stop`, ya documentado, `value:"1"`) si aporta valor sobre apagar zona por zona. | ✅ Hecho — `api.send_installation_command(ctl, "stop"/"status")`; servicio registrado una vez por dominio (compartido entre config entries) y retirado al descargar la última. |
| F6 | Temporizador (`temporizer`) y programas (`programs`) — mucho más trabajo (entidades nuevas fuera de climate/sensor/switch) y valores de parámetros sin confirmar. Más especulativo de la lista. | 🟢 |

---

## Fase G — Publicación y mantenimiento

| # | Tarea | Prio |
|---|---|---|
| G1 | `hacs.json` + estructura `custom_components/mysair/` para instalación vía HACS. | ✅ Hecho |
| G2 | README completo: instalación, configuración, limitaciones, aviso de "no oficial". | ✅ Hecho |
| G3 | Versionado semántico y CHANGELOG. | ✅ Hecho |
| G4 | Ajustar/retirar `quality_scale` hasta cumplir requisitos. | ✅ Hecho (retirado) |
| G5 | Ampliar `.gitignore` (`.env`, `*.har`, capturas). | ✅ Hecho |

---

## Secuencia recomendada de arranque

~~A1 → A2 → A4 → A3 (estabilizar y limpiar) → A5/A6/A7 (requiere validación de protocolo) → B1–B3 (red de seguridad de tests)~~ — Fases A y B completas. `docs/known-unknowns.md` #6 (formato de frame MQTT, bloqueaba E1/E2) ya está resuelto — ninguna fila de esa tabla sigue marcada con riesgo 🔴 a día de hoy.

**Estado real (2026-07-21):** Fases A, B, C, D (D1-D4), G completas. Quedan: E2, E4, E6 (robustez); F3, F4, F6.
