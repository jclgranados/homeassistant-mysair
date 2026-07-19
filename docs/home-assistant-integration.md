# Integración con Home Assistant — ciclo de vida y evaluación

> Cada observación se clasifica como: ✅ **Correcto** · 🟡 **Mejorable** · 🟠 **Potencialmente obsoleto** · 🔴 **Posible bug** · 🔎 **Requiere investigación**.

---

## 1. Manifest y metadatos

`manifest.json` (Confirmado):

| Campo | Valor | Evaluación |
|---|---|---|
| `domain` | `mysair` | ✅ |
| `config_flow` | `true` | ✅ |
| `iot_class` | `cloud_push` | 🟡 híbrido (push MQTT + poll HTTP 60 s) |
| `integration_type` | `hub` | ✅ razonable |
| `dependencies` | `[]` | ✅ |
| `requirements` | `aiohttp`, `paho-mqtt`, `requests`, `boto3`, `websocket-client` | 🔴 `aiohttp`, `paho-mqtt`, `boto3` **no se usan**; solo `requests` y `websocket-client` |
| `quality_scale` | `silver` | 🔴 no cumple silver (sin tests, sin translations, unload roto) |
| `homeassistant` | `2025.10.0` | 🟡 clave `homeassistant` mínima válida, pero ver §11 |
| `version` | `1.0.0` | ✅ (requerido para custom) |

**Recomendación:** dejar en `requirements` solo `requests` y `websocket-client==1.8.0`; bajar `quality_scale` o retirarlo hasta cumplirlo.

---

## 2. Config flow / options flow / credenciales

`config_flow.py` (Confirmado):
- Un solo paso `async_step_user` con `email` + `password`. ✅ estructura básica.
- Login en executor (`async_add_executor_job(api.login)`). ✅ no bloquea el loop.
- Manejo de errores: `invalid_auth` / `cannot_connect`. ✅ básico.

Problemas:
- 🔴 **Guarda `password` en claro** en `entry.data`, además de `access_token`/`refresh_token` que **nunca se reutilizan** (`config_flow.py:46-54`). Los tokens caducan y son ruido; la contraseña se necesita porque el setup hace login nuevo cada vez.
- 🔴 **No llama a `async_set_unique_id`** → permite entradas duplicadas de la misma cuenta.
- 🟡 **Sin options flow** (no hay ajustes: intervalo de refresco, selección de ubicación, etc.).
- 🟡 **Sin reauth flow** (`async_step_reauth`) → si la contraseña cambia, hay que borrar y re-añadir.
- 🟠 `FlowResult` importado de `homeassistant.data_entry_flow` (`config_flow.py:6`) — tipo válido pero el patrón moderno usa `ConfigFlowResult`. 🔎 verificar en la versión objetivo.

---

## 3. Setup / unload / reload

`async_setup_entry` (`__init__.py:17-188`) — flujo en §Arquitectura.

### 🔴 Bug crítico de unload
- `async_unload_entry` está **definida como función anidada** dentro de `async_setup_entry` (`__init__.py:174`) y se registra con **`entry.add_update_listener(...)`** (`__init__.py:187`).
- `add_update_listener` registra un **update listener** (invocado cuando la entrada se *actualiza*), **no** un manejador de descarga. HA busca un `async_unload_entry(hass, entry)` a **nivel de módulo** para descargar.
- **Consecuencia (Confirmado por semántica de HA):**
  - Al **descargar/recargar** la integración **no** se ejecuta el cierre real → el hilo MQTT, la tarea periódica y la sesión quedan **huérfanos** (fuga de recursos).
  - Como *update listener*, esta función llama a `async_unload_platforms` y hace `hass.data.pop`, lo que ante cualquier update de la entrada **rompería** el estado.
- **Recomendación:** mover `async_unload_entry` a nivel de módulo con firma estándar y `return await hass.config_entries.async_unload_platforms(...)`; registrar el update listener por separado (si se quiere reload).

### 🔴 Tarea periódica huérfana
- `refresh_status_periodic` se lanza con `hass.loop.create_task(...)` (`__init__.py:171`) y **nunca se guarda ni se cancela**. Al recargar → múltiples tareas acumuladas enviando `status`. 🔴 fuga + duplicación. Debería usarse `entry.async_create_background_task` y cancelarse en unload.
- 🔴 Comentario dice "5 minutos" pero `asyncio.sleep(60)` = **1 minuto** (`__init__.py:168`).

