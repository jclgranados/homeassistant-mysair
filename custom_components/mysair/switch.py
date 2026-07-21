import logging
from homeassistant.components.switch import SwitchEntity
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .availability import AvailabilityMixin
from .command_feedback import CommandFeedbackMixin
from .const import DOMAIN
from .coordinator import signal_zone_update
from .status_parser import compute_mode_value

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Configura los switches de MySair (encendido/apagado por zona)."""
    data = hass.data[DOMAIN][entry.entry_id]
    api = data["api"]
    mqtt_client = data["mqtt"]
    devices = data["devices"]

    entities = []
    for inst_ref, device_list in devices.items():
        for dev in device_list:
            dev_id = dev.get("reference") or dev.get("rf") or dev.get("id")
            name = dev.get("name", f"Zona {dev_id} (Power)")
            zone_name = dev.get("name", f"Zona {dev_id}")
            entities.append(MySairSwitch(hass, api, mqtt_client, inst_ref, dev_id, name))
            entities.append(MySairFloorSwitch(hass, api, mqtt_client, inst_ref, dev_id, f"{zone_name} Suelo"))

    async_add_entities(entities)
    _LOGGER.info(f"[MySair Switch] ✅ {len(entities)} switches creados.")


class MySairSwitch(CommandFeedbackMixin, AvailabilityMixin, SwitchEntity):
    """Entidad Switch para encender o apagar cada termostato MySair."""

    _attr_icon = "mdi:power"

    def __init__(self, hass, api, mqtt_client, inst_ref, device_id, name):
        self.hass = hass
        self.api = api
        self.mqtt_client = mqtt_client
        self.inst_ref = inst_ref
        self.device_id = device_id
        self._attr_unique_id = f"mysair_switch_{inst_ref}_{device_id}"
        self._attr_name = name
        self._is_on = False
        # Último modo AC conocido para encender preservándolo: "0"=calor, "1"=frío.
        # Por defecto calor (encender NUNCA debe forzar frío). Ver docs/protocol-findings.md.
        self._last_ac_mode = "0"
        self._unsub = None
        self._init_command_feedback()
        self._init_availability()

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
    def is_on(self):
        return self._is_on

    async def async_turn_on(self, **kwargs):
        previous_is_on = self._is_on
        try:
            # Encender = enviar comando 'mode' (no existe power "1"). Preservamos el
            # último modo calor/frío conocido; por defecto calor. Ver docs/protocol-findings.md.
            _LOGGER.debug(f"[MySair Switch] 🔛 Encendiendo {self.name} (modo {self._last_ac_mode})")
            response = await self.hass.async_add_executor_job(
                self.api.send_zone_command,
                self.inst_ref,
                self.device_id,
                "mode",
                self._last_ac_mode,
                22.0
            )

            def _revert(previous=previous_is_on):
                self._is_on = previous

            self._track_command_confirmation(response, revert_fn=_revert)
            self._is_on = True
            self.async_write_ha_state()
        except Exception as e:
            _LOGGER.error(f"[MySair Switch] ❌ Error al encender {self.name}: {e}")

    async def async_turn_off(self, **kwargs):
        previous_is_on = self._is_on
        try:
            _LOGGER.debug(f"[MySair Switch] ⛔ Apagando {self.name}")
            response = await self.hass.async_add_executor_job(
                self.api.send_zone_command,
                self.inst_ref,
                self.device_id,
                "power"
            )

            def _revert(previous=previous_is_on):
                self._is_on = previous

            self._track_command_confirmation(response, revert_fn=_revert)
            self._is_on = False
            self.async_write_ha_state()
        except Exception as e:
            _LOGGER.error(f"[MySair Switch] ❌ Error al apagar {self.name}: {e}")

    async def async_added_to_hass(self):
        self._unsub = async_dispatcher_connect(
            self.hass, signal_zone_update(self.inst_ref, self.device_id), self._handle_zone_update
        )
        self._start_feedback_listener()

    async def async_will_remove_from_hass(self):
        if self._unsub:
            self._unsub()
            self._unsub = None
        self._stop_feedback_listener()
        self._stop_availability()

    @callback
    def _handle_zone_update(self, zone):
        self._mark_status_received()
        self._clear_pending_command()
        self._is_on = bool(zone.get("is_on"))
        # Recordar el modo AC (calor/frío) para preservarlo al reencender.
        if zone.get("is_ac") and zone.get("mode_raw") in ("0", "1"):
            self._last_ac_mode = zone.get("mode_raw")
        _LOGGER.debug(f"[MySair Switch] 🔄 Estado {self.name}: {'ON' if self._is_on else 'OFF'}")
        self.async_write_ha_state()


class MySairFloorSwitch(CommandFeedbackMixin, AvailabilityMixin, SwitchEntity):
    """Entidad Switch para encender/apagar el suelo radiante de una zona (F4).

    No existe un comando dedicado en el protocolo: la app oficial recalcula
    el valor de `m` (preservando calor/frío y el estado de AC) y lo envía
    con el mismo comando `mode` que ya usa `climate.py`
    (`toggleRadiatingFloor`/`setModeHeat`, ver docs/protocol-findings.md §4).
    """

    _attr_icon = "mdi:heat-wave"

    def __init__(self, hass, api, mqtt_client, inst_ref, device_id, name):
        self.hass = hass
        self.api = api
        self.mqtt_client = mqtt_client
        self.inst_ref = inst_ref
        self.device_id = device_id
        self._attr_unique_id = f"mysair_floor_{inst_ref}_{device_id}"
        self._attr_name = name
        self._is_on = False
        self._allow_floor = False
        # Estado actual conocido para preservarlo al recalcular 'm'.
        self._current_is_heat = True
        self._current_is_ac = True
        self._current_temp_target = 22.0
        self._unsub = None
        self._init_command_feedback()
        self._init_availability()

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
    def is_on(self):
        return self._is_on

    @property
    def available(self):
        # El suelo radiante no es una capacidad universal (a diferencia del
        # power on/off): la entidad existe siempre, pero se marca "no
        # disponible" para zonas sin capacidad de suelo, igual que el resto
        # de entidades ya están "no disponibles" hasta el primer status.
        return super().available and self._allow_floor

    async def async_turn_on(self, **kwargs):
        await self._async_set_floor(True)

    async def async_turn_off(self, **kwargs):
        await self._async_set_floor(False)

    async def _async_set_floor(self, floor_on):
        previous_is_on = self._is_on
        try:
            new_mode = compute_mode_value(self._current_is_heat, self._current_is_ac, floor_on)
            _LOGGER.debug(f"[MySair Switch] 🌡️ Cambiando suelo a {'ON' if floor_on else 'OFF'} en {self.name} (m={new_mode})")
            response = await self.hass.async_add_executor_job(
                self.api.send_zone_command,
                self.inst_ref,
                self.device_id,
                "mode",
                new_mode,
                self._current_temp_target,
            )

            def _revert(previous=previous_is_on):
                self._is_on = previous

            self._track_command_confirmation(response, revert_fn=_revert)
            self._is_on = floor_on
            self.async_write_ha_state()
        except Exception as e:
            _LOGGER.error(f"[MySair Switch] ❌ Error al cambiar el suelo de {self.name}: {e}")

    async def async_added_to_hass(self):
        self._unsub = async_dispatcher_connect(
            self.hass, signal_zone_update(self.inst_ref, self.device_id), self._handle_zone_update
        )
        self._start_feedback_listener()

    async def async_will_remove_from_hass(self):
        if self._unsub:
            self._unsub()
            self._unsub = None
        self._stop_feedback_listener()
        self._stop_availability()

    @callback
    def _handle_zone_update(self, zone):
        self._mark_status_received()
        self._clear_pending_command()
        self._allow_floor = bool(zone.get("allow_floor"))
        self._is_on = bool(zone.get("is_floor"))
        if zone.get("is_heat") is not None:
            self._current_is_heat = bool(zone.get("is_heat"))
        if zone.get("is_ac") is not None:
            self._current_is_ac = bool(zone.get("is_ac"))
        if zone.get("temp_target") is not None:
            self._current_temp_target = zone.get("temp_target")
        _LOGGER.debug(f"[MySair Switch] 🔄 Suelo {self.name}: {'ON' if self._is_on else 'OFF'}")
        self.async_write_ha_state()

