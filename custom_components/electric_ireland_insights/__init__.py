"""Electric Ireland Insights integration."""

from __future__ import annotations

import logging

import homeassistant.helpers.config_validation as cv
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import ElectricIrelandCoordinator

_LOGGER = logging.getLogger(DOMAIN)

PLATFORMS = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type ElectricIrelandConfigEntry = ConfigEntry[ElectricIrelandCoordinator]


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    _LOGGER.debug(
        "Migrating Electric Ireland entry from version %s to 2",
        config_entry.version,
    )
    if config_entry.version < 2:
        new_data = {
            **dict(config_entry.data),
            "partner_id": None,
            "contract_id": None,
            "premise_id": None,
        }
        hass.config_entries.async_update_entry(config_entry, data=new_data, version=2)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ElectricIrelandConfigEntry) -> bool:
    coordinator = ElectricIrelandCoordinator(hass, entry)

    entry.runtime_data = coordinator

    await coordinator.async_config_entry_first_refresh()

    entry.async_on_unload(coordinator.async_add_listener(lambda: None))

    if entry.data.get("import_full_history"):
        new_data = {**dict(entry.data), "import_full_history": False}
        hass.config_entries.async_update_entry(entry, data=new_data)
        entry.async_create_background_task(
            hass,
            coordinator.async_tariff_backfill(),
            "electric_ireland_full_history_import",
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ElectricIrelandConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
