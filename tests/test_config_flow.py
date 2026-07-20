"""Tests P2 del config flow (harness de Home Assistant, ver Dockerfile.test)."""

import pytest

pytest.importorskip("homeassistant")

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mysair.const import DOMAIN
from custom_components.mysair.api import MySairAPI, MySairAuthError, MySairConnectionError


def _mock_login_ok(refresh_token="REFRESH_NEW"):
    def _login(self):
        self.access_token = "ACCESS_NEW"
        self.refresh_token_value = refresh_token
        return True

    return _login


def _mock_login_raises(exc):
    def _login(self):
        raise exc

    return _login


async def test_user_flow_success_creates_entry(hass, monkeypatch):
    monkeypatch.setattr(MySairAPI, "login", _mock_login_ok())

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": "user@example.com", "password": "secret"}
    )
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["title"] == "MySair"
    # A6: no se persiste password ni access_token, solo email + refresh_token.
    assert result2["data"] == {"email": "user@example.com", "refresh_token": "REFRESH_NEW"}


async def test_user_flow_invalid_auth(hass, monkeypatch):
    monkeypatch.setattr(MySairAPI, "login", _mock_login_raises(MySairAuthError("bad creds")))

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": "user@example.com", "password": "wrong"}
    )
    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "invalid_auth"}


async def test_user_flow_cannot_connect(hass, monkeypatch):
    monkeypatch.setattr(MySairAPI, "login", _mock_login_raises(MySairConnectionError("boom")))

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": "user@example.com", "password": "secret"}
    )
    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_user_flow_duplicate_account_aborts(hass, monkeypatch):
    # C2: la misma cuenta (mismo email, normalizado en minúsculas) no se puede añadir dos veces.
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.com",
        data={"email": "user@example.com", "refresh_token": "OLD"},
    )
    existing.add_to_hass(hass)

    monkeypatch.setattr(MySairAPI, "login", _mock_login_ok())

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": "USER@example.com", "password": "secret"}
    )
    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] == "already_configured"


async def test_reauth_flow_success_updates_refresh_token(hass, monkeypatch):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.com",
        data={"email": "user@example.com", "refresh_token": "STALE"},
    )
    entry.add_to_hass(hass)

    monkeypatch.setattr(MySairAPI, "login", _mock_login_ok(refresh_token="REFRESH_AFTER_REAUTH"))

    result = await entry.start_reauth_flow(hass)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"password": "the-new-password"}
    )
    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] == "reauth_successful"
    assert entry.data["refresh_token"] == "REFRESH_AFTER_REAUTH"


async def test_reauth_flow_invalid_auth_shows_error(hass, monkeypatch):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.com",
        data={"email": "user@example.com", "refresh_token": "STALE"},
    )
    entry.add_to_hass(hass)

    monkeypatch.setattr(MySairAPI, "login", _mock_login_raises(MySairAuthError("still bad")))

    result = await entry.start_reauth_flow(hass)
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"password": "still-wrong"}
    )
    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": "invalid_auth"}
    # El refresh_token no cambia si la reautenticación falla.
    assert entry.data["refresh_token"] == "STALE"
