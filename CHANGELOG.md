# Changelog

Todos los cambios notables de este proyecto se documentan en este fichero.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y este proyecto se adhiere a [Semantic Versioning](https://semver.org/lang/es/): `MAJOR.MINOR.PATCH`, donde `MAJOR` indica cambios incompatibles (p. ej. ruta de instalación, esquema de la config entry o comportamiento observable), `MINOR` añade funcionalidad compatible hacia atrás, y `PATCH` corrige bugs sin cambiar comportamiento esperado.

## [Unreleased]

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
