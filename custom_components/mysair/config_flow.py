import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN
from .api import MySairAPI

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required("email"): str,
        vol.Required("password"): str,
    }
)


class MySairConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Flujo de configuración para la integración MySair."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Primer paso del flujo de configuración (inicio de sesión)."""
        errors = {}

        if user_input is not None:
            email = user_input["email"]
            password = user_input["password"]

            api = MySairAPI(email, password)

            try:
                # Ejecuta el login de forma segura en un hilo (sin bloquear el bucle principal)
                result = await self.hass.async_add_executor_job(api.login)

                if not result or not api.access_token:
                    _LOGGER.error("[MySair ConfigFlow] ❌ Login fallido: sin token o sin respuesta.")
                    errors["base"] = "invalid_auth"
                else:
                    _LOGGER.info("[MySair ConfigFlow] ✅ Login correcto para %s", email)

                    return self.async_create_entry(
                        title="MySair",
                        data={
                            "email": email,
                            "password": password,
                            "access_token": api.access_token,
                            "refresh_token": api.refresh_token_value,
                        },
                    )

            except Exception as e:
                _LOGGER.exception("[MySair ConfigFlow] ❌ Error conectando con MySair API: %s", e)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
        )

