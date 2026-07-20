import logging
from homeassistant.components.switch import SwitchEntity
from homeassistant.core import callback

from .availability import AvailabilityMixin
from .command_feedback import CommandFeedbackMixin
from .const import DOMAIN

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
            entities.append(MySairSwitch(hass, api, mqtt_client, inst_ref, dev_id, name))

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
        try:
            # Encender = enviar comando 'mode' (no existe power "1"). Preservamos el
            # último modo calor/frío conocido; por defecto calor. Ver docs/protocol-findings.md.
            _LOGGER.info(f"[MySair Switch] 🔛 Encendiendo {self.name} (modo {self._last_ac_mode})")
            response = await self.hass.async_add_executor_job(
                self.api.send_zone_command,
                self.inst_ref,
                self.device_id,
                "mode",
                self._last_ac_mode,
                22.0
            )
            self._track_command_confirmation(response)
            self._is_on = True
            self.async_write_ha_state()
        except Exception as e:
            _LOGGER.error(f"[MySair Switch] ❌ Error al encender {self.name}: {e}")

    async def async_turn_off(self, **kwargs):
        try:
            _LOGGER.info(f"[MySair Switch] ⛔ Apagando {self.name}")
            response = await self.hass.async_add_executor_job(
                self.api.send_zone_command,
                self.inst_ref,
                self.device_id,
                "power"
            )
            self._track_command_confirmation(response)
            self._is_on = False
            self.async_write_ha_state()
        except Exception as e:
            _LOGGER.error(f"[MySair Switch] ❌ Error al apagar {self.name}: {e}")

    async def async_added_to_hass(self):
        self._unsub = self.hass.bus.async_listen(f"{DOMAIN}_update", self._handle_mqtt_update)
        self._start_feedback_listener()

    async def async_will_remove_from_hass(self):
        if self._unsub:
            self._unsub()
            self._unsub = None
        self._stop_feedback_listener()
        self._stop_availability()

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
            self._mark_status_received()
            self._is_on = bool(zone.get("is_on"))
            # Recordar el modo AC (calor/frío) para preservarlo al reencender.
            if zone.get("is_ac") and zone.get("mode_raw") in ("0", "1"):
                self._last_ac_mode = zone.get("mode_raw")
            _LOGGER.debug(f"[MySair Switch] 🔄 Estado {self.name}: {'ON' if self._is_on else 'OFF'}")
            self.async_write_ha_state()

