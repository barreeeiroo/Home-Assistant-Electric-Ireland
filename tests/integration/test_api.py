"""API layer integration tests — discovery, tariff parsing, credential validation.

Only fake: HTTP responses via aioresponses.
Real: ElectricIrelandAPI, MeterInsightClient, HTML/JSON parsing.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.electric_ireland_insights.api import (
    ElectricIrelandAPI,
    MeterInsightClient,
)
from custom_components.electric_ireland_insights.const import TARIFF_BUCKET_MAP
from custom_components.electric_ireland_insights.exceptions import (
    AccountNotFound,
    CachedIdsInvalid,
    CannotConnect,
)

from .conftest import (
    ACCOUNT_1,
    ACCOUNT_2,
    BASE_URL,
    CONTRACT,
    EMPTY_HOURLY,
    GAS_ACCOUNT,
    LOGIN_PAGE,
    LOGIN_PAGE_NO_SOURCE,
    PARTNER,
    PREMISE,
    acct_div,
    hourly_json,
    insights_page,
    page,
)

_HOURLY_RE = re.compile(rf"{re.escape(BASE_URL)}/MeterInsight/{PARTNER}/{CONTRACT}/{PREMISE}/hourly-usage")
_IDS = {"partner": PARTNER, "contract": CONTRACT, "premise": PREMISE}


async def test_discover_single_account(session: aiohttp.ClientSession) -> None:
    with aioresponses() as m:
        m.get(f"{BASE_URL}/", body=LOGIN_PAGE, headers={"Set-Cookie": "rvt=tok1"})
        m.post(f"{BASE_URL}/", body=page(acct_div(ACCOUNT_1)))

        accounts = await ElectricIrelandAPI("u@test.com", "pass").discover_accounts(session)

    assert len(accounts) == 1
    assert accounts[0]["account_number"] == ACCOUNT_1
    assert accounts[0]["display_name"] == ACCOUNT_1


async def test_discover_multiple_accounts(session: aiohttp.ClientSession) -> None:
    with aioresponses() as m:
        m.get(f"{BASE_URL}/", body=LOGIN_PAGE, headers={"Set-Cookie": "rvt=tok1"})
        m.post(f"{BASE_URL}/", body=page(acct_div(ACCOUNT_1), acct_div(ACCOUNT_2)))

        accounts = await ElectricIrelandAPI("u@test.com", "p").discover_accounts(session)

    assert len(accounts) == 2
    assert {a["account_number"] for a in accounts} == {ACCOUNT_1, ACCOUNT_2}


async def test_discover_filters_gas_accounts(session: aiohttp.ClientSession) -> None:
    with aioresponses() as m:
        m.get(f"{BASE_URL}/", body=LOGIN_PAGE, headers={"Set-Cookie": "rvt=tok1"})
        m.post(
            f"{BASE_URL}/",
            body=page(
                acct_div(ACCOUNT_1),
                acct_div(GAS_ACCOUNT, icon="account-gas-icon"),
            ),
        )

        accounts = await ElectricIrelandAPI("u@test.com", "p").discover_accounts(session)

    assert len(accounts) == 1
    assert accounts[0]["account_number"] == ACCOUNT_1


async def test_discover_label_in_display_name(session: aiohttp.ClientSession) -> None:
    with aioresponses() as m:
        m.get(f"{BASE_URL}/", body=LOGIN_PAGE, headers={"Set-Cookie": "rvt=tok1"})
        m.post(f"{BASE_URL}/", body=page(acct_div(ACCOUNT_1, label="My Home")))

        accounts = await ElectricIrelandAPI("u@test.com", "p").discover_accounts(session)

    assert accounts[0]["display_name"] == f"{ACCOUNT_1} (My Home)"


async def test_discover_no_label_plain_number(session: aiohttp.ClientSession) -> None:
    with aioresponses() as m:
        m.get(f"{BASE_URL}/", body=LOGIN_PAGE, headers={"Set-Cookie": "rvt=tok1"})
        m.post(f"{BASE_URL}/", body=page(acct_div(ACCOUNT_1)))

        accounts = await ElectricIrelandAPI("u@test.com", "p").discover_accounts(session)

    assert accounts[0]["display_name"] == ACCOUNT_1


async def test_discover_no_account_divs_raises(session: aiohttp.ClientSession) -> None:
    with aioresponses() as m:
        m.get(f"{BASE_URL}/", body=LOGIN_PAGE, headers={"Set-Cookie": "rvt=tok1"})
        m.post(f"{BASE_URL}/", body="<html><body></body></html>")

        with pytest.raises(AccountNotFound):
            await ElectricIrelandAPI("u@test.com", "p").discover_accounts(session)


async def test_discover_gas_only_raises(session: aiohttp.ClientSession) -> None:
    with aioresponses() as m:
        m.get(f"{BASE_URL}/", body=LOGIN_PAGE, headers={"Set-Cookie": "rvt=tok1"})
        m.post(
            f"{BASE_URL}/",
            body=page(acct_div(GAS_ACCOUNT, icon="account-gas-icon")),
        )

        with pytest.raises(AccountNotFound):
            await ElectricIrelandAPI("u@test.com", "p").discover_accounts(session)


async def test_discover_missing_source_token_raises(session: aiohttp.ClientSession) -> None:
    with aioresponses() as m:
        m.get(f"{BASE_URL}/", body=LOGIN_PAGE_NO_SOURCE, headers={"Set-Cookie": "rvt=tok1"})

        with pytest.raises(CannotConnect):
            await ElectricIrelandAPI("u@test.com", "p").discover_accounts(session)


async def test_discover_missing_rvt_cookie_raises(session: aiohttp.ClientSession) -> None:
    with aioresponses() as m:
        m.get(f"{BASE_URL}/", body=LOGIN_PAGE)

        with pytest.raises(CannotConnect):
            await ElectricIrelandAPI("u@test.com", "p").discover_accounts(session)


# ===================================================================
# Credential validation & day-range fetch
# ===================================================================


async def test_validate_credentials_returns_meter_ids(session: aiohttp.ClientSession) -> None:
    db = page(acct_div(ACCOUNT_1))
    with aioresponses() as m:
        m.get(f"{BASE_URL}/", body=LOGIN_PAGE, repeat=True, headers={"Set-Cookie": "rvt=tok1"})
        m.post(f"{BASE_URL}/", body=db, repeat=True)
        m.post(f"{BASE_URL}/Accounts/OnEvent", body=insights_page(), repeat=True)

        ids = await ElectricIrelandAPI("u@test.com", "p", ACCOUNT_1).validate_credentials(session)

    assert ids == _IDS


# ===================================================================
# MeterInsightClient.get_data — tariff parsing
# ===================================================================

_DATE = datetime(2024, 1, 20, tzinfo=UTC)


@pytest.mark.parametrize("tariff", ["flatRate", "offPeak", "midPeak", "onPeak"])
async def test_get_data_parses_tariff(session: aiohttp.ClientSession, tariff: str) -> None:
    with aioresponses() as m:
        m.get(_HOURLY_RE, payload=hourly_json(_DATE, tariff=tariff), content_type="application/json")

        result = await MeterInsightClient(session, _IDS).get_data(_DATE)

    assert len(result) == 1
    assert result[0]["consumption"] == 0.5
    assert result[0]["cost"] == 0.10
    assert result[0]["tariff_bucket"] == TARIFF_BUCKET_MAP[tariff]


async def test_get_data_no_tariff_returns_empty(session: aiohttp.ClientSession) -> None:
    body = {
        "isSuccess": True,
        "data": [
            {
                "endDate": "2024-01-20T01:00:00Z",
                "flatRate": None,
                "offPeak": None,
                "midPeak": None,
                "onPeak": None,
            }
        ],
    }
    with aioresponses() as m:
        m.get(_HOURLY_RE, payload=body, content_type="application/json")
        result = await MeterInsightClient(session, _IDS).get_data(_DATE)

    assert result == []


async def test_get_data_empty_array(session: aiohttp.ClientSession) -> None:
    with aioresponses() as m:
        m.get(_HOURLY_RE, payload=EMPTY_HOURLY, content_type="application/json")
        result = await MeterInsightClient(session, _IDS).get_data(_DATE)

    assert result == []


async def test_get_data_404_raises(session: aiohttp.ClientSession) -> None:
    with aioresponses() as m:
        m.get(_HOURLY_RE, status=404)
        with pytest.raises(CachedIdsInvalid):
            await MeterInsightClient(session, _IDS).get_data(_DATE)


async def test_get_data_success_false_returns_empty(session: aiohttp.ClientSession) -> None:
    with aioresponses() as m:
        m.get(_HOURLY_RE, payload={"isSuccess": False, "message": "fail"}, content_type="application/json")
        result = await MeterInsightClient(session, _IDS).get_data(_DATE)

    assert result == []


async def test_get_data_non_json_raises(session: aiohttp.ClientSession) -> None:
    with aioresponses() as m:
        m.get(_HOURLY_RE, body="<html>Not JSON</html>", content_type="text/html")
        with pytest.raises(CachedIdsInvalid):
            await MeterInsightClient(session, _IDS).get_data(_DATE)


# ---------------------------------------------------------------------------
# rvt token fallback: extract from hidden input when cookie is absent
# ---------------------------------------------------------------------------


async def test_discover_accounts_rvt_from_hidden_input(session: aiohttp.ClientSession) -> None:
    """When rvt cookie is absent, rvt is extracted from the hidden form input."""
    with aioresponses() as m:
        m.get(f"{BASE_URL}/", body=LOGIN_PAGE)
        m.post(f"{BASE_URL}/", body=page(acct_div(ACCOUNT_1)))

        accounts = await ElectricIrelandAPI("u@test.com", "pass").discover_accounts(session)

    assert len(accounts) == 1
    assert accounts[0]["account_number"] == ACCOUNT_1


async def test_validate_credentials_rvt_from_hidden_input(session: aiohttp.ClientSession) -> None:
    """validate_credentials extracts rvt from hidden input when cookie is absent."""
    db = page(acct_div(ACCOUNT_1))
    with aioresponses() as m:
        m.get(f"{BASE_URL}/", body=LOGIN_PAGE)
        m.post(f"{BASE_URL}/", body=db)
        m.post(f"{BASE_URL}/Accounts/OnEvent", body=insights_page(PARTNER, CONTRACT, PREMISE))

        api = ElectricIrelandAPI("u@test.com", "pass", ACCOUNT_1)
        result = await api.validate_credentials(session)

    assert result["partner"] == PARTNER
