"""Tests P2 de entidades y eventos MQTT (harness de Home Assistant, ver Dockerfile.test).

Cubre climate/sensor/switch reaccionando a `mysair_update` y enviando comandos
vía `send_zone_command`. Sin red real: MySairAPI y MySairMQTTClient van
parcheados (igual que en test_init_setup_unload.py).
"""

import pytest

pytest.importorskip("homeassistant")

from homeassistant.components.climate.const import HVACMode, HVACAction
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mysair.const import DOMAIN
from custom_components.mysair.api import MySairAPI
from custom_components.mysair.mqtt_handler import MySairMQTTClient


def _patch_happy_api(monkeypatch, send_zone_command_calls=None):
    def _refresh_tokens(self):
        self.access_token = "ACCESS"
        self.refresh_token_value = "REFRESH"
        return True

    monkeypatch.setattr(MySairAPI, "refresh_tokens", _refresh_tokens)
    monkeypatch.setattr(MySairAPI, "get_locations", lambda self: [{"id": 1001}])
    monkeypatch.setattr(MySairAPI, "get_installations", lambda self, location_id: [{"reference": "INST_A"}])
    monkeypatch.setattr(MySairAPI, "get_devices", lambda self, ref: [{"reference": "DEV_1", "name": "Salon"}])
    monkeypatch.setattr(MySairAPI, "send_instruction", lambda self, instruction: {"msg": "Creado", "error": []})
    monkeypatch.setattr(MySairMQTTClient, "start", lambda self: None)

    if send_zone_command_calls is not None:
        def _send_zone_command(self, ctl, device, command_type, value=None, temperature=None):
            send_zone_command_calls.append(
                {"ctl": ctl, "device": device, "command_type": command_type, "value": value, "temperature": temperature}
            )
            return {"msg": "Creado", "error": []}

        monkeypatch.setattr(MySairAPI, "send_zone_command", _send_zone_command)


