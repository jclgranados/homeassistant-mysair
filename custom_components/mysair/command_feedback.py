"""Seguimiento de confirmación (ACK) de comandos vía el topic MQTT feedback.

Mixin compartido por MySairThermostat (climate.py) y MySairSwitch (switch.py):
ambas envían comandos por HTTP y necesitan la misma lógica para correlacionar
la respuesta (``orderId``) con el ACK que llega después por MQTT (ver
docs/protocol-findings.md §8, docs/known-unknowns.md #23 — payload confirmado
con captura real de producción el 2026-07-20).

Si no llega confirmación a tiempo, se revierte el estado optimista al último
valor conocido (``revert_fn``, opcional en ``_track_command_confirmation``).
Si llega un status MQTT real antes (nueva verdad confirmada), se descarta
cualquier revert pendiente: ya no hace falta, el dato fresco manda.
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
        self._pending_revert_fn = None
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

    def _track_command_confirmation(self, response, revert_fn=None):
        """Registra el ``orderId`` de un comando recién enviado y arma el timeout.

        ``revert_fn``, si se pasa, es una función sin argumentos que restaura
        el estado local al valor previo al cambio optimista; se llama solo si
        no llega confirmación a tiempo (no escribe el estado, eso lo hace el
        llamador tras invocarla).
        """
        order_id = extract_order_id(response)
        if not order_id:
            return
        if self._cancel_feedback_timeout:
            self._cancel_feedback_timeout()
        self._pending_order_id = order_id
        self._pending_revert_fn = revert_fn
        self._cancel_feedback_timeout = async_call_later(
            self.hass, FEEDBACK_TIMEOUT_SECONDS, self._on_feedback_timeout
        )

    def _clear_pending_command(self):
        """Descarta cualquier comando pendiente de confirmar (y su revert).

        Se llama al recibir un status MQTT real para esta zona: ese dato
        fresco ya es la verdad, no hace falta seguir esperando/revirtiendo.
        """
        self._pending_order_id = None
        self._pending_revert_fn = None
        if self._cancel_feedback_timeout:
            self._cancel_feedback_timeout()
            self._cancel_feedback_timeout = None

    @callback
    def _handle_feedback_event(self, event):
        if event.data.get("ctl") != self.inst_ref:
            return
        if (
            not self._pending_order_id
            or event.data.get("order_id") != self._pending_order_id
        ):
            return
        _LOGGER.debug(
            f"[MySair] ✅ Comando confirmado para {self.name} (orderId={self._pending_order_id})"
        )
        self._pending_order_id = None
        self._pending_revert_fn = None
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

            revert_fn = self._pending_revert_fn
            revert_note = (
                " — revirtiendo al último estado confirmado" if revert_fn else ""
            )
            _LOGGER.warning(
                f"[MySair] ⚠️ Sin confirmación MQTT para {self.name} tras "
                f"{FEEDBACK_TIMEOUT_SECONDS}s ({reason}, orderId={self._pending_order_id})"
                f"{revert_note}"
            )
            self._pending_order_id = None
            self._pending_revert_fn = None
            if revert_fn:
                revert_fn()
                self.async_write_ha_state()
        self._cancel_feedback_timeout = None
