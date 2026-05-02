"""Config flow for Electric Ireland Insights integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import ElectricIrelandAPI
from .const import DOMAIN, NAME
from .exceptions import AccountNotFound, CannotConnect, InvalidAuth

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("username"): str,
        vol.Required("password"): str,
    }
)


class ElectricIrelandInsightsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg,misc]  # HA ConfigFlow metaclass requires domain=; misc covers TypedDict compatibility
    VERSION = 2

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                session = async_create_clientsession(self.hass, cookie_jar=aiohttp.CookieJar())
                api = ElectricIrelandAPI(
                    user_input["username"],
                    user_input["password"],
                )
                accounts = await api.discover_accounts(session)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except AccountNotFound:
                errors["base"] = "account_not_found"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "cannot_connect"
            else:
                self._username = user_input["username"]
                self._password = user_input["password"]
                self._accounts = accounts
                _LOGGER.debug("Credential validation successful, found %d account(s)", len(accounts))

                if len(accounts) == 1:
                    return await self._finish_flow(accounts[0]["account_number"])

                return await self.async_step_account()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_account(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            account_number = user_input.get("account_number")
            if not account_number:
                errors["base"] = "account_not_found"
            else:
                return await self._finish_flow(account_number)

        accounts = self._accounts
        schema = vol.Schema(
            {
                vol.Required("account_number"): vol.In(
                    {acc["account_number"]: acc["display_name"] for acc in accounts}
                ),
            }
        )

        return self.async_show_form(
            step_id="account",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "num_accounts": str(len(accounts)),
            },
        )

    async def _finish_flow(self, account_number: str) -> ConfigFlowResult:
        try:
            session = async_create_clientsession(self.hass, cookie_jar=aiohttp.CookieJar())
            api = ElectricIrelandAPI(
                self._username,
                self._password,
                account_number,
            )
            meter_ids = await api.validate_credentials(session)
        except InvalidAuth:
            return self.async_abort(reason="invalid_auth")
        except CannotConnect:
            return self.async_abort(reason="cannot_connect")
        except AccountNotFound:
            return self.async_abort(reason="account_not_found")
        except Exception:
            _LOGGER.exception("Unexpected exception during account setup")
            return self.async_abort(reason="cannot_connect")

        self._account_number = account_number
        self._meter_ids = meter_ids
        _LOGGER.debug("Account %s validated, proceeding to options", account_number)
        return await self.async_step_options()

    async def async_step_options(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            await self.async_set_unique_id(self._account_number)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"{NAME} ({self._account_number})",
                data={
                    "username": self._username,
                    "password": self._password,
                    "account_number": self._account_number,
                    "partner_id": self._meter_ids.get("partner"),
                    "contract_id": self._meter_ids.get("contract"),
                    "premise_id": self._meter_ids.get("premise"),
                    "import_full_history": user_input.get("import_full_history", False),
                },
            )

        return self.async_show_form(
            step_id="options",
            data_schema=vol.Schema(
                {
                    vol.Optional("import_full_history", default=True): bool,
                }
            ),
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            new_data = {**reauth_entry.data, "password": user_input["password"]}
            try:
                session = async_create_clientsession(self.hass, cookie_jar=aiohttp.CookieJar())
                api = ElectricIrelandAPI(
                    new_data["username"],
                    new_data["password"],
                    new_data["account_number"],
                )
                meter_ids = await api.validate_credentials(session)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except AccountNotFound:
                errors["base"] = "account_not_found"
            except Exception:
                _LOGGER.exception("Unexpected exception during reauth")
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(new_data["account_number"])
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data={
                        **new_data,
                        "partner_id": meter_ids.get("partner"),
                        "contract_id": meter_ids.get("contract"),
                        "premise_id": meter_ids.get("premise"),
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required("password"): str}),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            username = entry.data["username"]
            password = user_input["password"]
            force_rediscovery = user_input.get("force_rediscovery", False)

            try:
                session = async_create_clientsession(self.hass, cookie_jar=aiohttp.CookieJar())
                api = ElectricIrelandAPI(
                    username,
                    password,
                    entry.data["account_number"],
                )
                meter_ids = await api.validate_credentials(session)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except AccountNotFound:
                errors["base"] = "account_not_found"
            except Exception:
                _LOGGER.exception("Unexpected exception during reconfigure")
                errors["base"] = "cannot_connect"
            else:
                password_changed = password != entry.data["password"]
                import_full_history = user_input.get("import_full_history", False)
                if force_rediscovery or password_changed:
                    new_data = {
                        **entry.data,
                        "password": password,
                        "partner_id": None,
                        "contract_id": None,
                        "premise_id": None,
                        "import_full_history": import_full_history,
                    }
                else:
                    new_data = {
                        **entry.data,
                        "password": password,
                        "partner_id": meter_ids.get("partner"),
                        "contract_id": meter_ids.get("contract"),
                        "premise_id": meter_ids.get("premise"),
                        "import_full_history": import_full_history,
                    }
                return self.async_update_reload_and_abort(entry, data=new_data)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required("password"): str,
                        vol.Optional("force_rediscovery", default=False): bool,
                        vol.Optional("import_full_history", default=False): bool,
                    }
                ),
                user_input or {"password": entry.data["password"]},
            ),
            description_placeholders={"username": entry.data["username"]},
            errors=errors,
        )
