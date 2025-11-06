from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    api = data["api"]
    mqtt = data["mqtt"]  # noqa: F401

    selects = []

    locations = await api.get_locations()
    for loc in locations["entity"]:
        insts = await api.get_installations(loc["id"])
        for inst in insts["entity"]:
            devices = await api.get_devices(inst["reference"])
            for dev in devices["entity"]:
                selects.append(MySairModeSelect(api, inst["reference"], dev))

    async_add_entities(selects)
    hass.data[DOMAIN][entry.entry_id]["select_entities"] = selects
    print(f"✅ [MySair] Añadidos {len(selects)} selectores de modo.")


class MySairModeSelect(SelectEntity):
    """Selector de modo (Frío/Calor)."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = ["Frío", "Calor"]

    def __init__(self, api, installation_ref, device):
        self._api = api
        self._installation_ref = installation_ref
        self._device = device
        self._attr_name = f"{device.get('name', 'Termostato')} Modo"
        self._attr_unique_id = f"{installation_ref}_{device.get('reference')}_mode_select"
        self._attr_current_option = None

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"{self._installation_ref}_{self._device.get('reference')}")},
            "name": self._device.get("name", "Termostato"),
            "manufacturer": "MySair",
            "model": "WiFi Thermostat",
            "sw_version": "1.0",
            "via_device": (DOMAIN, self._installation_ref),
        }

    @property
    def current_option(self):
        return self._attr_current_option

    async def async_select_option(self, option: str):
        mode = "1" if option == "Calor" else "0"
        payload = [{
            "sender": "WEB",
            "ctl": self._installation_ref,
            "app": self._api.aws_data.get("aws_mqtt_user"),
            "device": self._device["reference"],
            "command": "mode",
            "value": {"mode": mode}
        }]
        await self._api.send_instruction(payload)
        self._attr_current_option = option
        self.async_write_ha_state()

    def update_from_status(self, thermostat: dict):
        m = thermostat.get("m")
        if m is not None:
            self._attr_current_option = "Calor" if str(m) == "1" else "Frío"
            self.async_write_ha_state()

