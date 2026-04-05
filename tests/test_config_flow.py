"""Tests for the Electric Ireland config flow."""

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.electric_ireland_insights.const import DOMAIN
from custom_components.electric_ireland_insights.exceptions import (
    AccountNotFound,
    CannotConnect,
    InvalidAuth,
)


async def test_user_flow_success(recorder_mock, hass, enable_custom_integrations, mock_config_entry):
    """Test successful user flow creates a config entry."""
    with (
        patch("custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.config_flow.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.discover_accounts = AsyncMock(
            return_value=[{"account_number": "100000001", "display_name": "100000001"}]
        )
        mock_api_instance.validate_credentials = AsyncMock(
            return_value={"partner": "p1", "contract": "c1", "premise": "pr1"}
        )
        mock_api_class.return_value = mock_api_instance

        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "test@test.com", "password": "testpass"},
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["step_id"] == "options"

        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {"import_full_history": False},
        )
        assert result3["type"] == FlowResultType.CREATE_ENTRY
        assert result3["data"]["account_number"] == "100000001"
        assert result3["data"]["partner_id"] == "p1"
        assert result3["data"]["contract_id"] == "c1"
        assert result3["data"]["premise_id"] == "pr1"


async def test_user_flow_multi_account(recorder_mock, hass, enable_custom_integrations):
    """Test user flow with multiple accounts shows account selection step."""
    with (
        patch("custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.config_flow.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.discover_accounts = AsyncMock(
            return_value=[
                {"account_number": "111111111", "display_name": "111111111 (Home)"},
                {"account_number": "222222222", "display_name": "222222222 (Office)"},
            ]
        )
        mock_api_instance.validate_credentials = AsyncMock(
            return_value={"partner": "p1", "contract": "c1", "premise": "pr1"}
        )
        mock_api_class.return_value = mock_api_instance

        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "test@test.com", "password": "testpass"},
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["step_id"] == "account"

        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {"account_number": "222222222"},
        )
        assert result3["type"] == FlowResultType.FORM
        assert result3["step_id"] == "options"

        result4 = await hass.config_entries.flow.async_configure(
            result3["flow_id"],
            {"import_full_history": False},
        )
        assert result4["type"] == FlowResultType.CREATE_ENTRY
        assert result4["data"]["account_number"] == "222222222"
        assert result4["data"]["partner_id"] == "p1"


