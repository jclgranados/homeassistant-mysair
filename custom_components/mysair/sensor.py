import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfTemperature
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.core import callback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Configura los sensores MySair (temperaturas y modo por zona)."""
    data = hass.data[DOMAIN][entry.entry_id]
    devices = data["devices"]

    entities = []
    for inst_ref, device_list in devices.items():
        for dev in device_list:
            dev_id = dev.get("reference") or dev.get("rf") or dev.get("id")
            name = dev.get("name", f"Zona {dev_id}")
            entities.append(MySairTempSensor(hass, inst_ref, dev_id, f"{name} Temperatura Actual"))
            entities.append(MySairSetpointSensor(hass, inst_ref, dev_id, f"{name} Temperatura Consigna"))
            entities.append(MySairModeSensor(hass, inst_ref, dev_id, f"{name} Modo"))

    async_add_entities(entities)
    _LOGGER.info(f"[MySair Sensor] ✅ {len(entities)} sensores creados.")


# ==========================================================
# 🌡️ SENSOR DE TEMPERATURA ACTUAL
# ==========================================================
class MySairTempSensor(SensorEntity):
    """Mide la temperatura actual de la zona."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_icon = "mdi:thermometer"

    def __init__(self, hass, inst_ref, device_id, name):
        self.hass = hass
        self.inst_ref = inst_ref
        self.device_id = device_id
        self._attr_name = name
        self._attr_unique_id = f"mysair_temp_{inst_ref}_{device_id}"
        self._state = None
        self._unsub = None

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"{self.inst_ref}_{self.device_id}")},
            "name": f"{self.device_id.upper()} ({self.inst_ref})",
            "manufacturer": "MySair",
            "model": "Zonificador de aire",
            "sw_version": "v1.0",
        }

    @property
    def native_value(self):
        return self._state

    async def async_added_to_hass(self):
        self._unsub = self.hass.bus.async_listen(f"{DOMAIN}_update", self._handle_mqtt_update)

    async def async_will_remove_from_hass(self):
        if self._unsub:
            self._unsub()
            self._unsub = None

    @callback
    def _handle_mqtt_update(self, event):
        topic = event.data.get("topic", "")
        data = event.data.get("data", {})
        if not topic.endswith("/status"):
            return
        ctl = data.get("ctl")
        if ctl != self.inst_ref:
            return
        for zone in data.get("zones", []):
            if zone.get("zone_id") != self.device_id:
                continue
            new_val = zone.get("temp_actual")
            if new_val != self._state:
                self._state = new_val
                _LOGGER.debug(f"[MySair Sensor] 🌡️ {self._attr_name}: {new_val}°C")
                self.async_write_ha_state()


# ==========================================================
# 🎯 SENSOR DE TEMPERATURA DE CONSIGNA
# ==========================================================
class MySairSetpointSensor(SensorEntity):
    """Muestra la temperatura de consigna actual."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_icon = "mdi:thermostat"

    def __init__(self, hass, inst_ref, device_id, name):
        self.hass = hass
        self.inst_ref = inst_ref
        self.device_id = device_id
        self._attr_name = name
        self._attr_unique_id = f"mysair_setpoint_{inst_ref}_{device_id}"
        self._state = None
        self._unsub = None

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"{self.inst_ref}_{self.device_id}")},
            "name": f"{self.device_id.upper()} ({self.inst_ref})",
            "manufacturer": "MySair",
            "model": "Zonificador de aire",
            "sw_version": "v1.0",
        }

    @property
    def native_value(self):
        return self._state

    async def async_added_to_hass(self):
        self._unsub = self.hass.bus.async_listen(f"{DOMAIN}_update", self._handle_mqtt_update)

    async def async_will_remove_from_hass(self):
        if self._unsub:
            self._unsub()
            self._unsub = None

    @callback
    def _handle_mqtt_update(self, event):
        topic = event.data.get("topic", "")
        data = event.data.get("data", {})
        if not topic.endswith("/status"):
            return
        ctl = data.get("ctl")
        if ctl != self.inst_ref:
            return
        for zone in data.get("zones", []):
            if zone.get("zone_id") != self.device_id:
                continue
            new_val = zone.get("temp_target")
            if new_val != self._state:
                self._state = new_val
                _LOGGER.debug(f"[MySair Sensor] 🎯 {self._attr_name}: {new_val}°C")
                self.async_write_ha_state()


# ==========================================================
# 🔄 SENSOR DE MODO HVAC
# ==========================================================
class MySairModeSensor(SensorEntity):
    """Muestra el modo actual (OFF / HEAT / COOL)."""

    _attr_icon = "mdi:repeat-variant"

    def __init__(self, hass, inst_ref, device_id, name):
        self.hass = hass
        self.inst_ref = inst_ref
        self.device_id = device_id
        self._attr_name = name
        self._attr_unique_id = f"mysair_mode_{inst_ref}_{device_id}"
        self._state = "OFF"
        self._unsub = None

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"{self.inst_ref}_{self.device_id}")},
            "name": f"{self.device_id.upper()} ({self.inst_ref})",
            "manufacturer": "MySair",
            "model": "Zonificador de aire",
            "sw_version": "v1.0",
        }

    @property
    def native_value(self):
        return self._state

    async def async_added_to_hass(self):
        self._unsub = self.hass.bus.async_listen(f"{DOMAIN}_update", self._handle_mqtt_update)

    async def async_will_remove_from_hass(self):
        if self._unsub:
            self._unsub()
            self._unsub = None

    @callback
    def _handle_mqtt_update(self, event):
        topic = event.data.get("topic", "")
        data = event.data.get("data", {})
        if not topic.endswith("/status"):
            return
        ctl = data.get("ctl")
        if ctl != self.inst_ref:
            return
        for zone in data.get("zones", []):
            if zone.get("zone_id") != self.device_id:
                continue
            mode = zone.get("mode")
            new_state = "OFF"
            if mode == 1:
                new_state = "HEAT"
            elif mode == 2:
                new_state = "COOL"
            if new_state != self._state:
                self._state = new_state
                _LOGGER.debug(f"[MySair Sensor] 🔄 {self._attr_name}: {self._state}")
                self.async_write_ha_state()