### 🟡 Preload de paho innecesario
- `__init__.py:22` precarga `paho.mqtt.client` en executor "fuera del loop", pero **paho no se usa** en ningún sitio → import muerto que además obliga a la dependencia.

---

## 4. Coordinador / actualización de datos

- 🟠 **No usa `DataUpdateCoordinator`.** Implementa un patrón push manual: hilo MQTT → callback → `hass.bus.async_fire("mysair_update")` → cada entidad escucha y filtra.
- **Evaluación:** funcional pero **no idiomático**. Problemas:
  - 🟡 Fan-out O(nº entidades) por mensaje: cada `status` despierta a *todas* las entidades, que filtran por `ctl`/`zone_id`.
  - 🟡 Sin estado centralizado → cada entidad guarda su propia copia; difícil de diagnosticar.
  - 🟡 No hay `available`/disponibilidad basada en frescura de datos.
- **Recomendación:** introducir un coordinador (o un almacén central en `hass.data`) que mantenga el último estado por zona y notifique a las entidades vía `async_dispatcher_send`/callbacks del coordinador.

---

## 5. Entidades

Comunes a climate/sensor/switch (Confirmado):
- ✅ `unique_id` presente y estable.
- ✅ `device_info` con `identifiers` consistentes → agrupan bien por zona.
- ✅ Uso de `@callback` en handlers de evento.
- ✅ `async_added_to_hass`/`async_will_remove_from_hass` suscriben/desuscriben correctamente del bus.
- 🟡 **Sin `available`** → las entidades nunca aparecen como "no disponible" aunque MQTT esté caído.
- 🟡 **Sin `should_poll = False` explícito** (climate/sensor/switch). Por defecto `SensorEntity`/`ClimateEntity` tienen `should_poll=True` salvo que se declare lo contrario → HA podría intentar `update()` (inexistente) periódicamente. 🔎 verificar impacto; recomendable `_attr_should_poll = False`.
- 🟡 `sw_version="v1.0"` hardcodeado; `model` difiere entre plataformas (`"Zonificador de aire"` vs `select.py` `"WiFi Thermostat"`). Inconsistencia cosmética.

### climate.py específico
- ✅ `supported_features`: `TARGET_TEMPERATURE | TURN_ON | TURN_OFF`.
- ✅ `hvac_modes`: OFF/HEAT/COOL.
- 🔴 **`min_temp`/`max_temp` fijos (10/30)** ignorando `tmm`/`tmx` del dispositivo (`climate.py:43-44`).
- 🔴 `async_set_temperature` con modo OFF **no envía comando** pero cambia consigna local (`climate.py:103-106`) → puede divergir del real.
- 🟠 Con `TURN_ON`/`TURN_OFF` en features y HA moderno se requiere que `hvac_modes` y `turn_on/off` sean coherentes; `async_turn_on` reusa último modo o HEAT (`climate.py:167-169`). ✅ aceptable.

### switch.py específico
- 🔴 **`async_turn_on` envía `mode="1"` (= frío según `send_zone_command`)** (`switch.py:64`). "Encender" siempre pone la zona en **frío**, ignorando el modo previo. Probable bug de semántica.

### sensor.py específico
- ✅ device_class TEMPERATURE en temp/consigna.
- 🟡 `MySairModeSensor` sin `device_class`/`options`; devuelve strings libres `OFF/HEAT/COOL`. Podría ser `SensorDeviceClass.ENUM`.

### select.py — 🔴 CÓDIGO ROTO / MUERTO
- **No está en `PLATFORMS`** (`__init__.py:14`) → nunca se carga. Confirmado.
- Aunque se cargara, tiene bugs que impiden funcionar:
  - `await api.get_locations()` — `get_locations` es **síncrono** (`requests`), no awaitable → `TypeError` (`select.py:21`).
  - Itera `locations["entity"]` pero `get_locations` ya devuelve la lista `entity` → doble desreferencia rota (`select.py:22`).
  - `self._api.aws_data` — atributo **inexistente** (es `aws_credentials`) (`select.py:68`).
  - `print(...)` en vez de logger (`select.py:31`).
- **Recomendación:** eliminar `select.py` o reescribirlo alineado con el resto (y sumarlo a `PLATFORMS`) — ver roadmap.

---

## 6. Servicios / diagnostics / repairs / translations

