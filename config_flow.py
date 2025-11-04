from homeassistant import config_entries
import voluptuous as vol
import aiohttp
from .const import DOMAIN, API_BASE_URL

DATA_SCHEMA = vol.Schema({
    vol.Required("email"): str,
    vol.Required("password"): str
})

class MySairConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    async def async_step_user(self, user_input=None):
        if user_input is not None:
            valid = await self._test_login(user_input["email"], user_input["password"])
            if valid:
                return self.async_create_entry(title="MySair", data=user_input)
            return self.async_abort(reason="invalid_auth")

        return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA)

    async def _test_login(self, email, password):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{API_BASE_URL}user/login",
                    json={"email": email, "password": password}
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return "access_token" in data["entity"]
        except Exception:
            return False

