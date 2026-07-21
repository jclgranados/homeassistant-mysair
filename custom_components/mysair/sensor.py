import logging
from datetime import timedelta
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfTemperature, PERCENTAGE
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .availability import AvailabilityMixin
from .const import DOMAIN, SCAN_INTERVAL as _SCAN_INTERVAL_SECONDS
from .coordinator import signal_zone_update

_LOGGER = logging.getLogger(__name__)

# Respetado automáticamente por HA para las entidades de este platform con
# should_poll=True (MySairMqttStatusSensor); los sensores por zona usan
# should_poll=False (AvailabilityMixin) y no se ven afectados.
SCAN_INTERVAL = timedelta(seconds=_SCAN_INTERVAL_SECONDS)


async def async_setup_entry(hass, entry, async_add_entities):
    """Configura los sensores MySair (temperaturas y modo por zona)."""
    data = hass.data[DOMAIN][entry.entry_id]
    devices = data["devices"]
    mqtt_client = data["mqtt"]

    entities = [MySairMqttStatusSensor(hass, entry.entry_id, mqtt_client)]
    for inst_ref, device_list in devices.items():
        for dev in device_list:
            dev_id = dev.get("reference") or dev.get("rf") or dev.get("id")
            name = dev.get("name", f"Zona {dev_id}")
            entities.append(MySairTempSensor(hass, inst_ref, dev_id, f"{name} Temperatura Actual"))
            entities.append(MySairSetpointSensor(hass, inst_ref, dev_id, f"{name} Temperatura Consigna"))
            entities.append(MySairModeSensor(hass, inst_ref, dev_id, f"{name} Modo"))
            entities.append(MySairHumiditySensor(hass, inst_ref, dev_id, f"{name} Humedad"))

    async_add_entities(entities)
    _LOGGER.info(f"[MySair Sensor] ✅ {len(entities)} sensores creados.")


# ==========================================================
# 📶 SENSOR DE ESTADO DE CONEXIÓN MQTT (D3/D4)
# ==========================================================
class MySairMqttStatusSensor(SensorEntity):
    """Estado de la conexión MQTT (D3) y métricas de reconexión/parseo (D4).

    Una instancia por config entry (no por zona): a diferencia del resto de
    sensores, no depende de datos de una zona concreta ni de AvailabilityMixin
    (su propia "no disponibilidad" no tiene sentido — incluso "offline" es
    información válida). Se actualiza por sondeo (should_poll=True) leyendo
    directamente el estado en vivo de MySairMQTTClient.
    """

    _attr_icon = "mdi:wifi"
    _attr_should_poll = True
    _attr_name = "MySair Conexión MQTT"

    def __init__(self, hass, entry_id, mqtt_client):
        self.hass = hass
        self.entry_id = entry_id
        self.mqtt_client = mqtt_client
        self._attr_unique_id = f"mysair_mqtt_status_{entry_id}"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.entry_id)},
            "name": "MySair (cuenta)",
            "manufacturer": "MySair",
            "model": "Integración",
        }

    @property
    def native_value(self):
        return "online" if self.mqtt_client.connected else "offline"

    @property
    def extra_state_attributes(self):
        last = self.mqtt_client.last_message_at
        return {
            "last_update": last.isoformat() if last else None,
            "reconnect_attempts": self.mqtt_client.reconnect_attempt,
            "total_reconnects": self.mqtt_client.total_reconnects,
            "parse_strict_count": self.mqtt_client.parse_strict_count,
            "parse_fallback_count": self.mqtt_client.parse_fallback_count,
            "parse_error_count": self.mqtt_client.parse_error_count,
            "last_close_code": self.mqtt_client.last_close_code,
        }


# ==========================================================
# 🌡️ SENSOR DE TEMPERATURA ACTUAL
# ==========================================================
class MySairTempSensor(AvailabilityMixin, SensorEntity):
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
        self._init_availability()

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"{self.inst_ref}_{self.device_id}")},
            "name": f"{self.device_id.upper()} ({self.inst_ref})",
            "manufacturer": "MySair",
            "model": "Zonificador de climatización",
            "sw_version": "v1.0",
        }

    @property
    def native_value(self):
        return self._state

    async def async_added_to_hass(self):
        self._unsub = async_dispatcher_connect(
            self.hass, signal_zone_update(self.inst_ref, self.device_id), self._handle_zone_update
        )

    async def async_will_remove_from_hass(self):
        if self._unsub:
            self._unsub()
            self._unsub = None
        self._stop_availability()

    @callback
    def _handle_zone_update(self, zone):
        self._mark_status_received()
        new_val = zone.get("temp_actual")
        if new_val != self._state:
            self._state = new_val
            _LOGGER.debug(f"[MySair Sensor] 🌡️ {self._attr_name}: {new_val}°C")
        self.async_write_ha_state()


