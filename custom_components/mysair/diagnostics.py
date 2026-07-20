"""Diagnostics de la integración MySair (D1).

Vuelca el estado en memoria (config entry, sesión API, credenciales AWS,
estado del cliente MQTT) para depuración desde la UI de Home Assistant,
redactando cualquier credencial o token antes de exponerlo.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

TO_REDACT_ENTRY = {"email", "password", "access_token", "refresh_token"}
TO_REDACT_API = {
    "access_token",
    "refresh_token_value",
    "aws_access_key_id",
    "aws_secret_access_key",
    "aws_security_token",
    "aws_mqtt_user",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Genera el volcado de diagnóstico para una config entry de MySair."""
    data = hass.data[DOMAIN][entry.entry_id]
    api = data["api"]
    mqtt_client = data["mqtt"]

    api_state = {
        "access_token": api.access_token,
        "refresh_token_value": api.refresh_token_value,
        **(api.aws_credentials or {}),
    }

    mqtt_state = None
    if mqtt_client is not None:
        mqtt_state = {
            "connected": mqtt_client.connected,
            "reconnect_attempt": mqtt_client._reconnect_attempt,
        }

    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT_ENTRY),
        "installations": data["installations"],
        "devices": data["devices"],
        "api": async_redact_data(api_state, TO_REDACT_API),
        "mqtt": mqtt_state,
    }
