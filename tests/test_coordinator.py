"""Tests P2 del coordinador de zona (C1, harness de Home Assistant).

Cubre `MySairCoordinator` en aislamiento: filtrado por instalación propia,
redistribución por zona vía dispatcher, y desuscripción en `stop()`. El
comportamiento observable end-to-end (entidades reaccionando a `mysair_update`)
ya está cubierto por test_entities.py y no cambia con este refactor.
"""

import pytest

pytest.importorskip("homeassistant")

from homeassistant.helpers.dispatcher import async_dispatcher_connect
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mysair.const import DOMAIN
from custom_components.mysair.coordinator import signal_zone_update

from test_entities import _patch_happy_api, _fire_status, _zone


async def _setup_entry(hass, monkeypatch):
    _patch_happy_api(monkeypatch)
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="user@example.com",
        data={"email": "user@example.com", "refresh_token": "OLD_REFRESH"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_coordinator_ignores_ctl_not_in_installation_refs(hass, monkeypatch):
    await _setup_entry(hass, monkeypatch)

    received = []
    async_dispatcher_connect(
        hass, signal_zone_update("OTHER_INST", "DEV_1"), lambda zone: received.append(zone)
    )

    _fire_status(hass, "OTHER_INST", _zone())
    await hass.async_block_till_done()

    assert received == []


async def test_coordinator_dispatches_each_zone_independently_for_multi_zone_message(hass, monkeypatch):
    await _setup_entry(hass, monkeypatch)

    received_dev1 = []
    received_dev2 = []
    async_dispatcher_connect(
        hass, signal_zone_update("INST_A", "DEV_1"), lambda zone: received_dev1.append(zone)
    )
    async_dispatcher_connect(
        hass, signal_zone_update("INST_A", "DEV_2"), lambda zone: received_dev2.append(zone)
    )

    hass.bus.async_fire(
        f"{DOMAIN}_update",
        {
            "topic": "pro/v1/get/ctl/INST_A/status",
            "data": {
                "ctl": "INST_A",
                "zones": [_zone(zone_id="DEV_1"), _zone(zone_id="DEV_2", temp_actual=19.0)],
            },
        },
    )
    await hass.async_block_till_done()

    assert len(received_dev1) == 1 and received_dev1[0]["zone_id"] == "DEV_1"
    assert len(received_dev2) == 1 and received_dev2[0]["temp_actual"] == 19.0


async def test_coordinator_ignores_non_status_topic(hass, monkeypatch):
    await _setup_entry(hass, monkeypatch)

    received = []
    async_dispatcher_connect(
        hass, signal_zone_update("INST_A", "DEV_1"), lambda zone: received.append(zone)
    )

    hass.bus.async_fire(
        f"{DOMAIN}_update",
        {"topic": "pro/v1/get/usr/web0077/feedback", "data": {"ctl": "INST_A", "zones": [_zone()]}},
    )
    await hass.async_block_till_done()

    assert received == []


async def test_coordinator_stop_unsubscribes(hass, monkeypatch):
    entry = await _setup_entry(hass, monkeypatch)
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    received = []
    async_dispatcher_connect(
        hass, signal_zone_update("INST_A", "DEV_1"), lambda zone: received.append(zone)
    )

    coordinator.stop()

    _fire_status(hass, "INST_A", _zone())
    await hass.async_block_till_done()

    assert received == []