# ==========================================================
# 🎯 SENSOR DE TEMPERATURA DE CONSIGNA
# ==========================================================
class MySairSetpointSensor(AvailabilityMixin, SensorEntity):
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
        self._init_availability()

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"{self.inst_ref}_{self.device_id}")},
            "name": f"{self.device_id.upper()} ({self.inst_ref})",
            "manufacturer": "MySair",
            "model": "Zonificador de climatización",
            "sw_version": "v1.0",
        }

    @property
    def native_value(self):
        return self._state

    async def async_added_to_hass(self):
        self._unsub = async_dispatcher_connect(
            self.hass, signal_zone_update(self.inst_ref, self.device_id), self._handle_zone_update
        )

    async def async_will_remove_from_hass(self):
        if self._unsub:
            self._unsub()
            self._unsub = None
        self._stop_availability()

    @callback
    def _handle_zone_update(self, zone):
        self._mark_status_received()
        new_val = zone.get("temp_target")
        if new_val != self._state:
            self._state = new_val
            _LOGGER.debug(f"[MySair Sensor] 🎯 {self._attr_name}: {new_val}°C")
        self.async_write_ha_state()


# ==========================================================
# 🔄 SENSOR DE MODO HVAC
# ==========================================================
class MySairModeSensor(AvailabilityMixin, SensorEntity):
    """Muestra el modo actual (OFF / HEAT / COOL) y, como atributo, el medio
    activo (AC / suelo radiante / mixto — ver F4)."""

    _attr_icon = "mdi:repeat-variant"

    def __init__(self, hass, inst_ref, device_id, name):
        self.hass = hass
        self.inst_ref = inst_ref
        self.device_id = device_id
        self._attr_name = name
        self._attr_unique_id = f"mysair_mode_{inst_ref}_{device_id}"
        self._state = "OFF"
        self._medium = None
        self._unsub = None
        self._init_availability()

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"{self.inst_ref}_{self.device_id}")},
            "name": f"{self.device_id.upper()} ({self.inst_ref})",
            "manufacturer": "MySair",
            "model": "Zonificador de climatización",
            "sw_version": "v1.0",
        }

    @property
    def native_value(self):
        return self._state

    @property
    def extra_state_attributes(self):
        return {"medio": self._medium}

    async def async_added_to_hass(self):
        self._unsub = async_dispatcher_connect(
            self.hass, signal_zone_update(self.inst_ref, self.device_id), self._handle_zone_update
        )

    async def async_will_remove_from_hass(self):
        if self._unsub:
            self._unsub()
            self._unsub = None
        self._stop_availability()

    @callback
    def _handle_zone_update(self, zone):
        self._mark_status_received()
        # 'e' = encendido; calor/frío = paridad de 'm'. Ver docs/protocol-findings.md.
        new_state = "OFF"
        if zone.get("is_on"):
            if zone.get("is_cool"):
                new_state = "COOL"
            elif zone.get("is_heat"):
                new_state = "HEAT"
            else:
                new_state = "ON"
        if new_state != self._state:
            self._state = new_state
            _LOGGER.debug(f"[MySair Sensor] 🔄 {self._attr_name}: {self._state}")

        # Medio activo (F4/AC-vs-suelo): 'm' distingue AC-solo/suelo-solo/mixto
        # con independencia de encendido/apagado (se conserva aunque la zona
        # esté apagada). Ver docs/protocol-findings.md §4.
        if zone.get("is_ac") and zone.get("is_floor"):
            self._medium = "mixto"
        elif zone.get("is_floor"):
            self._medium = "suelo"
        elif zone.get("is_ac"):
            self._medium = "ac"
        else:
            self._medium = None

        self.async_write_ha_state()


# ==========================================================
# 💧 SENSOR DE HUMEDAD
# ==========================================================
class MySairHumiditySensor(AvailabilityMixin, SensorEntity):
    """Muestra la humedad relativa de la zona (campo ``hm``)."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_icon = "mdi:water-percent"

    def __init__(self, hass, inst_ref, device_id, name):
        self.hass = hass
        self.inst_ref = inst_ref
        self.device_id = device_id
        self._attr_name = name
        self._attr_unique_id = f"mysair_humidity_{inst_ref}_{device_id}"
        self._state = None
        self._unsub = None
        self._init_availability()

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"{self.inst_ref}_{self.device_id}")},
            "name": f"{self.device_id.upper()} ({self.inst_ref})",
            "manufacturer": "MySair",
            "model": "Zonificador de climatización",
            "sw_version": "v1.0",
        }

    @property
    def native_value(self):
        return self._state

    async def async_added_to_hass(self):
        self._unsub = async_dispatcher_connect(
            self.hass, signal_zone_update(self.inst_ref, self.device_id), self._handle_zone_update
        )

    async def async_will_remove_from_hass(self):
        if self._unsub:
            self._unsub()
            self._unsub = None
        self._stop_availability()

    @callback
    def _handle_zone_update(self, zone):
        self._mark_status_received()
        new_val = zone.get("humidity")
        if new_val != self._state:
            self._state = new_val
            _LOGGER.debug(f"[MySair Sensor] 💧 {self._attr_name}: {new_val}%")
        self.async_write_ha_state()

