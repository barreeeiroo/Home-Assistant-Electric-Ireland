"""Config flow, reauth, and reconfigure integration tests.

Only fake: HTTP responses via aioresponses.
Real: config flow machinery, HA entry lifecycle, API code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from aioresponses import aioresponses
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.electric_ireland_insights.const import DOMAIN

from .conftest import (
    ACCOUNT_1,
    ACCOUNT_2,
    BASE_URL,
    CONTRACT,
    LOGIN_PAGE,
    LOGIN_PAGE_NO_SOURCE,
    PARTNER,
    PREMISE,
    acct_div,
    mock_ei_http,
    page,
)


@pytest.fixture
def mock_setup_entry():
    with patch(
        "custom_components.electric_ireland_insights.async_setup_entry",
        new=AsyncMock(return_value=True),
    ):
        yield


# ===================================================================
# User flow — happy paths
# ===================================================================


async def test_single_account_creates_entry(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
    mock_setup_entry,
) -> None:
    """One electricity account → auto-selected → entry created."""
    db = page(acct_div(ACCOUNT_1))
    with aioresponses() as m:
        mock_ei_http(m, db)
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
        )
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "u@test.com", "password": "pass"},
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "options"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"import_full_history": False},
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["account_number"] == ACCOUNT_1
    assert result["data"]["partner_id"] == PARTNER
    assert result["data"]["contract_id"] == CONTRACT
    assert result["data"]["premise_id"] == PREMISE


async def test_multi_account_shows_selection_then_creates(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
    mock_setup_entry,
) -> None:
    """Two accounts → selection step → pick second → entry created."""
    db = page(acct_div(ACCOUNT_1), acct_div(ACCOUNT_2))
    with aioresponses() as m:
        mock_ei_http(m, db)
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "u@test.com", "password": "pass"},
        )
        assert result["step_id"] == "account"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"account_number": ACCOUNT_2},
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "options"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"import_full_history": False},
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["account_number"] == ACCOUNT_2


# ===================================================================
# User flow — error paths
# ===================================================================


async def test_cannot_connect_shows_form_error(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Missing login tokens → form error, not abort."""
    with aioresponses() as m:
        m.get(f"{BASE_URL}/", body=LOGIN_PAGE_NO_SOURCE, headers={"Set-Cookie": "rvt=tok1"})

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "u@test.com", "password": "pass"},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_no_accounts_shows_form_error(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    with aioresponses() as m:
        m.get(f"{BASE_URL}/", body=LOGIN_PAGE, headers={"Set-Cookie": "rvt=tok1"})
        m.post(f"{BASE_URL}/", body="<html><body></body></html>")

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "u@test.com", "password": "pass"},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "account_not_found"}