| Elemento | Estado | Evaluación |
|---|---|---|
| Servicios propios (`services.yaml`) | ❌ ninguno | 🟡 aceptable (todo vía entidades) |
| `diagnostics.py` | ❌ ausente | 🟡 recomendable para depurar sin exponer secretos |
| Repairs | ❌ ausente | 🟢 opcional |
| `translations/` + `strings.json` | ❌ ausentes | 🔴 requerido para quality_scale; el config flow no está traducido |

---

## 7. Errores, excepciones y autenticación expirada

- ✅ `send_instruction` maneja `401` con refresh + reintento único (`api.py:205-213`).
- 🟡 El resto de llamadas HTTP no manejan expiración; `get_*` devuelven `[]` ante cualquier error → un token caducado en el arranque se ve como "sin datos" y `setup` devuelve `False` sin `ConfigEntryAuthFailed`.
- 🔴 **No se usa `ConfigEntryAuthFailed`/`ConfigEntryNotReady`.** Si el login falla en setup se propaga una `Exception` genérica (o `return False`) en vez de las excepciones idiomáticas que disparan reautenticación/reintento. 🔎 verificar comportamiento exacto de HA ante `return False`.
- 🟡 Handlers de entidad tragan excepciones y solo loguean (`climate.py:118`, `switch.py:69`) → el usuario no ve fallo del comando.

---

## 8. Polling vs push / shutdown

- **Push:** MQTT → event bus. ✅ concepto correcto.
- **Poll oculto:** refresco HTTP cada 60 s (provoca push). 🟡 no declarado como polling de HA.
- **Shutdown:** 🔴 roto (ver §3). No hay registro de `EVENT_HOMEASSISTANT_STOP` para cerrar el WS; depende del unload roto.

---

## 9. Almacenamiento de estado

- Estado en memoria: `hass.data[DOMAIN][entry_id]` con `api`, `devices`, `installations`, `mqtt`. **Confirmado**.
- ✅ No usa `Store`/persistencia propia (no necesaria).
- 🟡 El estado de las entidades **no se restaura** tras reinicio hasta el primer `status` MQTT (sin `RestoreEntity`).

---

## 10. Concurrencia loop vs hilos

- ✅ MQTT en hilo daemon; el callback usa `hass.loop.call_soon_threadsafe(...)` para volver al loop (`__init__.py:116`). Correcto cruce hilo→loop.
- ✅ HTTP síncrono siempre vía `async_add_executor_job`.
- 🔎 `refresh_status_periodic` corre en el loop y llama a `async_add_executor_job` en cada iteración — correcto, pero sin manejo de cancelación.

---

## 11. Compatibilidad con Home Assistant moderno

| Aspecto | Riesgo | Certeza |
|---|---|---|
| `datetime.utcnow()` en firma AWS (`api.py:294`) | Obsoleto en Python 3.12+ (usado por HA reciente); genera DeprecationWarning, no fallo inmediato | Confirmado |
| `add_update_listener` usado como unload | Rompe unload/reload en cualquier versión | 🔴 Confirmado |
| `should_poll` no desactivado | Posibles updates espurios | 🔎 |
| `FlowResult` vs `ConfigFlowResult` | Renombrado en versiones recientes; import antiguo puede quedar deprecado | 🔎 |
| Requirements con libs no usadas | HA instala deps innecesarias (boto3 es pesado) | Confirmado |
| Sin `strings.json` | Warnings de traducción; incumple requisitos de calidad | Confirmado |
| Bloqueo de import en setup (`__import__` paho) | Innecesario, pero se hace en executor (no bloquea) | Confirmado |

---

## 12. Resumen de acciones prioritarias (integración HA)

1. 🔴 Corregir `async_unload_entry` (nivel módulo, firma estándar) y cierre de recursos.
2. 🔴 Gestionar la tarea periódica (guardar + cancelar; corregir intervalo/comentario).
3. 🔴 Eliminar o arreglar `select.py`.
4. 🔴 Depurar `requirements` (quitar aiohttp/paho/boto3) y el preload de paho.
5. 🟡 Añadir `unique_id` en config entry, reauth y disponibilidad de entidades.
6. 🟡 Introducir coordinador/almacén central y `strings.json`/translations.

Detalle de severidad y evidencia en `docs/` (fase 7 del análisis) y `docs/development-roadmap.md`.
