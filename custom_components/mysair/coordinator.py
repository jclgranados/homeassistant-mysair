"""Coordinador de eventos MQTT por config entry (refactor de eficiencia, C1).

Antes: cada entidad (climate/sensor/switch) se suscribía por su cuenta al
evento de bus `f"{DOMAIN}_update"` y repetía el mismo filtrado manual de
topic/ctl/zone_id sobre la lista completa de zonas del mensaje. Con N zonas
y 6 entidades por zona, un solo mensaje MQTT disparaba 6×N listeners que
recorrían la misma lista de arriba a abajo.

Ahora: una única instancia de `MySairCoordinator` por config entry escucha
`f"{DOMAIN}_update"` una sola vez, filtra por sufijo de topic e instalaciones
propias, y redistribuye cada zona por separado vía
`homeassistant.helpers.dispatcher` con una señal específica por (ctl,
zone_id). Cada entidad se suscribe solo a su propia señal: ya no repite el
filtrado, recibe directamente su zona ya aislada.

El evento `f"{DOMAIN}_update"` (disparado desde `mqtt_message_callback` en
`__init__.py`, sin cambios) sigue siendo el único punto de entrada: tanto el
MQTT real como los tests (`_fire_status` en test_entities.py) funcionan igual
que antes.
"""

import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Prefijo de señal del dispatcher: detalle interno de este mecanismo (solo lo
# usan este módulo y las entidades), no una constante de protocolo/dominio,
# así que vive aquí y no en const.py.
_SIGNAL_ZONE_UPDATE = f"{DOMAIN}_zone_update"


def signal_zone_update(inst_ref: str, device_id: str) -> str:
    """Nombre de señal del dispatcher para una zona concreta.

    Cada entidad de una zona (climate/sensor/switch) se suscribe a esta
    misma señal para recibir solo los datos de su propia zona, ya
    filtrados y aislados por el coordinador.
    """
    return f"{_SIGNAL_ZONE_UPDATE}_{inst_ref}_{device_id}"


class MySairCoordinator:
    """Redistribuye los mensajes `status` de una config entry por zona.

    Sustituye las N×6 suscripciones directas al bus (una por entidad) por
    una única suscripción por config entry; ver docstring del módulo.
    """

    def __init__(self, hass: HomeAssistant, installation_refs: list) -> None:
        self.hass = hass
        self._installation_refs = set(installation_refs)
        self._zones = {}  # (ctl, zone_id) -> último dict de zona recibido
        self._unsub = None

    def start(self) -> None:
        """Se suscribe al evento `mysair_update` (una sola vez por entry)."""
        self._unsub = self.hass.bus.async_listen(
            f"{DOMAIN}_update", self._handle_update
        )

    def stop(self) -> None:
        """Cancela la suscripción al bus."""
        if self._unsub:
            self._unsub()
            self._unsub = None

    @callback
    def _handle_update(self, event) -> None:
        topic = event.data.get("topic", "")
        if not topic.endswith("/status"):
            return

        data = event.data.get("data", {})
        ctl = data.get("ctl")
        if ctl not in self._installation_refs:
            return

        for zone in data.get("zones", []):
            zone_id = zone.get("zone_id")
            if zone_id is None:
                continue
            self._zones[(ctl, zone_id)] = zone
            _LOGGER.debug(
                f"[MySair Coordinator] 📨 Zona {ctl}/{zone_id} actualizada, redistribuyendo"
            )
            async_dispatcher_send(self.hass, signal_zone_update(ctl, zone_id), zone)
