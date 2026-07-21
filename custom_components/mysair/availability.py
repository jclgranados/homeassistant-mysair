"""Disponibilidad de entidad basada en la frescura de los datos MQTT (C5).

Mixin compartido por las entidades climate/sensor/switch. Sin heartbeat de
aplicación (ver docs/known-unknowns.md #11) no hay forma directa de saber si
el dispositivo sigue "vivo"; en vez de mostrar datos potencialmente obsoletos
como si fueran en tiempo real, la entidad se marca no disponible si no ha
recibido un ``status`` en más de ``MQTT_STALE_AFTER_SECONDS``. Empieza no
disponible hasta el primer status tras el arranque/recarga.

Con ``should_poll=False`` nada vuelve a evaluar ``available`` por su cuenta:
si el MQTT se cae y no llega más ningún status, el último estado publicado
se quedaría "disponible" para siempre. Por eso cada status recibido arma
además un timer (``async_call_later``) que fuerza un `async_write_ha_state`
al cabo de ``MQTT_STALE_AFTER_SECONDS` si no ha llegado nada más nuevo.
"""

from datetime import timedelta

import homeassistant.util.dt as dt_util
from homeassistant.core import callback
from homeassistant.helpers.event import async_call_later

from .const import MQTT_STALE_AFTER_SECONDS


class AvailabilityMixin:
    """Requiere que la clase que lo use llame a ``self._init_availability()``
    y a ``self._stop_availability()`` en ``async_will_remove_from_hass``."""

    _attr_should_poll = False

    def _init_availability(self):
        self._last_status_at = None
        self._cancel_stale_check = None

    def _stop_availability(self):
        if self._cancel_stale_check:
            self._cancel_stale_check()
            self._cancel_stale_check = None

    def _mark_status_received(self):
        self._last_status_at = dt_util.utcnow()
        if self._cancel_stale_check:
            self._cancel_stale_check()
        self._cancel_stale_check = async_call_later(
            self.hass, MQTT_STALE_AFTER_SECONDS, self._on_stale_check
        )

    @callback
    def _on_stale_check(self, now):
        """Fuerza una reevaluación de `available` cuando los datos podrían haber caducado."""
        self._cancel_stale_check = None
        self.async_write_ha_state()

    @property
    def available(self):
        if self._last_status_at is None:
            return False
        return dt_util.utcnow() - self._last_status_at < timedelta(
            seconds=MQTT_STALE_AFTER_SECONDS
        )
