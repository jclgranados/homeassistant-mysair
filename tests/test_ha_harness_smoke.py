"""Smoke test P2: valida que el harness de Home Assistant descubre custom_components/mysair.

Solo corre con pytest-homeassistant-custom-component instalado (ver Dockerfile.test);
en el entorno P0/P1 sin HA se salta (pytest.importorskip).
"""

import pytest

pytest.importorskip("homeassistant")

from homeassistant.loader import async_get_custom_components


async def test_mysair_is_discovered_as_custom_component(hass, enable_custom_integrations):
    components = await async_get_custom_components(hass)
    assert "mysair" in components
