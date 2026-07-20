"""Tests P2 de ciclo de vida (harness de Home Assistant, ver Dockerfile.test).

Sin red real: MySairAPI y MySairMQTTClient van parcheados. El objetivo es
validar el ciclo de vida (setup/unload, ConfigEntryAuthFailed/NotReady), no
el protocolo (ya cubierto en tests/test_api.py, tests/test_status_parser.py).
"""

import pytest

pytest.importorskip("homeassistant")

from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mysair.const import DOMAIN
from custom_components.mysair.api import MySairAPI, MySairAuthError, MySairConnectionError
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
    monkeypatch.setattr(MySairAPI, "get_installations", lambda self, location_id: [{"reference": "INST_A"}])
    monkeypatch.setattr(MySairAPI, "get_devices", lambda self, ref: [{"reference": "DEV_1", "name": "Salon"}])
    monkeypatch.setattr(MySairAPI, "send_instruction", lambda self, instruction: {"msg": "Creado", "error": []})
    monkeypatch.setattr(MySairMQTTClient, "start", lambda self: None)


def _make_entry(refresh_token="OLD_REFRESH", extra_data=None):
    data = {"email": "user@example.com", "refresh_token": refresh_token}
    if extra_data:
        data.update(extra_data)
    return MockConfigEntry(domain=DOMAIN, unique_id="user@example.com", data=data)


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
    entry = _make_entry(extra_data={"password": "plaintext-leftover", "access_token": "OLD_TOKEN"})
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
        MySairAPI, "refresh_tokens", _mock_refresh_tokens_raises(MySairAuthError("expired"))
    )
    entry = _make_entry()
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_setup_entry_connection_error_retries(hass, monkeypatch):
    monkeypatch.setattr(
        MySairAPI, "refresh_tokens", _mock_refresh_tokens_raises(MySairConnectionError("boom"))
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
