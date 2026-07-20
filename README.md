# MySair para Home Assistant

Integración **no oficial** de Home Assistant para el sistema de zonificación de aire acondicionado **MySair**, construida por ingeniería inversa de la app web oficial (API HTTP + AWS IoT MQTT). No está afiliada ni respaldada por MySair.

> ⚠️ **No oficial.** El protocolo no está documentado públicamente por el fabricante; puede romperse sin aviso si MySair cambia su backend. Úsala bajo tu propio riesgo. Ver [`docs/known-unknowns.md`](docs/known-unknowns.md) para las incógnitas abiertas del protocolo.

## Qué hace

- **Descubre** la topología de tu cuenta: `Location → Installation → Device (zona)`.
- Recibe el **estado en tiempo real** (temperatura, consigna, modo, encendido) por MQTT sobre WebSocket (AWS IoT), con un refresco de respaldo por HTTP cada 2 minutos.
- Permite **controlar** cada zona (encendido/apagado, modo calor/frío, temperatura consigna) desde Home Assistant.

## Entidades por zona

| Entidad | Tipo | Descripción |
|---|---|---|
| `climate.<zona>` | Climate | Termostato: encendido/apagado, modo calor/frío, temperatura objetivo |
| `switch.<zona>` | Switch | Encendido/apagado, preservando el último modo usado |
| `sensor.<zona>_temperatura` | Sensor | Temperatura actual de la zona |
| `sensor.<zona>_consigna` | Sensor | Temperatura objetivo (setpoint) |
| `sensor.<zona>_modo` | Sensor | Modo actual (`off`/`heat`/`cool`) |

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

- **Solo la primera `Location`** de la cuenta: si tienes varias ubicaciones, solo se cargan las instalaciones de la primera (decisión de alcance, ver `docs/known-unknowns.md` #15).
- El **parser de frames MQTT crudos** es best-effort (no decodifica la cabecera MQTT completa); es robusto para el tráfico observado hasta ahora pero podría fallar ante formatos no vistos (`docs/known-unknowns.md` #6).
- Sin **fan speed** ni **modo automático** todavía (protocolo parcialmente reverseado, ver `docs/protocol-findings.md`).
- Requiere Home Assistant **≥ 2025.10.0**.

## Documentación técnica

Para arquitectura, protocolo HTTP/MQTT, modelo de dominio, estrategia de tests y roadmap, ver la carpeta [`docs/`](docs/) y [`CLAUDE.md`](CLAUDE.md).

## Desarrollo y contribuciones

El repositorio no tiene entorno de HA para tests completos todavía; los tests P0/P1 (parser, builders MQTT, firma SigV4, cliente HTTP) corren sin HA:

```bash
python -m venv .venv-test && source .venv-test/bin/activate
pip install -r requirements-test.txt
pytest
```

Issues y pull requests son bienvenidos. Revisa `CLAUDE.md` antes de tocar el protocolo o las credenciales.

## Changelog

Ver [`CHANGELOG.md`](CHANGELOG.md).

## Licencia

[MIT](LICENSE)
