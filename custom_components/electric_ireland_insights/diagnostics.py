"""Diagnostics support for Electric Ireland Insights."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import ElectricIrelandConfigEntry

TO_REDACT = {
    "username",
    "password",
    "partner_id",
    "contract_id",
    "premise_id",
    "account_number",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    config_entry: ElectricIrelandConfigEntry,
) -> dict[str, Any]:
    coordinator = config_entry.runtime_data

    return {
        "config_entry": async_redact_data(dict(config_entry.data), TO_REDACT),
        "coordinator_data": coordinator.data,
    }
