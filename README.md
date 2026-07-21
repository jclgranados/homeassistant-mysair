# MySair para Home Assistant

Integración **no oficial** de Home Assistant para el sistema de zonificación de climatización **MySair** (aire acondicionado y/o suelo radiante, por zona), construida por ingeniería inversa de la app web oficial (API HTTP + AWS IoT MQTT). No está afiliada ni respaldada por MySair.

> ⚠️ **No oficial.** El protocolo no está documentado públicamente por el fabricante; puede romperse sin aviso si MySair cambia su backend. Úsala bajo tu propio riesgo. Ver [`docs/known-unknowns.md`](docs/known-unknowns.md) para las incógnitas abiertas del protocolo.

## Qué hace

- **Descubre** la topología de tu cuenta: `Location → Installation → Device (zona)`.
- Recibe el **estado en tiempo real** (temperatura, consigna, modo, encendido) por MQTT sobre WebSocket (AWS IoT), con un refresco de respaldo por HTTP cada 2 minutos.
- Permite **controlar** cada zona (encendido/apagado, modo calor/frío, temperatura consigna, y suelo radiante si la zona lo tiene) desde Home Assistant.

## Entidades por zona

| Entidad | Tipo | Descripción |
|---|---|---|
| `climate.<zona>` | Climate | Termostato: encendido/apagado, modo calor/frío (según disponibilidad real de la zona), temperatura objetivo, min/max reales, velocidad de ventilador (manual 1-3 o automático, si la zona lo soporta) |
| `switch.<zona>` | Switch | Encendido/apagado, preservando el último modo usado |
| `switch.<zona>_suelo` | Switch | Suelo radiante encendido/apagado, combinable con el AC de la misma zona. Aparece como "no disponible" en zonas sin esa capacidad |
| `sensor.<zona>_temperatura_actual` | Sensor | Temperatura actual de la zona |
| `sensor.<zona>_temperatura_consigna` | Sensor | Temperatura objetivo (setpoint) |
| `sensor.<zona>_modo` | Sensor | Modo actual (`OFF`/`HEAT`/`COOL`) |
| `sensor.<zona>_humedad` | Sensor | Humedad relativa de la zona |

## Otras entidades

| Entidad | Tipo | Descripción |
|---|---|---|
| `sensor.mysair_conexion_mqtt` | Sensor | Una por cuenta configurada: estado de la conexión MQTT (`online`/`offline`), hora de la última actualización recibida, y métricas de reconexión/parseo (para depuración) |

## Instalación

### Opción A — HACS (repositorio personalizado)

1. HACS → menú (⋮) → **Repositorios personalizados**.
2. Añade `https://github.com/jclgranados/homeassistant-mysair` como tipo **Integración**.
3. Busca "MySair" en HACS e instálala.
4. Reinicia Home Assistant.

### Opción B — Manual

1. Copia la carpeta `custom_components/mysair/` de este repositorio a `<config>/custom_components/mysair/` en tu instalación de Home Assistant.
2. Reinicia Home Assistant por completo (no solo recargar la integración).

## Configuración

Ajustes → Dispositivos y servicios → Añadir integración → **MySair** → introduce el email y la contraseña de tu cuenta MySair.

- La contraseña **no se guarda**: solo se usa una vez para obtener un `refresh_token`, que es lo que se persiste y lo que renueva la sesión en cada arranque (ver [`docs/security-and-privacy.md`](docs/security-and-privacy.md)).
- Si la sesión deja de ser válida (p. ej. el `refresh_token` expira), Home Assistant te pedirá reautenticarte desde la propia UI de la integración, sin perder la configuración existente.

## Limitaciones conocidas

- **Las entidades tardan unos segundos en mostrar datos reales tras un arranque/recarga**: aparecen como "no disponible" hasta recibir el primer status por MQTT (y de nuevo si se pierde la conexión más de 6 minutos), en vez de mostrar valores por defecto como si fueran en tiempo real.
- **Solo la primera `Location`** de la cuenta: si tienes varias ubicaciones, solo se cargan las instalaciones de la primera (decisión de alcance, ver `docs/known-unknowns.md` #15).
- **Sin temporizador ni programas por horario**: el backend no expone ninguna forma confirmada de fijarlos (solo de leerlos); adivinar el formato no es una opción responsable (decisión de alcance, ver `docs/known-unknowns.md` #27).
- **Sin modo automático (HVAC)**: no es una carencia de la integración — el protocolo en sí no tiene ningún modo de cambio automático calor/frío (ver `docs/protocol-findings.md` §4). El único "automático" real del sistema es la velocidad de ventilador, que sí está implementada.
- Requiere Home Assistant **≥ 2025.10.0**.

## Documentación técnica

Para arquitectura, protocolo HTTP/MQTT, modelo de dominio, estrategia de tests y roadmap, ver la carpeta [`docs/`](docs/) y [`CLAUDE.md`](CLAUDE.md).

## Desarrollo y contribuciones

Tests P0/P1 (parser, builders MQTT, firma SigV4, cliente HTTP) corren sin Home Assistant:

```bash
python -m venv .venv-test && source .venv-test/bin/activate
pip install -r requirements-test.txt
pytest
```

Tests P2 (config flow, setup/unload) usan un harness real de Home Assistant, vía Docker — no instala nada en tu máquina:

```bash
docker compose run --rm test-ha
```

Issues y pull requests son bienvenidos. Revisa `CLAUDE.md` antes de tocar el protocolo o las credenciales.

## Changelog

Ver [`CHANGELOG.md`](CHANGELOG.md).

## Licencia

[MIT](LICENSE)
