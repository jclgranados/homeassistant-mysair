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
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_component import async_update_entity
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


async def test_malformed_status_payload_does_not_fire_update_event(hass, monkeypatch):
    # E4: mqtt_message_callback (__init__.py) rechaza (no dispara
    # mysair_update) cuando parse_status_payload devuelve None por recibir
    # un payload que no es ni siquiera un dict.
    entry = await _setup_entry(hass, monkeypatch)
    mqtt_client = hass.data[DOMAIN][entry.entry_id]["mqtt"]

    events = []
    hass.bus.async_listen(f"{DOMAIN}_update", events.append)

    mqtt_client.message_callback({"topic": "pro/v1/get/ctl/INST_A/status", "payload": "not-a-dict"})
    await hass.async_block_till_done()

    assert events == []


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


# --- Control de suelo radiante (F4) ---

async def test_floor_switch_unavailable_without_capability(hass, monkeypatch):
    await _setup_entry(hass, monkeypatch)

    _fire_status(hass, "INST_A", _zone(allow_floor=False, is_floor=False))
    await hass.async_block_till_done()

    assert hass.states.get("switch.salon_suelo").state == "unavailable"


async def test_floor_switch_available_and_reflects_state_with_capability(hass, monkeypatch):
    await _setup_entry(hass, monkeypatch)

    _fire_status(hass, "INST_A", _zone(allow_floor=True, is_floor=False))
    await hass.async_block_till_done()
    assert hass.states.get("switch.salon_suelo").state == "off"

    _fire_status(hass, "INST_A", _zone(allow_floor=True, is_floor=True, mode_raw="4", is_ac=True))
    await hass.async_block_till_done()
    assert hass.states.get("switch.salon_suelo").state == "on"


async def test_floor_switch_turn_on_preserves_heat_cool_and_ac(hass, monkeypatch):
    calls = []
    await _setup_entry(hass, monkeypatch, send_zone_command_calls=calls)
    # Zona en AC-only frío (m="1"): activar suelo debe pasar a AC+suelo frío (m="5").
    _fire_status(hass, "INST_A", _zone(
        allow_floor=True, is_floor=False, is_ac=True, mode_raw="1", is_heat=False, is_cool=True, temp_target=23.0,
    ))
    await hass.async_block_till_done()

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.salon_suelo"}, blocking=True
    )

    assert calls[-1] == {
        "ctl": "INST_A", "device": "DEV_1", "command_type": "mode", "value": "5", "temperature": 23.0
    }
    assert hass.states.get("switch.salon_suelo").state == "on"


async def test_floor_switch_turn_off_preserves_heat_cool_and_ac(hass, monkeypatch):
    calls = []
    await _setup_entry(hass, monkeypatch, send_zone_command_calls=calls)
    # AC+suelo calor (m="4"): apagar suelo debe volver a AC-only calor ("0").
    _fire_status(hass, "INST_A", _zone(
        allow_floor=True, is_floor=True, is_ac=True, mode_raw="4", is_heat=True, is_cool=False, temp_target=21.0,
    ))
    await hass.async_block_till_done()

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.salon_suelo"}, blocking=True
    )

    assert calls[-1] == {
        "ctl": "INST_A", "device": "DEV_1", "command_type": "mode", "value": "0", "temperature": 21.0
    }
    assert hass.states.get("switch.salon_suelo").state == "off"


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
    caplog.set_level(logging.DEBUG)
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


async def test_climate_command_timeout_logs_warning_when_mqtt_disconnected(hass, monkeypatch, caplog):
    # MySairMQTTClient.start está parcheado a no-op: mqtt_client.connected
    # se queda en False, como si el MQTT estuviera caído (causa real
    # confirmada en producción de este aviso).
    caplog.set_level(logging.INFO)
    calls = []
    entry = await _setup_entry(hass, monkeypatch, send_zone_command_calls=calls)
    _fire_status(hass, "INST_A", _zone())
    await hass.async_block_till_done()

    mqtt_client = hass.data[DOMAIN][entry.entry_id]["mqtt"]
    assert mqtt_client.connected is False

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
    assert "MQTT desconectado" in caplog.text


