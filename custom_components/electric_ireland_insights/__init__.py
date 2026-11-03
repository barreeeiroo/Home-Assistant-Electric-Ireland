import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import ElectricIrelandScraper
from .const import DOMAIN, DEFAULT_LOOKUP_DAYS

LOGGER = logging.getLogger(DOMAIN)

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Electric Ireland Insights from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    ei_api = ElectricIrelandScraper(
        entry.data["username"],
        entry.data["password"],
        entry.data["account_number"],
    )

    lookup_days = int(entry.data.get("lookup_days", DEFAULT_LOOKUP_DAYS))

    coordinator = DataUpdateCoordinator(
        hass,
        LOGGER,
        name=DOMAIN,
        update_method=lambda: hass.async_add_executor_job(ei_api.fetch_all, lookup_days),
        update_interval=timedelta(hours=1),
    )

    await coordinator.async_config_entry_first_refresh()

    # Store coordinator in hass.data for later use
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward the entry setup to the sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    LOGGER.debug(f"Forwarded config entry setup to {PLATFORMS} platforms.")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # Clean up the stored entry data
        hass.data[DOMAIN].pop(entry.entry_id)
        LOGGER.debug(f"Successfully unloaded config entry {entry.entry_id}.")

    # If no entries remain, clean up the domain
    if not hass.data[DOMAIN]:
        hass.data.pop(DOMAIN)
        LOGGER.debug("No more entries. Cleaned up domain.")

    return unload_ok
