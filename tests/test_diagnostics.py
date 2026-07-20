"""Tests P2 de diagnostics.py (harness de Home Assistant, ver Dockerfile.test).

Verifica que el volcado de diagnóstico incluye el estado necesario para
depurar (instalaciones, dispositivos, conexión MQTT) y que redacta
credenciales/tokens antes de exponerlos.
"""

import pytest

pytest.importorskip("homeassistant")

from homeassistant.components.diagnostics import REDACTED
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mysair.const import DOMAIN
from custom_components.mysair.diagnostics import async_get_config_entry_diagnostics
from custom_components.mysair.api import MySairAPI
from custom_components.mysair.mqtt_handler import MySairMQTTClient


def _patch_happy_api(monkeypatch):
    def _mock_refresh_tokens_ok(self):
        self.access_token = "ACCESS_SECRETO"
        self.refresh_token_value = "REFRESH_SECRETO"
        self.aws_credentials = {
            "aws_mqtt_host": "host.iot.eu-west-1.amazonaws.com",
            "aws_default_region": "eu-west-1",
            "aws_access_key_id": "AKIASECRETO",
            "aws_secret_access_key": "SECRETO",
            "aws_security_token": "TOKEN_SECRETO",
            "aws_mqtt_user": "web0000",
            "aws_base_topic": "mysair/web0000",
            "aws_expires_at": 9999999999,
        }
        return True

    monkeypatch.setattr(MySairAPI, "refresh_tokens", _mock_refresh_tokens_ok)
    monkeypatch.setattr(MySairAPI, "get_locations", lambda self: [{"id": 1001}])
    monkeypatch.setattr(MySairAPI, "get_installations", lambda self, location_id: [{"reference": "INST_A"}])
    monkeypatch.setattr(MySairAPI, "get_devices", lambda self, ref: [{"reference": "DEV_1", "name": "Salon"}])
    monkeypatch.setattr(MySairMQTTClient, "start", lambda self: None)


def _make_entry():
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.com",
        data={"email": "user@example.com", "refresh_token": "REFRESH_ENTRY_SECRETO"},
    )


async def test_diagnostics_redacts_sensitive_fields(hass, monkeypatch):
    _patch_happy_api(monkeypatch)
    entry = _make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["entry_data"]["email"] == REDACTED
    assert result["entry_data"]["refresh_token"] == REDACTED
    assert result["api"]["access_token"] == REDACTED
    assert result["api"]["refresh_token_value"] == REDACTED
    assert result["api"]["aws_access_key_id"] == REDACTED
    assert result["api"]["aws_secret_access_key"] == REDACTED
    assert result["api"]["aws_security_token"] == REDACTED
    assert result["api"]["aws_mqtt_user"] == REDACTED
    # Campos no sensibles, útiles para depurar, se conservan sin redactar.
    assert result["api"]["aws_mqtt_host"] == "host.iot.eu-west-1.amazonaws.com"
    assert result["api"]["aws_base_topic"] == "mysair/web0000"


async def test_diagnostics_includes_installations_devices_and_mqtt_state(hass, monkeypatch):
    _patch_happy_api(monkeypatch)
    entry = _make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["installations"] == ["INST_A"]
    assert result["devices"] == {"INST_A": [{"reference": "DEV_1", "name": "Salon"}]}
    assert result["mqtt"]["connected"] is False
    assert result["mqtt"]["reconnect_attempt"] == 0