async def test_climate_command_timeout_logs_warning_when_mqtt_connected(hass, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    calls = []
    entry = await _setup_entry(hass, monkeypatch, send_zone_command_calls=calls)
    _fire_status(hass, "INST_A", _zone())
    await hass.async_block_till_done()

    mqtt_client = hass.data[DOMAIN][entry.entry_id]["mqtt"]
    mqtt_client.connected = True

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
    assert "con MQTT activo" in caplog.text


async def test_switch_command_confirmed_via_feedback(hass, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
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


# --- E7 parte 2: revertir estado optimista si no llega confirmación ---

async def test_climate_hvac_mode_reverts_on_timeout(hass, monkeypatch):
    calls = []
    await _setup_entry(hass, monkeypatch, send_zone_command_calls=calls)
    _fire_status(hass, "INST_A", _zone(is_on=True, is_heat=True, is_cool=False, mode_raw="0"))
    await hass.async_block_till_done()
    assert hass.states.get("climate.salon").state == HVACMode.HEAT

    await hass.services.async_call(
        "climate", "set_hvac_mode",
        {"entity_id": "climate.salon", "hvac_mode": "cool"},
        blocking=True,
    )
    assert hass.states.get("climate.salon").state == HVACMode.COOL  # optimista

    future = dt_util.utcnow() + timedelta(seconds=FEEDBACK_TIMEOUT_SECONDS + 1)
    async_fire_time_changed(hass, future)
    await hass.async_block_till_done()

    assert hass.states.get("climate.salon").state == HVACMode.HEAT  # revertido


async def test_climate_temperature_reverts_on_timeout(hass, monkeypatch):
    calls = []
    await _setup_entry(hass, monkeypatch, send_zone_command_calls=calls)
    _fire_status(hass, "INST_A", _zone(temp_target=22.0))
    await hass.async_block_till_done()
    assert hass.states.get("climate.salon").attributes["temperature"] == 22.0

    await hass.services.async_call(
        "climate", "set_temperature",
        {"entity_id": "climate.salon", "temperature": 26.0},
        blocking=True,
    )
    assert hass.states.get("climate.salon").attributes["temperature"] == 26.0

    future = dt_util.utcnow() + timedelta(seconds=FEEDBACK_TIMEOUT_SECONDS + 1)
    async_fire_time_changed(hass, future)
    await hass.async_block_till_done()

    assert hass.states.get("climate.salon").attributes["temperature"] == 22.0


async def test_climate_fan_mode_reverts_on_timeout(hass, monkeypatch):
    calls = []
    await _setup_entry(hass, monkeypatch, send_zone_command_calls=calls)
    _fire_status(hass, "INST_A", _zone(allow_fan=True, fan_mode="1"))
    await hass.async_block_till_done()
    assert hass.states.get("climate.salon").attributes["fan_mode"] == "1"

    await hass.services.async_call(
        "climate", "set_fan_mode",
        {"entity_id": "climate.salon", "fan_mode": "auto"},
        blocking=True,
    )
    assert hass.states.get("climate.salon").attributes["fan_mode"] == "auto"

    future = dt_util.utcnow() + timedelta(seconds=FEEDBACK_TIMEOUT_SECONDS + 1)
    async_fire_time_changed(hass, future)
    await hass.async_block_till_done()

    assert hass.states.get("climate.salon").attributes["fan_mode"] == "1"


async def test_switch_reverts_on_timeout(hass, monkeypatch):
    calls = []
    await _setup_entry(hass, monkeypatch, send_zone_command_calls=calls)
    _fire_status(hass, "INST_A", _zone(is_on=False))
    await hass.async_block_till_done()
    assert hass.states.get("switch.salon").state == "off"

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.salon"}, blocking=True
    )
    assert hass.states.get("switch.salon").state == "on"

    future = dt_util.utcnow() + timedelta(seconds=FEEDBACK_TIMEOUT_SECONDS + 1)
    async_fire_time_changed(hass, future)
    await hass.async_block_till_done()

    assert hass.states.get("switch.salon").state == "off"


async def test_climate_pending_revert_cleared_by_real_status(hass, monkeypatch):
    # Si llega un status real antes del timeout, se descarta el revert
    # pendiente: el dato fresco manda, no hay que volver a un valor viejo.
    calls = []
    await _setup_entry(hass, monkeypatch, send_zone_command_calls=calls)
    _fire_status(hass, "INST_A", _zone(is_on=True, is_heat=True, is_cool=False, mode_raw="0"))
    await hass.async_block_till_done()

    await hass.services.async_call(
        "climate", "set_hvac_mode",
        {"entity_id": "climate.salon", "hvac_mode": "cool"},
        blocking=True,
    )
    assert hass.states.get("climate.salon").state == HVACMode.COOL

    # Llega un status real confirmando el cambio (verdad fresca).
    _fire_status(hass, "INST_A", _zone(is_on=True, is_heat=False, is_cool=True, mode_raw="1"))
    await hass.async_block_till_done()
    assert hass.states.get("climate.salon").state == HVACMode.COOL

    future = dt_util.utcnow() + timedelta(seconds=FEEDBACK_TIMEOUT_SECONDS + 1)
    async_fire_time_changed(hass, future)
    await hass.async_block_till_done()

    # Sigue en COOL: no se revierte, el pending ya se limpió con el status real.
    assert hass.states.get("climate.salon").state == HVACMode.COOL


async def test_mqtt_status_sensor_reflects_connection_state(hass, monkeypatch):
    entry = await _setup_entry(hass, monkeypatch)
    mqtt_client = hass.data[DOMAIN][entry.entry_id]["mqtt"]

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"mysair_mqtt_status_{entry.entry_id}")
    assert entity_id is not None
    assert hass.states.get(entity_id).state == "offline"

    mqtt_client.connected = True
    mqtt_client.last_message_at = dt_util.utcnow()
    mqtt_client.parse_strict_count = 3
    mqtt_client.parse_fallback_count = 1
    mqtt_client.parse_error_count = 2
    mqtt_client.total_reconnects = 4
    await async_update_entity(hass, entity_id)

    state = hass.states.get(entity_id)
    assert state.state == "online"
    assert state.attributes["last_update"] is not None
    assert state.attributes["parse_strict_count"] == 3
    assert state.attributes["parse_fallback_count"] == 1
    assert state.attributes["parse_error_count"] == 2
    assert state.attributes["total_reconnects"] == 4
