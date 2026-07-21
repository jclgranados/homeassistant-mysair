"""Tests P2 de ciclo de vida (harness de Home Assistant, ver Dockerfile.test).

Sin red real: MySairAPI y MySairMQTTClient van parcheados. El objetivo es
validar el ciclo de vida (setup/unload, ConfigEntryAuthFailed/NotReady), no
el protocolo (ya cubierto en tests/test_api.py, tests/test_status_parser.py).
"""

import pytest

pytest.importorskip("homeassistant")

from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mysair.const import DOMAIN, SERVICE_STOP_INSTALLATION
from custom_components.mysair.api import (
    MySairAPI,
    MySairAuthError,
    MySairConnectionError,
)
from custom_components.mysair.mqtt_handler import MySairMQTTClient


def _mock_refresh_tokens_ok(self):
    self.access_token = "ACCESS"
    self.refresh_token_value = "REFRESH_ROTATED"
    self._notify_tokens()  # el código real lo llama tras renovar; el mock reemplaza el método entero
    return True


def _mock_refresh_tokens_raises(exc):
    def _refresh(self):
        raise exc

    return _refresh


def _patch_happy_api(monkeypatch):
    monkeypatch.setattr(MySairAPI, "refresh_tokens", _mock_refresh_tokens_ok)
    monkeypatch.setattr(MySairAPI, "get_locations", lambda self: [{"id": 1001}])
    monkeypatch.setattr(
        MySairAPI,
        "get_installations",
        lambda self, location_id: [{"reference": "INST_A"}],
    )
    monkeypatch.setattr(
        MySairAPI,
        "get_devices",
        lambda self, ref: [{"reference": "DEV_1", "name": "Salon"}],
    )
    monkeypatch.setattr(
        MySairAPI,
        "send_instruction",
        lambda self, instruction: {"msg": "Creado", "error": []},
    )
    monkeypatch.setattr(MySairMQTTClient, "start", lambda self: None)


def _make_entry(refresh_token="OLD_REFRESH", extra_data=None):
    data = {"email": "user@example.com", "refresh_token": refresh_token}
    if extra_data:
        data.update(extra_data)
    return MockConfigEntry(domain=DOMAIN, unique_id="user@example.com", data=data)


def _fire_status(hass, ctl, zone):
    hass.bus.async_fire(
        f"{DOMAIN}_update",
        {
            "topic": f"pro/v1/get/ctl/{ctl}/status",
            "data": {"ctl": ctl, "zones": [zone]},
        },
    )


async def test_setup_entry_success(hass, monkeypatch):
    _patch_happy_api(monkeypatch)
    entry = _make_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    stored = hass.data[DOMAIN][entry.entry_id]
    assert stored["installations"] == ["INST_A"]
    assert stored["devices"] == {"INST_A": [{"reference": "DEV_1", "name": "Salon"}]}
    # El refresh_token rotado se persiste en la config entry (callback on_tokens_refreshed).
    assert entry.data["refresh_token"] == "REFRESH_ROTATED"


async def test_setup_entry_migrates_legacy_password_out(hass, monkeypatch):
    # A6: entradas creadas antes del cambio guardaban password/access_token en claro.
    _patch_happy_api(monkeypatch)
    entry = _make_entry(
        extra_data={"password": "plaintext-leftover", "access_token": "OLD_TOKEN"}
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert "password" not in entry.data
    assert "access_token" not in entry.data


async def test_setup_entry_missing_refresh_token_triggers_reauth(hass, monkeypatch):
    entry = _make_entry(refresh_token=None)
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_setup_entry_invalid_session_triggers_reauth(hass, monkeypatch):
    monkeypatch.setattr(
        MySairAPI,
        "refresh_tokens",
        _mock_refresh_tokens_raises(MySairAuthError("expired")),
    )
    entry = _make_entry()
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_setup_entry_connection_error_retries(hass, monkeypatch):
    monkeypatch.setattr(
        MySairAPI,
        "refresh_tokens",
        _mock_refresh_tokens_raises(MySairConnectionError("boom")),
    )
    entry = _make_entry()
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_entry_no_locations_retries(hass, monkeypatch):
    _patch_happy_api(monkeypatch)
    monkeypatch.setattr(MySairAPI, "get_locations", lambda self: [])
    entry = _make_entry()
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_entry_no_installations_retries(hass, monkeypatch):
    _patch_happy_api(monkeypatch)
    monkeypatch.setattr(MySairAPI, "get_installations", lambda self, location_id: [])
    entry = _make_entry()
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload_entry_cleans_up(hass, monkeypatch):
    _patch_happy_api(monkeypatch)
    stop_calls = []
    monkeypatch.setattr(MySairMQTTClient, "stop", lambda self: stop_calls.append(True))

    entry = _make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    assert entry.entry_id not in hass.data.get(DOMAIN, {})
    assert stop_calls == [True]


async def test_reload_entry_does_not_duplicate_entities_or_service(hass, monkeypatch):
    # P3 (docs/testing-strategy.md): un reload no debe dejar entidades
    # duplicadas, listeners colgados del coordinador/servicio anterior, ni
    # romper la actualización vía MQTT tras volver a cargar.
    _patch_happy_api(monkeypatch)
    monkeypatch.setattr(MySairMQTTClient, "stop", lambda self: None)

    entry = _make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.async_entity_ids("climate") == ["climate.salon"]
    assert hass.services.has_service(DOMAIN, SERVICE_STOP_INSTALLATION)

    # El coordinador/dispatcher se re-engancharon limpio tras el reload.
    _fire_status(
        hass,
        "INST_A",
        {"zone_id": "DEV_1", "is_on": True, "is_heat": True, "is_cool": False},
    )
    await hass.async_block_till_done()
    assert hass.states.get("climate.salon").state != "unavailable"


# --- SERVICIO mysair.stop_installation (F5) ---


async def test_stop_installation_service_calls_api(hass, monkeypatch):
    _patch_happy_api(monkeypatch)
    calls = []
    monkeypatch.setattr(
        MySairAPI,
        "send_installation_command",
        lambda self, ctl, command_type: calls.append((ctl, command_type)),
    )

    entry = _make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    calls.clear()  # descarta la llamada "status" del refresco periódico (__init__.py)

    assert hass.services.has_service(DOMAIN, SERVICE_STOP_INSTALLATION)
    await hass.services.async_call(
        DOMAIN, SERVICE_STOP_INSTALLATION, {"installation_ref": "INST_A"}, blocking=True
    )

    assert calls == [("INST_A", "stop")]


async def test_stop_installation_service_unknown_installation_raises(hass, monkeypatch):
    _patch_happy_api(monkeypatch)
    entry = _make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_STOP_INSTALLATION,
            {"installation_ref": "NO_EXISTE"},
            blocking=True,
        )


