import voluptuous as vol
from typing import Any

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import NumberSelector, NumberSelectorConfig, NumberSelectorMode

from .const import DOMAIN, NAME, DEFAULT_BILLING_DAY, DEFAULT_LOOKUP_DAYS

@callback
def configured_instances(hass):
    """Return a set of configured instances."""
    return set(entry.data['account_number']
               for entry
               in hass.config_entries.async_entries(DOMAIN))


class ElectricIrelandInsightsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
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
            vol.Required("billing_day", default=DEFAULT_BILLING_DAY): NumberSelector(
                NumberSelectorConfig(min=1, max=31, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Required("lookup_days", default=DEFAULT_LOOKUP_DAYS): NumberSelector(
                NumberSelectorConfig(min=7, max=365, step=1, mode=NumberSelectorMode.BOX)
            ),
        })

        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return ElectricIrelandInsightsOptionsFlow()


class ElectricIrelandInsightsOptionsFlow(config_entries.OptionsFlow):
    # No __init__ override — self.config_entry is set automatically by HA 2024.4+

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={
                    **self.config_entry.data,
                    "billing_day": int(user_input["billing_day"]),
                    "lookup_days": int(user_input["lookup_days"]),
                },
            )
            return self.async_create_entry(title="", data={})

        current_billing_day = int(self.config_entry.data.get("billing_day", DEFAULT_BILLING_DAY))
        current_lookup_days = int(self.config_entry.data.get("lookup_days", DEFAULT_LOOKUP_DAYS))

        data_schema = vol.Schema({
            vol.Required("billing_day", default=current_billing_day): NumberSelector(
                NumberSelectorConfig(min=1, max=31, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Required("lookup_days", default=current_lookup_days): NumberSelector(
                NumberSelectorConfig(min=7, max=365, step=1, mode=NumberSelectorMode.BOX)
            ),
        })

        return self.async_show_form(step_id="init", data_schema=data_schema)