async def _setup_entry(hass, monkeypatch, send_zone_command_calls=None):
    _patch_happy_api(monkeypatch, send_zone_command_calls)
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="user@example.com",
        data={"email": "user@example.com", "refresh_token": "OLD_REFRESH"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _fire_status(hass, ctl, zone):
    hass.bus.async_fire(
        f"{DOMAIN}_update",
        {"topic": f"pro/v1/get/ctl/{ctl}/status", "data": {"ctl": ctl, "zones": [zone]}},
    )


def _zone(**overrides):
    zone = {
        "zone_id": "DEV_1",
        "temp_actual": 21.5,
        "temp_target": 22.0,
        "is_on": True,
        "is_standby": False,
        "is_heat": True,
        "is_cool": False,
        "is_ac": True,
        "mode_raw": "0",
    }
    zone.update(overrides)
    return zone


async def test_climate_updates_from_mqtt_event(hass, monkeypatch):
    await _setup_entry(hass, monkeypatch)

    _fire_status(hass, "INST_A", _zone(temp_actual=23.0, temp_target=24.0, is_heat=True, is_cool=False))
    await hass.async_block_till_done()

    state = hass.states.get("climate.salon")
    assert state.state == HVACMode.HEAT
    assert state.attributes["current_temperature"] == 23.0
    assert state.attributes["temperature"] == 24.0
    assert state.attributes["hvac_action"] == HVACAction.HEATING


async def test_climate_reflects_off_and_standby(hass, monkeypatch):
    await _setup_entry(hass, monkeypatch)

    _fire_status(hass, "INST_A", _zone(is_on=False))
    await hass.async_block_till_done()
    assert hass.states.get("climate.salon").state == HVACMode.OFF

    _fire_status(hass, "INST_A", _zone(is_on=True, is_standby=True, is_heat=True, is_cool=False))
    await hass.async_block_till_done()
    state = hass.states.get("climate.salon")
    assert state.state == HVACMode.HEAT
    assert state.attributes["hvac_action"] == HVACAction.IDLE


async def test_sensors_update_from_mqtt_event(hass, monkeypatch):
    await _setup_entry(hass, monkeypatch)

    _fire_status(hass, "INST_A", _zone(temp_actual=19.5, temp_target=21.0, is_heat=True, is_cool=False))
    await hass.async_block_till_done()

    assert hass.states.get("sensor.salon_temperatura_actual").state == "19.5"
    assert hass.states.get("sensor.salon_temperatura_consigna").state == "21.0"
    assert hass.states.get("sensor.salon_modo").state == "HEAT"


async def test_mode_sensor_reflects_off(hass, monkeypatch):
    await _setup_entry(hass, monkeypatch)

    _fire_status(hass, "INST_A", _zone(is_on=False))
    await hass.async_block_till_done()

    assert hass.states.get("sensor.salon_modo").state == "OFF"


async def test_switch_updates_from_mqtt_event(hass, monkeypatch):
    await _setup_entry(hass, monkeypatch)

    _fire_status(hass, "INST_A", _zone(is_on=True, is_ac=True, mode_raw="1"))
    await hass.async_block_till_done()
    assert hass.states.get("switch.salon").state == "on"

    _fire_status(hass, "INST_A", _zone(is_on=False))
    await hass.async_block_till_done()
    assert hass.states.get("switch.salon").state == "off"


async def test_event_from_other_installation_is_ignored(hass, monkeypatch):
    await _setup_entry(hass, monkeypatch)
    before = hass.states.get("climate.salon").state

    _fire_status(hass, "OTHER_INST", _zone(is_on=True, is_heat=True, is_cool=False))
    await hass.async_block_till_done()

    assert hass.states.get("climate.salon").state == before


async def test_climate_set_hvac_mode_sends_command(hass, monkeypatch):
    calls = []
    await _setup_entry(hass, monkeypatch, send_zone_command_calls=calls)

    await hass.services.async_call(
        "climate", "set_hvac_mode",
        {"entity_id": "climate.salon", "hvac_mode": "cool"},
        blocking=True,
    )

    assert calls == [
        {"ctl": "INST_A", "device": "DEV_1", "command_type": "mode", "value": "1", "temperature": 22.0}
    ]
    assert hass.states.get("climate.salon").state == HVACMode.COOL


async def test_climate_set_temperature_while_off_does_not_send_command(hass, monkeypatch):
    calls = []
    await _setup_entry(hass, monkeypatch, send_zone_command_calls=calls)
    # La entidad arranca en OFF (estado local por defecto, sin evento MQTT todavía).
    assert hass.states.get("climate.salon").state == HVACMode.OFF

    await hass.services.async_call(
        "climate", "set_temperature",
        {"entity_id": "climate.salon", "temperature": 25.0},
        blocking=True,
    )

    assert calls == []
    assert hass.states.get("climate.salon").attributes["temperature"] == 25.0


async def test_switch_turn_on_off_sends_commands(hass, monkeypatch):
    calls = []
    await _setup_entry(hass, monkeypatch, send_zone_command_calls=calls)

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.salon"}, blocking=True
    )
    assert calls[-1] == {"ctl": "INST_A", "device": "DEV_1", "command_type": "mode", "value": "0", "temperature": 22.0}
    assert hass.states.get("switch.salon").state == "on"

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.salon"}, blocking=True
    )
    assert calls[-1] == {"ctl": "INST_A", "device": "DEV_1", "command_type": "power", "value": None, "temperature": None}
    assert hass.states.get("switch.salon").state == "off"


async def test_switch_preserves_last_ac_mode_from_mqtt(hass, monkeypatch):
    calls = []
    await _setup_entry(hass, monkeypatch, send_zone_command_calls=calls)

    # El estado real llega por MQTT en modo frío ("1"); al reencender debe preservarlo.
    _fire_status(hass, "INST_A", _zone(is_on=True, is_ac=True, mode_raw="1", is_heat=False, is_cool=True))
    await hass.async_block_till_done()

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.salon"}, blocking=True
    )

    assert calls[-1]["value"] == "1"
