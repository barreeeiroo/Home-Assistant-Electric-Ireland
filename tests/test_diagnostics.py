# pyright: reportMissingImports=false
"""Tests for Electric Ireland diagnostics."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.electric_ireland_insights.diagnostics import (
    async_get_config_entry_diagnostics,
)


async def test_diagnostics_structure(hass, enable_custom_integrations, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    mock_coordinator = MagicMock()
    mock_coordinator.data = {
        "last_import": datetime(2026, 3, 23, 12, 0, 0, tzinfo=UTC),
        "datapoint_count": 24,
        "latest_data_timestamp": datetime(2026, 3, 23, 0, 0, tzinfo=UTC),
        "import_error": None,
    }
    mock_config_entry.runtime_data = mock_coordinator

    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    assert "config_entry" in result
    assert "coordinator_data" in result
    assert result["coordinator_data"]["datapoint_count"] == 24


async def test_diagnostics_redacts_credentials(hass, enable_custom_integrations, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    mock_coordinator = MagicMock()
    mock_coordinator.data = {"last_import": None, "datapoint_count": 0}
    mock_config_entry.runtime_data = mock_coordinator

    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    config = result["config_entry"]
    assert config.get("username") != "test@test.com"
    assert config.get("password") != "testpass"
    assert config.get("account_number") == "**REDACTED**"


async def test_diagnostics_redacts_cached_ids(hass, enable_custom_integrations):
    mock_config_entry = MockConfigEntry(
        domain="electric_ireland_insights",
        data={
            "username": "test@test.com",
            "password": "testpass",
            "partner_id": "P123",
            "contract_id": "C456",
            "premise_id": "PR789",
            "account_number": "ACC001",
        },
        unique_id="ACC001",
    )
    mock_config_entry.add_to_hass(hass)
    mock_coordinator = MagicMock()
    mock_coordinator.data = {"last_import": None, "datapoint_count": 0}
    mock_config_entry.runtime_data = mock_coordinator

    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    config = result["config_entry"]
    assert config.get("partner_id") == "**REDACTED**"
    assert config.get("contract_id") == "**REDACTED**"
    assert config.get("premise_id") == "**REDACTED**"
    assert config.get("account_number") == "**REDACTED**"


async def test_diagnostics_coordinator_data_passthrough(hass, enable_custom_integrations, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    mock_coordinator = MagicMock()
    test_data = {
        "last_import": datetime(2026, 3, 23, 12, 0, 0, tzinfo=UTC),
        "datapoint_count": 48,
        "latest_data_timestamp": datetime(2026, 3, 22, 0, 0, tzinfo=UTC),
        "import_error": None,
    }
    mock_coordinator.data = test_data
    mock_config_entry.runtime_data = mock_coordinator

    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    assert result["coordinator_data"] is test_data
