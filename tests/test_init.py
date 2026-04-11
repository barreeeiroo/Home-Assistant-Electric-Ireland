"""Tests for the Electric Ireland Insights __init__ setup."""

import logging
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState

from custom_components.electric_ireland_insights.const import DOMAIN

TEST_METER_IDS = {"partner": "P1", "contract": "C1", "premise": "PR1"}


async def test_setup_entry_success(recorder_mock, hass, enable_custom_integrations, mock_config_entry, caplog):
    caplog.set_level(logging.DEBUG, logger="custom_components.electric_ireland_insights")
    mock_config_entry.add_to_hass(hass)
    with (
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.authenticate = AsyncMock(return_value=(TEST_METER_IDS, TEST_METER_IDS))
        mock_api_instance.get_bill_periods = AsyncMock(return_value=[])
        mock_api_instance.get_hourly_usage = AsyncMock(return_value=[])
        mock_api_class.return_value = mock_api_instance

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        assert "Setting up Electric Ireland entry" in caplog.text
        assert "Platforms forwarded" in caplog.text
        assert mock_config_entry.state == ConfigEntryState.LOADED


async def test_setup_entry_config_entry_not_ready(recorder_mock, hass, enable_custom_integrations, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    with (
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
    ):
        from custom_components.electric_ireland_insights.exceptions import CannotConnect

        mock_api_instance = AsyncMock()
        mock_api_instance.authenticate = AsyncMock(side_effect=CannotConnect("timeout"))
        mock_api_class.return_value = mock_api_instance

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        assert mock_config_entry.state == ConfigEntryState.SETUP_RETRY


async def test_unload_entry(recorder_mock, hass, enable_custom_integrations, mock_config_entry, caplog):
    caplog.set_level(logging.DEBUG, logger="custom_components.electric_ireland_insights")
    mock_config_entry.add_to_hass(hass)
    with (
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.authenticate = AsyncMock(return_value=(TEST_METER_IDS, TEST_METER_IDS))
        mock_api_instance.get_bill_periods = AsyncMock(return_value=[])
        mock_api_instance.get_hourly_usage = AsyncMock(return_value=[])
        mock_api_class.return_value = mock_api_instance

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        assert mock_config_entry.state == ConfigEntryState.LOADED

        await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        assert "Unloading Electric Ireland entry" in caplog.text
        assert mock_config_entry.state == ConfigEntryState.NOT_LOADED


async def test_migrate_v1_to_v2(recorder_mock, hass, enable_custom_integrations, caplog):
    """Test migration from V1 (no cached IDs) to V2 (with None cached IDs)."""
    caplog.set_level(logging.DEBUG, logger="custom_components.electric_ireland_insights")
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    v1_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "test@test.com",
            "password": "testpass",
            "account_number": "100000001",
        },
        version=1,
        unique_id="100000001",
    )
    v1_entry.add_to_hass(hass)

    with (
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.authenticate = AsyncMock(return_value=(TEST_METER_IDS, TEST_METER_IDS))
        mock_api_instance.get_bill_periods = AsyncMock(return_value=[])
        mock_api_instance.get_hourly_usage = AsyncMock(return_value=[])
        mock_api_class.return_value = mock_api_instance

        await hass.config_entries.async_setup(v1_entry.entry_id)
        await hass.async_block_till_done()

    entry = hass.config_entries.async_get_entry(v1_entry.entry_id)
    assert "Migrating Electric Ireland entry from version" in caplog.text
    assert entry.version == 2, f"Entry should be migrated to V2, got {entry.version}"
    assert "partner_id" in entry.data