async def test_user_flow_invalid_auth(recorder_mock, hass, enable_custom_integrations):
    """Test user flow shows error on invalid auth."""
    with (
        patch("custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.config_flow.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.discover_accounts = AsyncMock(side_effect=InvalidAuth)
        mock_api_class.return_value = mock_api_instance

        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "bad@test.com", "password": "wrong"},
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["errors"]["base"] == "invalid_auth"


async def test_user_flow_cannot_connect(recorder_mock, hass, enable_custom_integrations):
    """Test user flow shows error on connection failure."""
    with (
        patch("custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.config_flow.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.discover_accounts = AsyncMock(side_effect=CannotConnect)
        mock_api_class.return_value = mock_api_instance

        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "test@test.com", "password": "pass"},
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["errors"]["base"] == "cannot_connect"


async def test_user_flow_account_not_found(recorder_mock, hass, enable_custom_integrations):
    """Test user flow shows error when account not found."""
    with (
        patch("custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.config_flow.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.discover_accounts = AsyncMock(side_effect=AccountNotFound)
        mock_api_class.return_value = mock_api_instance

        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "test@test.com", "password": "pass"},
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["errors"]["base"] == "account_not_found"


async def test_user_flow_duplicate_account(recorder_mock, hass, enable_custom_integrations, mock_config_entry):
    """Test that configuring the same account twice aborts."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch("custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.config_flow.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.discover_accounts = AsyncMock(
            return_value=[{"account_number": "100000001", "display_name": "100000001"}]
        )
        mock_api_instance.validate_credentials = AsyncMock(
            return_value={"partner": "p1", "contract": "c1", "premise": "pr1"}
        )
        mock_api_class.return_value = mock_api_instance

        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "test@test.com", "password": "testpass"},
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["step_id"] == "options"

        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {"import_full_history": False},
        )
        assert result3["type"] == FlowResultType.ABORT
        assert result3["reason"] == "already_configured"


async def test_reauth_flow_success(recorder_mock, hass, enable_custom_integrations, mock_config_entry):
    """Test reauth flow updates credentials successfully."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch("custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.config_flow.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.validate_credentials = AsyncMock(
            return_value={"partner": "p1", "contract": "c1", "premise": "pr1"}
        )
        mock_api_class.return_value = mock_api_instance

        result = await mock_config_entry.start_reauth_flow(hass)
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"password": "newpassword"},
        )
        assert result2["type"] == FlowResultType.ABORT
        assert result2["reason"] == "reauth_successful"


async def test_reauth_flow_invalid_auth(recorder_mock, hass, enable_custom_integrations, mock_config_entry):
    """Test reauth flow shows error on invalid password."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch("custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.config_flow.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.validate_credentials = AsyncMock(side_effect=InvalidAuth)
        mock_api_class.return_value = mock_api_instance

        result = await mock_config_entry.start_reauth_flow(hass)
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"password": "wrongpassword"},
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["errors"]["base"] == "invalid_auth"


async def test_ids_cached_during_config_flow(recorder_mock, hass, enable_custom_integrations):
    """Test that meter IDs discovered during config flow are stored in entry data."""
    meter_ids = {"partner": "P_TEST", "contract": "C_TEST", "premise": "PR_TEST"}

    with (
        patch("custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.config_flow.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.discover_accounts = AsyncMock(
            return_value=[{"account_number": "100000001", "display_name": "100000001"}]
        )
        mock_api_instance.validate_credentials = AsyncMock(return_value=meter_ids)
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.const import DOMAIN

        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "test@test.com", "password": "testpass"},
        )

    assert result2["type"] == FlowResultType.FORM
    assert result2["step_id"] == "options"

    result3 = await hass.config_entries.flow.async_configure(
        result2["flow_id"],
        {"import_full_history": False},
    )
    assert result3["type"] == FlowResultType.CREATE_ENTRY
    assert result3["data"].get("partner_id") == "P_TEST", (
        "partner_id should be stored in entry data after successful config flow"
    )
    assert result3["data"].get("contract_id") == "C_TEST"
    assert result3["data"].get("premise_id") == "PR_TEST"


async def test_reconfigure_success(recorder_mock, hass, enable_custom_integrations):
    """Test reconfigure updates password and clears IDs when password changes."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "test@test.com",
            "password": "oldpass",
            "account_number": "100000001",
            "partner_id": "p1",
            "contract_id": "c1",
            "premise_id": "pr1",
        },
        unique_id="100000001",
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.config_flow.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.validate_credentials = AsyncMock(
            return_value={"partner": "p2", "contract": "c2", "premise": "pr2"}
        )
        mock_api_class.return_value = mock_api_instance

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": entry.entry_id,
            },
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "reconfigure"

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"password": "newpass", "force_rediscovery": False},
        )
        assert result2["type"] == FlowResultType.ABORT
        assert result2["reason"] == "reconfigure_successful"

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.data["password"] == "newpass"
    assert updated.data["partner_id"] is None
    assert updated.data["contract_id"] is None
    assert updated.data["premise_id"] is None


async def test_reconfigure_force_rediscovery(recorder_mock, hass, enable_custom_integrations):
    """Test reconfigure clears cached IDs when force_rediscovery is True."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "test@test.com",
            "password": "testpass",
            "account_number": "100000001",
            "partner_id": "p1",
            "contract_id": "c1",
            "premise_id": "pr1",
        },
        unique_id="100000001",
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.config_flow.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.validate_credentials = AsyncMock(
            return_value={"partner": "p2", "contract": "c2", "premise": "pr2"}
        )
        mock_api_class.return_value = mock_api_instance

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": entry.entry_id,
            },
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"password": "testpass", "force_rediscovery": True},
        )
        assert result2["type"] == FlowResultType.ABORT
        assert result2["reason"] == "reconfigure_successful"

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.data["password"] == "testpass"
    assert updated.data["partner_id"] is None
    assert updated.data["contract_id"] is None
    assert updated.data["premise_id"] is None


async def test_reconfigure_auth_error(recorder_mock, hass, enable_custom_integrations):
    """Test reconfigure shows error on invalid credentials."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "test@test.com",
            "password": "testpass",
            "account_number": "100000001",
            "partner_id": "p1",
            "contract_id": "c1",
            "premise_id": "pr1",
        },
        unique_id="100000001",
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.config_flow.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.validate_credentials = AsyncMock(side_effect=InvalidAuth)
        mock_api_class.return_value = mock_api_instance

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": entry.entry_id,
            },
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"password": "wrongpass", "force_rediscovery": False},
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["errors"]["base"] == "invalid_auth"


