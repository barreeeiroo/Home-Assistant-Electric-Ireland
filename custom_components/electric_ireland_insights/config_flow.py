"""Config flow for Electric Ireland Insights integration."""
import logging
import voluptuous as vol
from typing import Any

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .api import ElectricIrelandScraper
from .const import DOMAIN, NAME

LOGGER = logging.getLogger(__name__)


@callback
def configured_instances(hass):
    """Return a set of configured instances."""
    return set(entry.data['account_number']
               for entry
               in hass.config_entries.async_entries(DOMAIN))


class ElectricIrelandInsightsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Electric Ireland Insights."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            if user_input["account_number"] in configured_instances(self.hass):
                errors["base"] = "account_number_exists"
            else:
                # Validate credentials before creating entry
                try:
                    await self.hass.async_add_executor_job(
                        self._validate_credentials,
                        user_input["username"],
                        user_input["password"],
                        user_input["account_number"]
                    )
                    return self.async_create_entry(title=NAME, data=user_input)
                except Exception as err:
                    LOGGER.error(f"Failed to validate credentials: {err}")
                    errors["base"] = "cannot_connect"
                    # Don't abort - allow user to try again with different credentials

        data_schema = vol.Schema({
            vol.Required("username"): str,
            vol.Required("password"): str,
            vol.Required("account_number"): str,
        })

        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    def _validate_credentials(self, username: str, password: str, account_number: str) -> None:
        """Validate credentials by attempting to login.

        Args:
            username: Electric Ireland account username
            password: Electric Ireland account password
            account_number: Electric Ireland account number

        Raises:
            Exception: If credentials are invalid or login fails
        """
        scraper = ElectricIrelandScraper(username, password, account_number)
        scraper.refresh_credentials()
        if not scraper.scraper:
            raise Exception("Failed to authenticate with Electric Ireland")
