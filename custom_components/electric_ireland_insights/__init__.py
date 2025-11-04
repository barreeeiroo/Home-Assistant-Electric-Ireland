"""Electric Ireland Insights integration for Home Assistant.

This integration provides energy consumption and cost data from Electric Ireland
by scraping the insights page and accessing the Bidgely API.
"""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN


LOGGER = logging.getLogger(DOMAIN)

PLATFORMS = ["sensor"]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Electric Ireland Insights component.

    Args:
        hass: Home Assistant instance
        config: Configuration dictionary

    Returns:
        True if setup succeeded
    """
    # Ensure the domain is registered in the hass.data store
    hass.data.setdefault(DOMAIN, {})
    LOGGER.debug("Electric Ireland Insights component initialized.")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Electric Ireland Insights from a config entry.

    Args:
        hass: Home Assistant instance
        entry: Config entry to set up

    Returns:
        True if setup succeeded
    """
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    # Store entry data in hass.data for later use
    hass.data[DOMAIN][entry.entry_id] = entry.data

    # Forward the entry setup to the sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    LOGGER.debug(f"Forwarded config entry setup to {PLATFORMS} platforms.")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    Args:
        hass: Home Assistant instance
        entry: Config entry to unload

    Returns:
        True if unload succeeded
    """
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
