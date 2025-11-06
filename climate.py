import logging
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    HVACMode,
    HVACAction,
)
from homeassistant.const import UnitOfTemperature, ATTR_TEMPERATURE
from homeassistant.core import callback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Configura los termostatos MySair."""
    data = hass.data[DOMAIN][entry.entry_id]
    api = data["api"]
    devices = data["devices"]

    entities = []
    for inst_ref, device_list in devices.items():
        for dev in device_list:
            dev_id = dev.get("reference") or dev.get("rf") or dev.get("id")
            name = dev.get("name", f"Termostato {dev_id}")
            entities.append(MySairThermostat(hass, api, inst_ref, dev_id, name))

    async_add_entities(entities)
    _LOGGER.info(f"[MySair Climate] ✅ {len(entities)} termostatos creados.")


class MySairThermostat(ClimateEntity):
    """Entidad Climate de un termostato MySair."""

    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL]
    _attr_min_temp = 10
    _attr_max_temp = 30

    def __init__(self, hass, api, inst_ref, device_id, name):
        self.hass = hass
        self.api = api
        self.inst_ref = inst_ref
        self.device_id = device_id
        self._attr_unique_id = f"mysair_{inst_ref}_{device_id}"
        self._attr_name = name
        self._target_temperature = 22.0
        self._current_temperature = None
        self._hvac_mode = HVACMode.OFF
        self._hvac_action = HVACAction.IDLE
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

    async def async_added_to_hass(self):
        _LOGGER.debug(f"[MySair Climate] 🧩 Entidad añadida: {self._attr_name} ({self.inst_ref}/{self.device_id})")
        self._unsub = self.hass.bus.async_listen(f"{DOMAIN}_update", self._handle_mqtt_update)

    async def async_will_remove_from_hass(self):
        if self._unsub:
            self._unsub()
            self._unsub = None

    @property
    def hvac_mode(self):
        return self._hvac_mode

    @property
    def hvac_action(self):
        return self._hvac_action

    @property
    def current_temperature(self):
        return self._current_temperature

    @property
    def target_temperature(self):
        return self._target_temperature

    # ------------------------------------------------------------------
    # MÉTODOS DE CONTROL (usando send_zone_command)
    # ------------------------------------------------------------------
    async def async_set_temperature(self, **kwargs):
        if ATTR_TEMPERATURE not in kwargs:
            return
        new_temp = kwargs[ATTR_TEMPERATURE]
        self._target_temperature = new_temp

        if self._hvac_mode == HVACMode.OFF:
            _LOGGER.debug(f"[MySair Climate] 💡 Apagado, actualizo consigna local a {new_temp}°C")
            self.async_write_ha_state()
            return

        _LOGGER.info(f"[MySair Climate] 🌡️ Cambiando temperatura a {new_temp}°C en {self.name}")
        try:
            await self.hass.async_add_executor_job(
                self.api.send_zone_command,
                self.inst_ref,
                self.device_id,
                "temp",
                new_temp
            )
            self.async_write_ha_state()
        except Exception as e:
            _LOGGER.error(f"[MySair Climate] ❌ Error al enviar cambio de temperatura: {e}")

    async def async_set_hvac_mode(self, hvac_mode):
        if hvac_mode not in self._attr_hvac_modes:
            _LOGGER.warning(f"[MySair Climate] ❌ Modo HVAC inválido: {hvac_mode}")
            return

        try:
            if hvac_mode == HVACMode.HEAT:
                _LOGGER.info(f"[MySair Climate] 🔥 Encendiendo {self.name} en CALOR a {self._target_temperature}°C")
                await self.hass.async_add_executor_job(
                    self.api.send_zone_command,
                    self.inst_ref,
                    self.device_id,
                    "mode",
                    "0",
                    self._target_temperature
                )

            elif hvac_mode == HVACMode.COOL:
                _LOGGER.info(f"[MySair Climate] ❄️ Encendiendo {self.name} en FRÍO a {self._target_temperature}°C")
                await self.hass.async_add_executor_job(
                    self.api.send_zone_command,
                    self.inst_ref,
                    self.device_id,
                    "mode",
                    "1",
                    self._target_temperature
                )

            elif hvac_mode == HVACMode.OFF:
                _LOGGER.info(f"[MySair Climate] ⛔ Apagando {self.name}")
                await self.hass.async_add_executor_job(
                    self.api.send_zone_command,
                    self.inst_ref,
                    self.device_id,
                    "power"
                )

            self._hvac_mode = hvac_mode
            self.async_write_ha_state()

        except Exception as e:
            _LOGGER.error(f"[MySair Climate] ❌ Error al cambiar modo HVAC: {e}")

    async def async_turn_off(self):
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_turn_on(self):
        next_mode = self._hvac_mode if self._hvac_mode != HVACMode.OFF else HVACMode.HEAT
        await self.async_set_hvac_mode(next_mode)

    # ------------------------------------------------------------------
    # EVENTOS MQTT → ACTUALIZACIÓN DE ESTADO
    # ------------------------------------------------------------------
    @callback
    def _handle_mqtt_update(self, event):
        topic = event.data.get("topic", "")
        data = event.data.get("data", {})
        if not topic.endswith("/status"):
            return

        ctl = data.get("ctl")
        if ctl != self.inst_ref:
            return

        zones = data.get("zones", [])
        for zone in zones:
            if zone.get("zone_id") != self.device_id:
                continue

            _LOGGER.debug(f"[MySair Climate] 📨 Evento recibido para {self._attr_name}")
            self._current_temperature = zone.get("temp_actual")
            self._target_temperature = zone.get("temp_target")

            mode = zone.get("mode")
            if mode == 1:
                self._hvac_mode = HVACMode.HEAT
                self._hvac_action = HVACAction.HEATING
            elif mode == 2:
                self._hvac_mode = HVACMode.COOL
                self._hvac_action = HVACAction.COOLING
            else:
                self._hvac_mode = HVACMode.OFF
                self._hvac_action = HVACAction.OFF

            _LOGGER.debug(
                f"[MySair Climate] 🔄 {self._attr_name}: {self._current_temperature}°C / "
                f"{self._target_temperature}°C / {self._hvac_mode}"
            )
            self.async_write_ha_state()

