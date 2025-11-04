from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import HVACMode
from homeassistant.const import UnitOfTemperature, ATTR_TEMPERATURE

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Configura las entidades de clima MySair desde una entrada de configuración."""
    data = hass.data[DOMAIN][entry.entry_id]
    api = data["api"]
    mqtt = data["mqtt"]

    devices_to_add = []

    # Descubrir ubicaciones e instalaciones
    locations = await api.get_locations()
    for loc in locations["entity"]:
        insts = await api.get_installations(loc["id"])
        for inst in insts["entity"]:
            devices = await api.get_devices(inst["reference"])
            for dev in devices["entity"]:
                devices_to_add.append(MySairClimate(api, mqtt, inst["reference"], dev))

    async_add_entities(devices_to_add)
    print(f"✅ [MySair] Se han añadido {len(devices_to_add)} termostatos.")


class MySairClimate(ClimateEntity):
    """Entidad Climate para cada termostato MySair."""

    def __init__(self, api, mqtt, installation_ref, device):
        self._api = api
        self._mqtt = mqtt
        self._installation_ref = installation_ref
        self._device = device
        self._name = device.get("name", "Termostato")
        self._unique_id = f"{installation_ref}_{device.get('reference')}"
        self._temperature = 21.0
        self._mode = HVACMode.OFF
        self._is_on = False

    @property
    def name(self):
        return self._name

    @property
    def unique_id(self):
        return self._unique_id

    @property
    def temperature_unit(self):
        return UnitOfTemperature.CELSIUS

    @property
    def target_temperature(self):
        return self._temperature

    @property
    def hvac_mode(self):
        return self._mode

    @property
    def hvac_modes(self):
        return [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL]

    async def async_set_hvac_mode(self, hvac_mode: HVACMode):
        """Cambia el modo de funcionamiento."""
        self._mode = hvac_mode
        mode_val = "1" if hvac_mode == HVACMode.HEAT else "0"
        payload = [{
            "sender": "WEB",
            "ctl": self._installation_ref,
            "app": self._api.aws_data.get("aws_mqtt_user"),
            "device": self._device.get("reference"),
            "command": "mode",
            "value": {"mode": mode_val, "temperature": str(self._temperature)}
        }]
        await self._api.send_instruction(payload)
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs):
        """Ajusta la temperatura objetivo."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is not None:
            self._temperature = temperature
            payload = [{
                "sender": "WEB",
                "ctl": self._installation_ref,
                "app": self._api.aws_data.get("aws_mqtt_user"),
                "device": self._device.get("reference"),
                "command": "mode",
                "value": {
                    "mode": "1" if self._mode == HVACMode.HEAT else "0",
                    "temperature": str(temperature)
                }
            }]
            await self._api.send_instruction(payload)
            self.async_write_ha_state()

