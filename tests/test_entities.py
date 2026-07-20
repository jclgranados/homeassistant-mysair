"""Tests P2 de entidades y eventos MQTT (harness de Home Assistant, ver Dockerfile.test).

Cubre climate/sensor/switch reaccionando a `mysair_update` y enviando comandos
vía `send_zone_command`. Sin red real: MySairAPI y MySairMQTTClient van
parcheados (igual que en test_init_setup_unload.py).
"""

import logging
from datetime import timedelta

import pytest

pytest.importorskip("homeassistant")

import homeassistant.util.dt as dt_util
from homeassistant.components.climate.const import HVACMode, HVACAction
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.mysair.const import DOMAIN, FEEDBACK_TIMEOUT_SECONDS
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
            order_id = f"order-{len(send_zone_command_calls)}"
            return {"msg": "Creado", "error": [], "entity": {"value": [{"orderId": order_id}]}}

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
        "temp_min": 10.0,
        "temp_max": 30.0,
        "humidity": 45.0,
        "is_on": True,
        "is_standby": False,
        "is_heat": True,
        "is_cool": False,
        "is_ac": True,
        "mode_raw": "0",
        "allow_heat": True,
        "allow_cool": True,
        "allow_fan": True,
        "fan_mode": "4",
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
    # C5: la entidad está "no disponible" hasta el primer status MQTT.
    _fire_status(hass, "INST_A", _zone())
    await hass.async_block_till_done()

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
    # C5: la entidad está "no disponible" hasta el primer status MQTT.
    _fire_status(hass, "INST_A", _zone(is_on=False))
    await hass.async_block_till_done()
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
    # C5: la entidad está "no disponible" hasta el primer status MQTT.
    _fire_status(hass, "INST_A", _zone())
    await hass.async_block_till_done()

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


async def test_humidity_sensor_updates_from_mqtt_event(hass, monkeypatch):
    await _setup_entry(hass, monkeypatch)

    _fire_status(hass, "INST_A", _zone(humidity=52.0))
    await hass.async_block_till_done()

    assert hass.states.get("sensor.salon_humedad").state == "52.0"


async def test_climate_min_max_temp_from_status(hass, monkeypatch):
    await _setup_entry(hass, monkeypatch)
    # Antes del primer status: valores por defecto (10-30).
    assert hass.states.get("climate.salon").attributes["min_temp"] == 10
    assert hass.states.get("climate.salon").attributes["max_temp"] == 30

    _fire_status(hass, "INST_A", _zone(temp_min=16.0, temp_max=28.0))
    await hass.async_block_till_done()

    state = hass.states.get("climate.salon")
    assert state.attributes["min_temp"] == 16.0
    assert state.attributes["max_temp"] == 28.0


async def test_climate_hvac_modes_restricted_by_capabilities(hass, monkeypatch):
    await _setup_entry(hass, monkeypatch)
    # Antes del primer status: los 3 modos por defecto.
    assert set(hass.states.get("climate.salon").attributes["hvac_modes"]) == {
        HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL
    }

    # Zona que solo permite calor (allow_cool=False, p. ej. sin bomba de frío).
    _fire_status(hass, "INST_A", _zone(allow_heat=True, allow_cool=False))
    await hass.async_block_till_done()

    modes = set(hass.states.get("climate.salon").attributes["hvac_modes"])
    assert modes == {HVACMode.OFF, HVACMode.HEAT}
    assert HVACMode.COOL not in modes


async def test_climate_set_hvac_mode_rejected_when_not_allowed(hass, monkeypatch):
    calls = []
    await _setup_entry(hass, monkeypatch, send_zone_command_calls=calls)

    _fire_status(hass, "INST_A", _zone(allow_heat=True, allow_cool=False))
    await hass.async_block_till_done()

    await hass.services.async_call(
        "climate", "set_hvac_mode",
        {"entity_id": "climate.salon", "hvac_mode": "cool"},
        blocking=True,
    )

    # La propia entidad rechaza el modo (no está en self._attr_hvac_modes) y no
    # envía comando. HA solo avisa por log en esta versión (ver climate.py:
    # el guard "if hvac_mode not in self._attr_hvac_modes" es lo que protege).
    assert calls == []
    assert hass.states.get("climate.salon").state != "cool"