async def test_user_flow_unexpected_exception(recorder_mock, hass, enable_custom_integrations):
    """Test user flow shows error on unexpected exception."""
    with (
        patch("custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.config_flow.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.discover_accounts = AsyncMock(side_effect=RuntimeError("boom"))
        mock_api_class.return_value = mock_api_instance

        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "test@test.com", "password": "pass"},
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["errors"]["base"] == "cannot_connect"


async def test_reauth_cannot_connect(recorder_mock, hass, enable_custom_integrations, mock_config_entry):
    """Test reauth flow shows error on connection failure."""
    mock_config_entry.add_to_hass(hass)
    with (
        patch("custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.config_flow.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.validate_credentials = AsyncMock(side_effect=CannotConnect)
        mock_api_class.return_value = mock_api_instance

        result = await mock_config_entry.start_reauth_flow(hass)
        result2 = await hass.config_entries.flow.async_configure(result["flow_id"], {"password": "pass"})
        assert result2["type"] == FlowResultType.FORM
        assert result2["errors"]["base"] == "cannot_connect"


async def test_reauth_account_not_found(recorder_mock, hass, enable_custom_integrations, mock_config_entry):
    """Test reauth flow shows error when account not found."""
    mock_config_entry.add_to_hass(hass)
    with (
        patch("custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.config_flow.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.validate_credentials = AsyncMock(side_effect=AccountNotFound)
        mock_api_class.return_value = mock_api_instance

        result = await mock_config_entry.start_reauth_flow(hass)
        result2 = await hass.config_entries.flow.async_configure(result["flow_id"], {"password": "pass"})
        assert result2["type"] == FlowResultType.FORM
        assert result2["errors"]["base"] == "account_not_found"


async def test_reauth_unexpected_exception(recorder_mock, hass, enable_custom_integrations, mock_config_entry):
    """Test reauth flow shows error on unexpected exception."""
    mock_config_entry.add_to_hass(hass)
    with (
        patch("custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.config_flow.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.validate_credentials = AsyncMock(side_effect=RuntimeError("boom"))
        mock_api_class.return_value = mock_api_instance

        result = await mock_config_entry.start_reauth_flow(hass)
        result2 = await hass.config_entries.flow.async_configure(result["flow_id"], {"password": "pass"})
        assert result2["type"] == FlowResultType.FORM
        assert result2["errors"]["base"] == "cannot_connect"


async def test_reconfigure_cannot_connect(recorder_mock, hass, enable_custom_integrations):
    """Test reconfigure flow shows error on connection failure."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "test@test.com",
            "password": "testpass",
            "account_number": "100000001",
            "partner_id": "p1",
            "contract_id": "c1",
            "premise_id": "pr1",
        },
        unique_id="100000001",
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.config_flow.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.validate_credentials = AsyncMock(side_effect=CannotConnect)
        mock_api_class.return_value = mock_api_instance
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"password": "newpass", "force_rediscovery": False}
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["errors"]["base"] == "cannot_connect"


async def test_reconfigure_account_not_found(recorder_mock, hass, enable_custom_integrations):
    """Test reconfigure flow shows error when account not found."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "test@test.com",
            "password": "testpass",
            "account_number": "100000001",
            "partner_id": "p1",
            "contract_id": "c1",
            "premise_id": "pr1",
        },
        unique_id="100000001",
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.config_flow.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.validate_credentials = AsyncMock(side_effect=AccountNotFound)
        mock_api_class.return_value = mock_api_instance
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"password": "newpass", "force_rediscovery": False}
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["errors"]["base"] == "account_not_found"


async def test_reconfigure_unexpected_exception(recorder_mock, hass, enable_custom_integrations):
    """Test reconfigure flow shows error on unexpected exception."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "test@test.com",
            "password": "testpass",
            "account_number": "100000001",
            "partner_id": "p1",
            "contract_id": "c1",
            "premise_id": "pr1",
        },
        unique_id="100000001",
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.config_flow.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.validate_credentials = AsyncMock(side_effect=RuntimeError("boom"))
        mock_api_class.return_value = mock_api_instance
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"password": "newpass", "force_rediscovery": False}
        )
        assert result2["type"] == FlowResultType.FORM
        assert result2["errors"]["base"] == "cannot_connect"


async def test_reconfigure_same_password_stores_meter_ids(recorder_mock, hass, enable_custom_integrations):
    """Test reconfigure with same password and no force_rediscovery stores fresh meter_ids."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "test@test.com",
            "password": "testpass",
            "account_number": "100000001",
            "partner_id": "p1",
            "contract_id": "c1",
            "premise_id": "pr1",
        },
        unique_id="100000001",
        version=2,
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.electric_ireland_insights.config_flow.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.config_flow.async_create_clientsession"),
        patch(
            "custom_components.electric_ireland_insights.async_setup_entry",
            return_value=True,
        ),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.validate_credentials = AsyncMock(
            return_value={"partner": "p_new", "contract": "c_new", "premise": "pr_new"}
        )
        mock_api_class.return_value = mock_api_instance
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"password": "testpass", "force_rediscovery": False},
        )
        assert result2["type"] == FlowResultType.ABORT
        assert result2["reason"] == "reconfigure_successful"

    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.data["partner_id"] == "p_new"
    assert updated.data["contract_id"] == "c_new"
    assert updated.data["premise_id"] == "pr_new"
