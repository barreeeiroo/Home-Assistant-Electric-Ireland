import voluptuous as vol
from typing import Any

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, NAME

@callback
def configured_instances(hass):
    """Return a set of configured instances."""
    return set(entry.data['account_number']
               for entry
               in hass.config_entries.async_entries(DOMAIN))


class ElectricIrelandInsightsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors = {}

        if user_input is not None:
            if user_input["account_number"] in configured_instances(self.hass):
                errors["base"] = "account_number_exists"
            else:
                return self.async_create_entry(title=NAME, data=user_input)

        data_schema = vol.Schema({
            vol.Required("username"): str,
            vol.Required("password"): str,
            vol.Required("account_number"): str,
        })

        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)
