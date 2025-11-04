from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .api import MySairAPI
from .mqtt_handler import MySairMQTTClient
from .const import DOMAIN

PLATFORMS: list[str] = ["climate"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configura MySair a partir de una entrada de configuración (UI)."""

    email = entry.data["email"]
    password = entry.data["password"]

    api = MySairAPI(email, password)
    aws_data = await api.login()

    mqtt_client = MySairMQTTClient(aws_data, lambda msg: None)
    mqtt_client.start()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "mqtt": mqtt_client,
    }

    # Cargar plataformas asociadas (por ejemplo, climate)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Desinstala MySair cuando se elimina desde la UI."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok

