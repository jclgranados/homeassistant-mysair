"""Seguimiento de confirmación (ACK) de comandos vía el topic MQTT feedback.

Mixin compartido por MySairThermostat (climate.py) y MySairSwitch (switch.py):
ambas envían comandos por HTTP y necesitan la misma lógica para correlacionar
la respuesta (``orderId``) con el ACK que llega después por MQTT (ver
docs/protocol-findings.md §8, docs/known-unknowns.md #23 — forma exacta del
payload sin confirmar con una captura real de producción).

De momento solo se registra en logs y en el estado interno: NO se revierte el
estado optimista si no llega confirmación (eso es el resto de E7, pendiente
de validar el payload real antes de mutar estado en base a él — ver
docs/execution-plan.md).
"""

import logging

from homeassistant.core import callback
from homeassistant.helpers.event import async_call_later

from .api import extract_order_id
from .const import DOMAIN, FEEDBACK_TIMEOUT_SECONDS

_LOGGER = logging.getLogger(__name__)


class CommandFeedbackMixin:
    """Requiere que la clase que lo use defina ``self.hass``, ``self.inst_ref``, ``self.name``."""

    def _init_command_feedback(self):
        self._pending_order_id = None
        self._cancel_feedback_timeout = None
        self._unsub_feedback = None

    def _start_feedback_listener(self):
        self._unsub_feedback = self.hass.bus.async_listen(
            f"{DOMAIN}_feedback", self._handle_feedback_event
        )

    def _stop_feedback_listener(self):
        if self._unsub_feedback:
            self._unsub_feedback()
            self._unsub_feedback = None
        if self._cancel_feedback_timeout:
            self._cancel_feedback_timeout()
            self._cancel_feedback_timeout = None

    def _track_command_confirmation(self, response):
        """Registra el ``orderId`` de un comando recién enviado y arma el timeout."""
        order_id = extract_order_id(response)
        if not order_id:
            return
        if self._cancel_feedback_timeout:
            self._cancel_feedback_timeout()
        self._pending_order_id = order_id
        self._cancel_feedback_timeout = async_call_later(
            self.hass, FEEDBACK_TIMEOUT_SECONDS, self._on_feedback_timeout
        )

    @callback
    def _handle_feedback_event(self, event):
        if event.data.get("ctl") != self.inst_ref:
            return
        if not self._pending_order_id or event.data.get("order_id") != self._pending_order_id:
            return
        _LOGGER.info(f"[MySair] ✅ Comando confirmado para {self.name} (orderId={self._pending_order_id})")
        self._pending_order_id = None
        if self._cancel_feedback_timeout:
            self._cancel_feedback_timeout()
            self._cancel_feedback_timeout = None

    @callback
    def _on_feedback_timeout(self, now):
        if self._pending_order_id:
            mqtt_client = getattr(self, "mqtt_client", None)
            if mqtt_client is not None and not mqtt_client.connected:
                reason = "MQTT desconectado en ese momento"
            else:
                reason = "con MQTT activo — puede ser un ACK perdido o un problema del backend"
            _LOGGER.warning(
                f"[MySair] ⚠️ Sin confirmación MQTT para {self.name} tras "
                f"{FEEDBACK_TIMEOUT_SECONDS}s ({reason}, orderId={self._pending_order_id})"
            )
            self._pending_order_id = None
        self._cancel_feedback_timeout = None
