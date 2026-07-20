import asyncio
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .api import MySairAPI, MySairAuthError, MySairConnectionError
from .mqtt_handler import MySairMQTTClient
from .status_parser import parse_status_payload
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["climate", "sensor", "switch"]


@callback
def _persist_refresh_token(hass: HomeAssistant, entry: ConfigEntry, refresh_token) -> None:
    """Guarda el refresh_token si ha rotado (cada renovación invalida el anterior)."""
    if not refresh_token or refresh_token == entry.data.get("refresh_token"):
        return
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "refresh_token": refresh_token}
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Configura la integración MySair."""
    email = entry.data.get("email")
    refresh_token = entry.data.get("refresh_token")
    if not email or not refresh_token:
        raise ConfigEntryAuthFailed("Faltan credenciales; reautentica la integración MySair.")

    _LOGGER.info(f"[MySair] 🔐 Autenticando usuario {email}")

    def _on_tokens_refreshed(access_token, refresh_token_value):
        # Se invoca desde un hilo ejecutor: hay que volver al loop para tocar hass.
        hass.loop.call_soon_threadsafe(_persist_refresh_token, hass, entry, refresh_token_value)

    api = MySairAPI(email, on_tokens_refreshed=_on_tokens_refreshed)
    api.refresh_token_value = refresh_token

    # --- SESIÓN: renovar tokens a partir del refresh_token guardado (A6: no se
    # persiste ni se usa password tras la configuración inicial). ---
    try:
        await hass.async_add_executor_job(api.refresh_tokens)
    except MySairAuthError as err:
        raise ConfigEntryAuthFailed(f"Sesión MySair inválida o expirada: {err}") from err
    except MySairConnectionError as err:
        raise ConfigEntryNotReady(f"No se pudo conectar con MySair: {err}") from err

    # Migración: entradas creadas antes de A6 guardaban password/access_token
    # en claro; ya no se usan, se eliminan de la config entry en el primer
    # arranque correcto tras la actualización.
    stale_keys = {"password", "access_token"} & entry.data.keys()
    if stale_keys:
        hass.config_entries.async_update_entry(
            entry, data={k: v for k, v in entry.data.items() if k not in stale_keys}
        )

    # --- ESTRUCTURA: Locations → Installations → Devices ---
    locations = await hass.async_add_executor_job(api.get_locations)
    if not locations:
        raise ConfigEntryNotReady("No se encontraron ubicaciones en la cuenta MySair.")

    first_loc = locations[0]
    location_id = first_loc["id"]
    installations = await hass.async_add_executor_job(api.get_installations, location_id)
    if not installations:
        raise ConfigEntryNotReady("No se encontraron instalaciones en la ubicación MySair.")

    _LOGGER.info(f"[MySair] 🏠 Instalaciones detectadas: {[i['reference'] for i in installations]}")

    all_devices = {}
    installation_refs = []
    for inst in installations:
        ref = inst["reference"]
        installation_refs.append(ref)
        devices = await hass.async_add_executor_job(api.get_devices, ref)
        all_devices[ref] = devices
        _LOGGER.info(f"[MySair] 📟 Instalación {ref}: {len(devices)} termostatos encontrados")

    # Guardar datos en memoria global
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "devices": all_devices,
        "installations": installation_refs,
        "mqtt": None,
    }

    # --- CALLBACK PARA MQTT (con parseo de mensajes status) ---
    def mqtt_message_callback(data):
        """Procesa mensajes entrantes desde AWS IoT."""
        try:
            topic = data.get("topic", "")
            payload = data.get("payload", {})
            _LOGGER.debug(f"[MySair MQTT] 📩 {topic} -> {payload}")

            # Si el mensaje es de tipo "status", lo parseamos
            if topic.endswith("/status"):
                parsed_data = parse_status_payload(payload)
                hass.loop.call_soon_threadsafe(
                    hass.bus.async_fire,
                    f"{DOMAIN}_update",
                    {"topic": topic, "data": parsed_data},
                )
                _LOGGER.debug(f"[MySair MQTT] 🧩 Estado parseado: {parsed_data}")

            else:
                # Otros mensajes (no status)
                hass.loop.call_soon_threadsafe(
                    hass.bus.async_fire,
                    f"{DOMAIN}_update",
                    {"topic": topic, "data": payload},
                )

        except Exception as e:
            _LOGGER.error(f"[MySair MQTT] ❌ Error en callback: {e}")

    # --- CLIENTE MQTT ---
    mqtt_client = MySairMQTTClient(api, installation_refs, mqtt_message_callback)
    hass.data[DOMAIN][entry.entry_id]["mqtt"] = mqtt_client

    # Lanzar el hilo MQTT sin bloquear el loop
    await hass.async_add_executor_job(mqtt_client.start)

    # --- PLATAFORMAS ---
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info("[MySair] ✅ Plataformas cargadas correctamente")

    # --- REFRESCO AUTOMÁTICO DE STATUS ---
    async def refresh_status_periodic():
        """Cada 2 minutos solicita un 'status' de respaldo a todas las instalaciones.

        El estado en tiempo real llega por MQTT; este POST solo fuerza un sync
        periódico por si se pierde algún mensaje.
        """
        while True:
            try:
                for ref in installation_refs:
                    instruction = [{
                        "sender": "WEB",
                        "ctl": ref,
                        "app": api.aws_credentials.get("aws_mqtt_user", "web0077") if api.aws_credentials else "web0077",
                        "device": "",
                        "command": "status",
                        "value": "sync",
                    }]
                    await hass.async_add_executor_job(api.send_instruction, instruction)
                    _LOGGER.debug(f"[MySair] 🔁 Solicitud de estado enviada a instalación {ref}")
            except Exception as e:
                _LOGGER.warning(f"[MySair] ⚠️ Error al enviar instrucción de estado: {e}")
            await asyncio.sleep(120)  # 2 minutos

    # Lanzar la tarea periódica ligada al ciclo de vida de la entrada:
    # Home Assistant la cancela automáticamente durante el unload.
    entry.async_create_background_task(
        hass, refresh_status_periodic(), name="mysair_status_refresh"
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Descarga la integración MySair y libera recursos (MQTT, tareas, estado).

    Orden de cierre: primero se descargan las plataformas (las entidades quitan
    sus listeners del bus), después se detiene el cliente MQTT y por último se
    limpia el estado en memoria. La tarea periódica se cancela sola por estar
    creada con entry.async_create_background_task.
    """
    _LOGGER.info("[MySair] 🔌 Deteniendo integración y cerrando sesiones...")

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if data:
            mqtt_client = data.get("mqtt")
            if mqtt_client:
                await hass.async_add_executor_job(mqtt_client.stop)

    return unload_ok

