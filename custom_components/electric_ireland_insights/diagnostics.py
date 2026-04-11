"""Diagnostics support for Electric Ireland Insights."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import ElectricIrelandConfigEntry

_LOGGER = logging.getLogger(__name__)

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
    _LOGGER.debug("Collecting diagnostics for Electric Ireland entry")
    coordinator = config_entry.runtime_data

    return {
        "config_entry": async_redact_data(dict(config_entry.data), TO_REDACT),
        "coordinator_data": coordinator.data,
    }