async def test_stop_installation_service_removed_after_last_unload(hass, monkeypatch):
    _patch_happy_api(monkeypatch)
    monkeypatch.setattr(MySairMQTTClient, "stop", lambda self: None)

    entry = _make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.services.has_service(DOMAIN, SERVICE_STOP_INSTALLATION)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert not hass.services.has_service(DOMAIN, SERVICE_STOP_INSTALLATION)


# --- Varias instalaciones en una cuenta / cambio de topología (P3) ---


async def test_setup_entry_multiple_installations(hass, monkeypatch):
    # El código de descubrimiento (bucle sobre `installations`) y el filtro
    # del coordinador por `ctl` ya estaban preparados para N>1 instalaciones;
    # hasta ahora solo se probaba con una.
    _patch_happy_api(monkeypatch)
    monkeypatch.setattr(
        MySairAPI,
        "get_installations",
        lambda self, location_id: [{"reference": "INST_A"}, {"reference": "INST_B"}],
    )

    def _get_devices(self, ref):
        if ref == "INST_A":
            return [{"reference": "DEV_1", "name": "Salon"}]
        return [{"reference": "DEV_2", "name": "Dormitorio"}]

    monkeypatch.setattr(MySairAPI, "get_devices", _get_devices)

    entry = _make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    stored = hass.data[DOMAIN][entry.entry_id]
    assert stored["installations"] == ["INST_A", "INST_B"]
    assert stored["devices"] == {
        "INST_A": [{"reference": "DEV_1", "name": "Salon"}],
        "INST_B": [{"reference": "DEV_2", "name": "Dormitorio"}],
    }
    assert hass.states.get("climate.salon") is not None
    assert hass.states.get("climate.dormitorio") is not None

    # Un status de INST_B solo debe actualizar su propia zona.
    _fire_status(
        hass,
        "INST_B",
        {"zone_id": "DEV_2", "is_on": True, "is_heat": True, "is_cool": False},
    )
    await hass.async_block_till_done()

    assert hass.states.get("climate.dormitorio").state != "unavailable"
    assert (
        hass.states.get("climate.salon").state == "unavailable"
    )  # sin status propio todavía


async def test_topology_change_removes_orphaned_zone_device_and_entities(
    hass, monkeypatch
):
    # _cleanup_stale_zone_devices (__init__.py): si una zona desaparece de
    # get_devices() entre reinicios, su dispositivo (y todas sus entidades:
    # climate + 4 sensores + 2 switches) se elimina del registro en vez de
    # quedar huérfano para siempre; la zona nueva se crea con normalidad.
    _patch_happy_api(monkeypatch)
    monkeypatch.setattr(MySairMQTTClient, "stop", lambda self: None)

    entry = _make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    _fire_status(
        hass,
        "INST_A",
        {"zone_id": "DEV_1", "is_on": True, "is_heat": True, "is_cool": False},
    )
    await hass.async_block_till_done()
    assert hass.states.get("climate.salon").state != "unavailable"

    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id("climate", DOMAIN, "mysair_INST_A_DEV_1")
        == "climate.salon"
    )

    # Cambio de topología: DEV_1 desaparece, aparece DEV_2 nueva.
    monkeypatch.setattr(
        MySairAPI,
        "get_devices",
        lambda self, ref: [{"reference": "DEV_2", "name": "Dormitorio"}],
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    # La zona nueva se crea y funciona con normalidad.
    assert hass.states.get("climate.dormitorio") is not None
    _fire_status(
        hass,
        "INST_A",
        {"zone_id": "DEV_2", "is_on": True, "is_heat": True, "is_cool": False},
    )
    await hass.async_block_till_done()
    assert hass.states.get("climate.dormitorio").state != "unavailable"

    # El dispositivo y las entidades de la zona eliminada ya no existen.
    assert (
        registry.async_get_entity_id("climate", DOMAIN, "mysair_INST_A_DEV_1") is None
    )
    assert (
        registry.async_get_entity_id("sensor", DOMAIN, "mysair_temp_INST_A_DEV_1")
        is None
    )
    assert hass.states.get("climate.salon") is None
