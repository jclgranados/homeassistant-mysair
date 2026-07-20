import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .api import MySairAPI, MySairAuthError, MySairConnectionError

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required("email"): str,
        vol.Required("password"): str,
    }
)

REAUTH_SCHEMA = vol.Schema({vol.Required("password"): str})


class MySairConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Flujo de configuración para la integración MySair."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Primer paso del flujo de configuración (inicio de sesión)."""
        errors = {}

        if user_input is not None:
            email = user_input["email"]
            password = user_input["password"]

            api = MySairAPI(email, password)

            try:
                # Ejecuta el login de forma segura en un hilo (sin bloquear el bucle principal)
                await self.hass.async_add_executor_job(api.login)
            except MySairAuthError:
                _LOGGER.error("[MySair ConfigFlow] ❌ Login fallido: credenciales inválidas.")
                errors["base"] = "invalid_auth"
            except MySairConnectionError as e:
                _LOGGER.error(f"[MySair ConfigFlow] ❌ Error conectando con MySair API: {e}")
                errors["base"] = "cannot_connect"
            except Exception as e:
                _LOGGER.exception(f"[MySair ConfigFlow] ❌ Error inesperado: {e}")
                errors["base"] = "unknown"
            else:
                _LOGGER.info("[MySair ConfigFlow] ✅ Login correcto para %s", email)

                await self.async_set_unique_id(email.lower())
                self._abort_if_unique_id_configured()

                # No se guarda el password: solo el refresh_token, usado para
                # renovar la sesión en cada arranque sin credenciales en claro
                # (ver docs/security-and-privacy.md §3).
                return self.async_create_entry(
                    title="MySair",
                    data={
                        "email": email,
                        "refresh_token": api.refresh_token_value,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(self, entry_data) -> ConfigFlowResult:
        """Se dispara cuando la sesión guardada ya no es válida (ConfigEntryAuthFailed)."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None) -> ConfigFlowResult:
        """Pide la contraseña de nuevo para restablecer el refresh_token."""
        errors = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            email = reauth_entry.data.get("email")
            password = user_input["password"]
            api = MySairAPI(email, password)

            try:
                await self.hass.async_add_executor_job(api.login)
            except MySairAuthError:
                errors["base"] = "invalid_auth"
            except MySairConnectionError as e:
                _LOGGER.error(f"[MySair ConfigFlow] ❌ Error conectando con MySair API: {e}")
                errors["base"] = "cannot_connect"
            except Exception as e:
                _LOGGER.exception(f"[MySair ConfigFlow] ❌ Error inesperado en reauth: {e}")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data={**reauth_entry.data, "email": email, "refresh_token": api.refresh_token_value},
                    reason="reauth_successful",
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={"email": reauth_entry.data.get("email", "")},
        )
