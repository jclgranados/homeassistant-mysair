# Changelog

Todos los cambios notables de este proyecto se documentan en este fichero.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y este proyecto se adhiere a [Semantic Versioning](https://semver.org/lang/es/): `MAJOR.MINOR.PATCH`, donde `MAJOR` indica cambios incompatibles (p. ej. ruta de instalación, esquema de la config entry o comportamiento observable), `MINOR` añade funcionalidad compatible hacia atrás, y `PATCH` corrige bugs sin cambiar comportamiento esperado.

## [Unreleased]

## [2.13.1] - 2026-09-12

### Fixed
- **El asistente de configuración estaba sin traducir en inglés.** Home Assistant no lee `strings.json` en tiempo de ejecución para integraciones custom: solo carga `translations/<idioma>.json`. Había `es.json` pero no `en.json`, así que cualquiera con HA en inglés (el idioma por defecto) veía claves crudas como `invalid_auth` en el login, en la reautenticación y en el servicio `mysair.stop_installation`.
- `climate.turn_on` en una zona que solo enfría no hacía nada: elegía siempre calor sin mirar las capacidades de la zona, y el propio guard de la entidad lo rechazaba en silencio. Ahora prefiere calor pero cae al primer modo que la zona admita.

### Changed
- `PERCENTAGE` pasa a `UnitOfRatio.PERCENTAGE` en el sensor de humedad, desaconsejado como unidad desde HA 2026.7. Mismo valor, sin cambio de comportamiento.
- CI: nuevo job de validación de HACS, que antes solo cubría `hassfest`.

## [2.13.0] - 2026-09-12

### Changed
- **Nombres de entidad y dispositivo, adaptados al esquema de Home Assistant 2026.** HA compone ahora el `entity_id` como área + dispositivo + entidad. Sin adaptarse, una instalación nueva habría creado `climate.dev_1_inst_a_salon` en vez de `climate.salon`. Las entidades pasan a usar `has_entity_name`: el dispositivo toma el nombre de la zona ("Salón" en vez de "DEV_1 (INST_A)") y cada entidad aporta solo su parte ("Temperatura actual", "Humedad", "Encendido", "Suelo radiante").
  - **Quien ya tenga la integración instalada no pierde nada**: el registro de entidades conserva los `entity_id` existentes mientras el `unique_id` no cambie, así que automatizaciones y paneles siguen funcionando. Hay un test que lo garantiza.
  - En **instalaciones nuevas**, los dos switches cambian de nombre respecto al esquema anterior: `switch.<zona>` pasa a `switch.<zona>_encendido` y `switch.<zona>_suelo` a `switch.<zona>_suelo_radiante`. El resto de entidades mantiene el mismo identificador de siempre.
  - El dispositivo de cuenta pasa a llamarse "MySair" en vez de "MySair (cuenta)", y su sensor "Conexión MQTT".
- Requisito mínimo de Home Assistant: **2026.8.0** (antes 2025.10.0), alineado con la versión contra la que se prueba.
- El harness de test sube de Home Assistant 2025.1.4 a 2026.9 (y con él Python 3.12 → 3.14). Se había quedado 20 versiones por detrás de lo que se ejecuta en producción, así que las deprecaciones pasaban desapercibidas.

### Fixed
- Limpieza de dispositivos huérfanos: se sustituye `async_update_device(remove_config_entry_id=...)`, deprecado desde HA 2026.8 (un dispositivo pertenece ya a una sola config entry) y con eliminación prevista en 2027.8, por `async_remove_device`. Escribía un aviso de deprecación en el log en cada arranque.

### Removed
- El bloque `device_info`, duplicado palabra por palabra en las 7 entidades de cada zona, se unifica en `device.py`.

## [2.12.0] - 2026-09-12

### Fixed
- **Una sesión caducada ya no obliga a desinstalar la integración.** MySair corre sobre Laravel Passport, que responde `404` (no `401`) cuando el `refresh_token` ya no existe en servidor, con el cuerpo `No query results for model [Laravel\Passport\RefreshToken]`. Ese 404 se clasificaba como error de conexión, se convertía en `ConfigEntryNotReady` y Home Assistant reintentaba el arranque en bucle (`setup_retry`) sin ofrecer nunca el botón de reautenticar. Ahora la clasificación es por rango: `5xx` y `429` son fallos transitorios (reintentar), y cualquier otro código no-2xx en un endpoint de sesión pide reautenticación.
- `get_locations()`, `get_installations()` y `get_devices()` dejan de devolver `[]` ante cualquier error. Una sesión muerta se leía como "cuenta vacía" y acababa también en un bucle de reintentos; una lista vacía ya solo significa que la cuenta no tiene datos.
- `refresh_aws_credentials()` reintenta una vez tras renovar la sesión ante un `401`, como ya hacía `send_instruction()`. Antes dependía de que la tarea periódica refrescara el token por su cuenta.

### Added
- **Reautenticación en caliente.** Si la sesión muere con la integración ya arrancada (cierre de sesión desde la app oficial, cambio de contraseña, limpieza de tokens en servidor), el hilo MQTT y la tarea periódica de estado piden el flujo de reauth al momento en vez de reintentar en silencio hasta el siguiente reinicio de Home Assistant. El hilo MQTT sigue reintentando en degradado y avisa una sola vez; al reconectar con éxito rearma el aviso.
- El flujo de reauth comprueba que la cuenta no cambia (`account_mismatch`), con su cadena traducida al inglés y al español.
## [2.11.2] - 2026-07-21

### Added
- Limpieza automática de entidades huérfanas: si una zona desaparece de la cuenta MySair entre un arranque/recarga y otro, su dispositivo y todas sus entidades (termostato, sensores, switches) se eliminan del registro de Home Assistant en vez de quedarse huérfanos para siempre.

## [2.11.1] - 2026-07-21

### Added
- `ruff` (lint + formato) configurado y añadido a CI como un 4º job independiente (`pyproject.toml`, `requirements-lint.txt`).
- 3 tests nuevos sin necesitar una captura real de producción: reload de la config entry (sin duplicar entidades ni el servicio compartido), varias instalaciones en una misma cuenta, y cambio de topología (documenta que una zona eliminada queda huérfana en el registro de entidades, sin limpieza automática).

### Fixed
- Eliminados 3 imports y 1 variable local sin usar (`api.py`, `config_flow.py`, `mqtt_handler.py`), sin cambio de comportamiento.

## [2.11.0] - 2026-07-21

### Added
- Icono y logo de marca (`custom_components/mysair/brand/`), usando el mecanismo local de Home Assistant ≥2026.3.0 (sin PR externo a `home-assistant/brands`). Se muestran automáticamente en la UI de HA para quien tenga esa versión o superior.
- `manifest.json` vuelve a declarar `quality_scale: "silver"` — pendiente de confirmar si `hassfest` lo acepta para una integración custom.

## [2.10.2] - 2026-07-21

### Added
- Nuevo atributo `medio` en `sensor.<zona>_modo`: indica si la zona está usando aire acondicionado (`ac`), suelo radiante (`suelo`) o ambos combinados (`mixto`), en un solo valor en vez de tener que combinar `climate.<zona>` y `switch.<zona>_suelo` manualmente. Se conserva aunque la zona esté apagada.

## [2.10.1] - 2026-07-21

### Changed
- El `model` del dispositivo (mostrado en la página de dispositivo de Home Assistant) pasa de `"Zonificador de aire"` a `"Zonificador de climatización"` en climate/sensor/switch, para reflejar que también controla suelo radiante, no solo aire acondicionado. Cambio cosmético, sin efecto en `unique_id` ni en el emparejamiento de entidades.

## [2.10.0] - 2026-07-21

### Added
- Control de suelo radiante por zona: nuevo switch (uno por zona con esa capacidad) para encender/apagar el suelo, independiente del switch de encendido general. Reutiliza el comando `mode` ya existente (recalcula el valor internamente preservando el modo calor/frío y el estado de AC actuales) — no requiere ningún comando nuevo del backend. La entidad aparece como "no disponible" en zonas sin capacidad de suelo.

### Removed
- `const.HVAC_MODES` (incluía un modo `"auto"` sin ningún soporte real en el sistema ni consumidor en el código — código muerto).

### Evaluado (sin cambios de código)
- Temporizador y programas por horario: no se implementan. El backend no expone ninguna forma confirmada de fijarlos (solo de leerlos), y adivinar el formato no es una opción responsable. Se retomará si en el futuro aparece evidencia real (p. ej. una captura de una instalación con temporizador configurado).

## [2.9.0] - 2026-07-21

### Added
- Reensamblado de frames MQTT (E2): el cliente ya no asume que cada mensaje WebSocket contiene exactamente un paquete MQTT completo. Ahora acumula los bytes recibidos y despacha tantos paquetes completos como haya (varios PUBLISH/CONNACK/SUBACK coalescidos en un mismo mensaje WS), y reensambla correctamente un paquete partido entre dos mensajes WS. Un cap defensivo descarta el buffer si crece sin completar un paquete o si una longitud declarada es absurda.
- Validación de payloads (E4): `status_parser.py` rechaza explícitamente (y loguea) un payload que no es ni siquiera un dict, en vez de producir un evento vacío sin sentido; se loguean (antes en silencio) los casos de `ctl` ausente, campo `t` con forma inesperada, y zonas sin identificador (`rf`). Deliberadamente no se rechazan claves adicionales desconocidas del payload (permisivo ante campos nuevos del backend).
- E6 (evaluar migrar a `paho-mqtt`): documentada la decisión de no migrar — ver `docs/development-roadmap.md`.

### Fixed
- Un campo `t` (zonas) con una forma inesperada que no fuera una lista (p. ej. un número) provocaba un `TypeError` sin capturar que descartaba el mensaje MQTT entero con un error genérico; ahora se degrada de forma segura con un aviso específico en logs.

## [2.8.0] - 2026-07-21

### Added
- Sensor `MySair Conexión MQTT` (uno por cuenta configurada): estado online/offline de la conexión MQTT, hora de la última actualización recibida, y métricas de reconexión/parseo (intentos de reconexión, reconexiones totales, mensajes decodificados por el método estricto/heurístico, mensajes que no se pudieron parsear, código del último cierre de conexión) (D3/D4).
- `diagnostics.py` incluye ahora las mismas métricas de conexión/parseo.

### Changed
- Redacción de logs (D2): los cuerpos de respuesta HTTP de error se truncan antes de loguearse (evita que un cuerpo inesperado del backend filtre más de lo necesario), y el `clientId` MQTT enmascara el `access_key` de AWS que lleva embebido. Varios logs de alta frecuencia (un mensaje MQTT recibido, un comando enviado, una confirmación de comando) bajan de `INFO` a `DEBUG`; se mantienen en `INFO` los eventos de ciclo de vida (login, conexión/desconexión MQTT, arranque).

## [2.7.1] - 2026-07-21

### Changed
- Refactor interno: un único `MySairCoordinator` por config entry ahora escucha `mysair_update` una sola vez y redistribuye cada zona por separado (`homeassistant.helpers.dispatcher`) a la entidad correspondiente, en vez de que las 6 entidades por zona (climate/sensor/switch) repitan cada una el mismo filtrado de topic/instalación/zona sobre el bus. Sin cambio de comportamiento observable.

## [2.7.0] - 2026-07-20

### Added
- Traducción del asistente de configuración (login, reautenticación, errores) y del servicio `mysair.stop_installation`: inglés por defecto (`strings.json`) y español (`translations/es.json`). Los nombres de las entidades (climate/sensor/switch) siguen en español, sin cambios.

## [2.6.0] - 2026-07-20

### Added
- Servicio `mysair.stop_installation`: detiene una instalación completa (todas sus zonas) con un solo comando, en vez de apagar zona por zona.
- `diagnostics.py`: volcado descargable desde la UI de Home Assistant con el estado de la integración (instalaciones, dispositivos, estado del cliente MQTT) para depuración, redactando credenciales y tokens.
- Backoff exponencial con jitter en la reconexión MQTT (antes una espera fija de 10 s); los reconectes planificados por refresco de credenciales siguen sin esperar.

## [2.5.0] - 2026-07-20

### Added
- Si un comando (temperatura, modo, ventilador, encendido/apagado) no se confirma por MQTT a tiempo, se revierte el estado optimista al último valor conocido en vez de quedarse mostrando algo que quizá no llegó a aplicarse.
- Parser de frames MQTT conforme al estándar (topic decodificado desde la cabecera real en vez de heurísticas de texto), con la heurística anterior como respaldo si el frame no tiene la forma esperada.

## [2.4.2] - 2026-07-20

### Fixed
- Causa raíz de las desconexiones MQTT periódicas: la sesión nunca se refrescaba antes de que caducaran las credenciales AWS, así que AWS IoT cortaba la conexión activa cada vez que expiraban (patrón regular/"sistemático"). Ahora la conexión se refresca proactivamente antes de que eso ocurra, igual que hace la app oficial.
- El aviso "Sin confirmación MQTT" ahora indica explícitamente si fue porque el MQTT estaba desconectado en ese momento o porque no llegó el ACK con la conexión activa.

## [2.4.1] - 2026-07-20

### Fixed
- La confirmación de comandos vía `feedback` (2.2.0) no funcionaba nunca: el topic se identificaba mal cuando el broker lo enviaba sin paréntesis alrededor (el caso real de `feedback`), así que la rama que procesa el ACK nunca se ejecutaba.
- El sensor de humedad (2.1.0) no mostraba nunca ningún valor: el campo real en el status es `hum`, no `hm`.

Ambos encontrados con una captura de logs real de producción compartida por el usuario tras probar un cambio de temperatura.

## [2.4.0] - 2026-07-20

### Added
- Control de velocidad de ventilador en `climate` (`fan_mode`/`fan_modes`): manual 1/2/3 o automático, solo en las zonas que lo soportan.

## [2.3.0] - 2026-07-20

### Added
- Todas las entidades pasan a "no disponible" si no reciben un status MQTT en más de 6 minutos (antes mostraban indefinidamente el último dato conocido, o valores por defecto antes del primer status).
- `should_poll = False` explícito en todas las entidades (integración 100% push, sin polling de HA).

### Fixed
- `datetime.utcnow()` (obsoleto) → `datetime.now(timezone.utc)` en la firma AWS SigV4.
- `FlowResult` genérico → `ConfigFlowResult` en el config flow (tipo correcto para HA moderno).

## [2.2.0] - 2026-07-20

### Added
- Confirmación de comandos vía el topic MQTT `.../usr/{aws_mqtt_user}/feedback`: cada comando enviado por `climate`/`switch` se correlaciona con su `orderId`, y se registra en el log si llega confirmación o si no llega en 5 s. No revierte el estado optimista todavía (pendiente de validar el payload real en producción).

## [2.1.0] - 2026-07-20

### Added
- Sensor de humedad por zona (`sensor.<zona>_humedad`).
- `climate.hvac_modes` refleja la disponibilidad real de calor/frío de cada zona (campos `c`/`f`) en vez de ofrecer siempre los tres modos.
- `climate.min_temp`/`max_temp` se actualizan con los límites reales de la zona (`tmm`/`tmx`) en vez de usar 10/30 fijos.
- Tests P2 con harness real de Home Assistant vía Docker (config flow, setup/unload, entidades) y CI en GitHub Actions (`pytest` + `hassfest`).

### Fixed
- `manifest.json`: eliminada la clave `homeassistant` (no válida para integraciones custom) y claves reordenadas — detectado por `hassfest` en CI.

## [2.0.0] - 2026-07-20

### ⚠️ Incompatible con instalaciones previas (manual, no HACS)

- **Reestructuración a `custom_components/mysair/`**: el layout plano anterior (ficheros sueltos en la raíz de `custom_components/`) ya no funciona. Hay que borrar la instalación previa y copiar la nueva carpeta completa (ver README §Instalación).
- **Corrección de la codificación de estado**: `e`=encendido/apagado/standby, `m`=modo por paridad (antes se leía `e` como si fuera el modo). Instalaciones existentes verán el modo/encendido reportado correctamente a partir de esta versión — puede diferir de lo que mostraban versiones anteriores. Ver `docs/protocol-findings.md`.
- **La config entry ya no almacena `password` en claro**: en el primer arranque tras actualizar se elimina automáticamente de entradas existentes. Si el `refresh_token` guardado no es válido, Home Assistant pedirá reautenticación desde la UI.

### Added
- Flujo de **reauth** (`async_step_reauth`) y uso de `ConfigEntryAuthFailed`/`ConfigEntryNotReady` en el setup.
- `unique_id` en la config entry: evita añadir la misma cuenta dos veces.
- `client_id` MQTT único por conexión (evita expulsar la app oficial del móvil).
- Refresco proactivo de credenciales AWS (`aws_expires_at`) y topic MQTT dinámico desde `aws_base_topic`.
- Suite de tests P0/P1 sin dependencia de Home Assistant (parser de status, builders MQTT, firma SigV4, cliente HTTP): 78 tests.
- Empaquetado para HACS (`hacs.json`), `LICENSE` (MIT) y README completo.

### Changed
- `async_unload_entry` movido a nivel de módulo, con cierre limpio de MQTT y cancelación de la tarea periódica de refresco (cada 120 s).
- `switch.turn_on` ya no fuerza modo frío: enciende preservando el último modo conocido.
- `requirements` reducidos a `requests` y `websocket-client` (se retiran `aiohttp`, `paho-mqtt`, `boto3`, no usados).
- `login()`/`refresh_tokens()` lanzan excepciones tipadas (`MySairAuthError`/`MySairConnectionError`) en vez de una excepción genérica.

### Removed
- `select.py` (código muerto, no cargado por la integración, con bugs).
- `quality_scale: silver` del manifiesto: no estaba justificado por el estado real del proyecto (sin cobertura de tests con harness de HA, sin traducciones, sin icono de marca). Se retira hasta poder reclamar un nivel real.

### Security
- El log de conexión MQTT ya no imprime la URL firmada de AWS (solo host y `client_id`).
- `password` fuera de la config entry (ver arriba).

## [1.0.0] - versión inicial

Primera versión funcional construida por el propietario del repositorio antes de este trabajo de estabilización: login, cliente MQTT y entidades `climate`/`sensor`/`switch` básicas, en layout plano (sin `custom_components/`).