# --- Confirmación de comandos vía feedback (E7, docs/protocol-findings.md §8) ---

async def test_climate_command_confirmed_via_feedback(hass, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    calls = []
    await _setup_entry(hass, monkeypatch, send_zone_command_calls=calls)
    _fire_status(hass, "INST_A", _zone())
    await hass.async_block_till_done()

    await hass.services.async_call(
        "climate", "set_hvac_mode",
        {"entity_id": "climate.salon", "hvac_mode": "heat"},
        blocking=True,
    )
    assert len(calls) == 1

    hass.bus.async_fire(f"{DOMAIN}_feedback", {"order_id": "order-1", "ctl": "INST_A", "raw": {}})
    await hass.async_block_till_done()

    assert "Comando confirmado" in caplog.text


async def test_climate_command_feedback_from_other_installation_ignored(hass, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    calls = []
    await _setup_entry(hass, monkeypatch, send_zone_command_calls=calls)
    _fire_status(hass, "INST_A", _zone())
    await hass.async_block_till_done()

    await hass.services.async_call(
        "climate", "set_hvac_mode",
        {"entity_id": "climate.salon", "hvac_mode": "heat"},
        blocking=True,
    )
    assert len(calls) == 1

    hass.bus.async_fire(f"{DOMAIN}_feedback", {"order_id": "order-1", "ctl": "OTHER_INST", "raw": {}})
    await hass.async_block_till_done()

    assert "Comando confirmado" not in caplog.text


async def test_climate_command_timeout_logs_warning(hass, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    calls = []
    await _setup_entry(hass, monkeypatch, send_zone_command_calls=calls)
    _fire_status(hass, "INST_A", _zone())
    await hass.async_block_till_done()

    await hass.services.async_call(
        "climate", "set_hvac_mode",
        {"entity_id": "climate.salon", "hvac_mode": "heat"},
        blocking=True,
    )
    assert len(calls) == 1

    future = dt_util.utcnow() + timedelta(seconds=FEEDBACK_TIMEOUT_SECONDS + 1)
    async_fire_time_changed(hass, future)
    await hass.async_block_till_done()

    assert "Sin confirmación MQTT" in caplog.text


async def test_switch_command_confirmed_via_feedback(hass, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    calls = []
    await _setup_entry(hass, monkeypatch, send_zone_command_calls=calls)
    _fire_status(hass, "INST_A", _zone())
    await hass.async_block_till_done()

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.salon"}, blocking=True
    )
    assert len(calls) == 1

    hass.bus.async_fire(f"{DOMAIN}_feedback", {"order_id": "order-1", "ctl": "INST_A", "raw": {}})
    await hass.async_block_till_done()

    assert "Comando confirmado" in caplog.text


# --- Disponibilidad por frescura de datos MQTT (C5) ---

async def test_entities_unavailable_until_first_status(hass, monkeypatch):
    await _setup_entry(hass, monkeypatch)

    assert hass.states.get("climate.salon").state == "unavailable"
    assert hass.states.get("switch.salon").state == "unavailable"
    assert hass.states.get("sensor.salon_temperatura_actual").state == "unavailable"
    assert hass.states.get("sensor.salon_humedad").state == "unavailable"


async def test_entities_become_available_after_status(hass, monkeypatch):
    await _setup_entry(hass, monkeypatch)

    _fire_status(hass, "INST_A", _zone())
    await hass.async_block_till_done()

    assert hass.states.get("climate.salon").state != "unavailable"
    assert hass.states.get("switch.salon").state != "unavailable"
    assert hass.states.get("sensor.salon_temperatura_actual").state != "unavailable"


async def test_availability_mixin_disables_polling():
    from custom_components.mysair.availability import AvailabilityMixin
    assert AvailabilityMixin._attr_should_poll is False


async def test_entities_become_unavailable_after_stale_timeout(hass, monkeypatch):
    # `available` vuelve a llamar a dt_util.utcnow() al evaluarse; para que la
    # comprobación de caducidad dé positivo hace falta congelar el reloj real
    # (async_fire_time_changed solo dispara el callback programado, no mueve
    # el reloj que `available` lee de forma independiente).
    freezegun = pytest.importorskip("freezegun")
    from custom_components.mysair.const import MQTT_STALE_AFTER_SECONDS

    with freezegun.freeze_time(dt_util.utcnow()) as frozen:
        await _setup_entry(hass, monkeypatch)
        _fire_status(hass, "INST_A", _zone())
        await hass.async_block_till_done()
        assert hass.states.get("climate.salon").state != "unavailable"

        frozen.tick(timedelta(seconds=MQTT_STALE_AFTER_SECONDS + 1))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()

    assert hass.states.get("climate.salon").state == "unavailable"
    assert hass.states.get("switch.salon").state == "unavailable"


# --- Velocidad de ventilador (F2, docs/protocol-findings.md §9) ---

async def test_climate_fan_mode_updates_from_mqtt_event(hass, monkeypatch):
    await _setup_entry(hass, monkeypatch)

    _fire_status(hass, "INST_A", _zone(allow_fan=True, fan_mode="2"))
    await hass.async_block_till_done()

    state = hass.states.get("climate.salon")
    assert state.attributes["fan_mode"] == "2"
    assert set(state.attributes["fan_modes"]) == {"1", "2", "3", "auto"}


async def test_climate_fan_mode_auto_mapping(hass, monkeypatch):
    await _setup_entry(hass, monkeypatch)

    _fire_status(hass, "INST_A", _zone(allow_fan=True, fan_mode="4"))
    await hass.async_block_till_done()

    assert hass.states.get("climate.salon").attributes["fan_mode"] == "auto"


async def test_climate_fan_mode_none_when_not_allowed(hass, monkeypatch):
    await _setup_entry(hass, monkeypatch)

    _fire_status(hass, "INST_A", _zone(allow_fan=False, fan_mode="2"))
    await hass.async_block_till_done()

    state = hass.states.get("climate.salon")
    assert state.attributes["fan_modes"] == []


async def test_climate_fan_mode_none_when_wire_is_zero(hass, monkeypatch):
    await _setup_entry(hass, monkeypatch)

    _fire_status(hass, "INST_A", _zone(allow_fan=True, fan_mode="0"))
    await hass.async_block_till_done()

    assert hass.states.get("climate.salon").attributes["fan_mode"] is None


async def test_climate_set_fan_mode_sends_command(hass, monkeypatch):
    calls = []
    await _setup_entry(hass, monkeypatch, send_zone_command_calls=calls)
    _fire_status(hass, "INST_A", _zone(allow_fan=True, fan_mode="1"))
    await hass.async_block_till_done()

    await hass.services.async_call(
        "climate", "set_fan_mode",
        {"entity_id": "climate.salon", "fan_mode": "auto"},
        blocking=True,
    )

    assert calls[-1] == {
        "ctl": "INST_A", "device": "DEV_1", "command_type": "fanspeed", "value": "4", "temperature": None
    }
    assert hass.states.get("climate.salon").attributes["fan_mode"] == "auto"


async def test_climate_set_fan_mode_rejected_when_not_allowed(hass, monkeypatch):
    # A diferencia de hvac_mode (que en esta versión de HA solo avisa), la
    # validación de fan_mode sí rechaza con ServiceValidationError a nivel de
    # servicio si fan_modes está vacío: la llamada ni siquiera llega a
    # climate.async_set_fan_mode.
    calls = []
    await _setup_entry(hass, monkeypatch, send_zone_command_calls=calls)
    _fire_status(hass, "INST_A", _zone(allow_fan=False))
    await hass.async_block_till_done()

    with pytest.raises(Exception):
        await hass.services.async_call(
            "climate", "set_fan_mode",
            {"entity_id": "climate.salon", "fan_mode": "auto"},
            blocking=True,
        )

    assert calls == []