async def test_finish_aborts_when_insights_inaccessible(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Discovery succeeds but validate_credentials fails (no modelData) → abort."""
    db = page(acct_div(ACCOUNT_1))
    with aioresponses() as m:
        m.get(f"{BASE_URL}/", body=LOGIN_PAGE, repeat=True, headers={"Set-Cookie": "rvt=tok1"})
        m.post(f"{BASE_URL}/", body=db, repeat=True)
        # OnEvent returns a page WITHOUT modelData → InvalidAuth in _login
        m.post(f"{BASE_URL}/Accounts/OnEvent", body="<html><body><p>Oops</p></body></html>", repeat=True)

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "u@test.com", "password": "pass"},
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "invalid_auth"


async def test_duplicate_account_aborts(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    existing = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "u@test.com", "password": "pass", "account_number": ACCOUNT_1},
        unique_id=ACCOUNT_1,
        version=2,
    )
    existing.add_to_hass(hass)

    db = page(acct_div(ACCOUNT_1))
    with aioresponses() as m:
        mock_ei_http(m, db)
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "u@test.com", "password": "pass"},
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "options"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"import_full_history": False},
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_retry_after_connect_error(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
    mock_setup_entry,
) -> None:
    db = page(acct_div(ACCOUNT_1))
    with aioresponses() as m:
        # Attempt 1: no Source token → CannotConnect
        m.get(f"{BASE_URL}/", body=LOGIN_PAGE_NO_SOURCE, headers={"Set-Cookie": "rvt=tok1"})

        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "u@test.com", "password": "pass"},
        )
        assert result["errors"] == {"base": "cannot_connect"}

        # Attempt 2: everything works (repeat mocks take over)
        mock_ei_http(m, db)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "u@test.com", "password": "pass"},
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "options"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"import_full_history": False},
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY


# ===================================================================
# Reauth
# ===================================================================


async def test_reauth_updates_credentials(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
    mock_setup_entry,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "u@test.com",
            "password": "old",
            "account_number": ACCOUNT_1,
            "partner_id": PARTNER,
            "contract_id": CONTRACT,
            "premise_id": PREMISE,
        },
        unique_id=ACCOUNT_1,
        version=2,
    )
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))
    with aioresponses() as m:
        mock_ei_http(m, db)

        result = await entry.start_reauth_flow(hass)
        assert result["step_id"] == "reauth_confirm"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"password": "new_pass"},
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["password"] == "new_pass"
    assert entry.data["partner_id"] == PARTNER


async def test_reauth_invalid_auth_shows_error(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "u@test.com",
            "password": "old",
            "account_number": ACCOUNT_1,
            "partner_id": PARTNER,
            "contract_id": CONTRACT,
            "premise_id": PREMISE,
        },
        unique_id=ACCOUNT_1,
        version=2,
    )
    entry.add_to_hass(hass)

    with aioresponses() as m:
        m.get(f"{BASE_URL}/", body=LOGIN_PAGE, repeat=True, headers={"Set-Cookie": "rvt=tok1"})
        m.post(f"{BASE_URL}/", body=page(acct_div(ACCOUNT_1)), repeat=True)
        m.post(f"{BASE_URL}/Accounts/OnEvent", body="<html><body>no insights</body></html>", repeat=True)

        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"password": "wrong"},
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


# ===================================================================
# Reconfigure
# ===================================================================


async def test_reconfigure_new_password_clears_ids(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
    mock_setup_entry,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "u@test.com",
            "password": "old",
            "account_number": ACCOUNT_1,
            "partner_id": PARTNER,
            "contract_id": CONTRACT,
            "premise_id": PREMISE,
        },
        unique_id=ACCOUNT_1,
        version=2,
    )
    entry.add_to_hass(hass)

    db = page(acct_div(ACCOUNT_1))
    with aioresponses() as m:
        mock_ei_http(m, db)

        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"password": "new_pass", "force_rediscovery": False},
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["password"] == "new_pass"


async def test_reconfigure_force_rediscovery_clears_ids(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
    mock_setup_entry,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "u@test.com",
            "password": "same",
            "account_number": ACCOUNT_1,
            "partner_id": PARTNER,
            "contract_id": CONTRACT,
            "premise_id": PREMISE,
        },
        unique_id=ACCOUNT_1,
        version=2,
    )
    entry.add_to_hass(hass)

    db = page(acct_div(ACCOUNT_1))
    with aioresponses() as m:
        mock_ei_http(m, db)

        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"password": "same", "force_rediscovery": True},
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.ABORT
    assert entry.data["password"] == "same"


async def test_reconfigure_same_password_keeps_ids(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
    mock_setup_entry,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "u@test.com",
            "password": "same",
            "account_number": ACCOUNT_1,
            "partner_id": "OLD_P",
            "contract_id": "OLD_C",
            "premise_id": "OLD_PR",
        },
        unique_id=ACCOUNT_1,
        version=2,
    )
    entry.add_to_hass(hass)

    db = page(acct_div(ACCOUNT_1))
    with aioresponses() as m:
        mock_ei_http(m, db)

        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"password": "same", "force_rediscovery": False},
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.ABORT
    # Same password, no force → IDs updated from validate_credentials
    assert entry.data["partner_id"] == PARTNER
    assert entry.data["contract_id"] == CONTRACT
    assert entry.data["premise_id"] == PREMISE
