"""Shared HTTP fixtures for integration tests.

The ONLY fake is the network — aioresponses intercepts HTTP calls.
All application code (API parsing, config flow, coordinator, recorder) runs for real.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

import aiohttp
import pytest
from aioresponses import CallbackResult


@pytest.fixture
async def session():
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(), cookie_jar=aiohttp.CookieJar()) as s:
        yield s


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_URL = "https://youraccountonline.electricireland.ie"
PARTNER, CONTRACT, PREMISE = "RP1", "RC1", "RPR1"
ACCOUNT_1 = "111111111"
ACCOUNT_2 = "222222222"
GAS_ACCOUNT = "333333333"


# ---------------------------------------------------------------------------
# HTML builders — mirror the real Electric Ireland markup
# ---------------------------------------------------------------------------
LOGIN_PAGE = (
    '<html><body><input name="Source" value="src_token"/><input name="rvt" value="rvt_from_input"/></body></html>'
)
LOGIN_PAGE_NO_SOURCE = "<html><body><p>nothing here</p></body></html>"


def acct_div(
    acct: str,
    icon: str = "account-electricity-icon",
    label: str | None = None,
    partner: str = PARTNER,
) -> str:
    """One ``<div class="my-accounts__item">`` block."""
    lbl = f'<h3 class="account-label">{label}</h3>' if label else ""
    return (
        f'<div class="my-accounts__item">'
        f'<p class="account-number">{acct}</p>'
        f'<h2 class="{icon}"></h2>{lbl}'
        f'<form action="/Accounts/OnEvent">'
        f'<input name="AccountId" value="{partner}"/>'
        f'<input name="triggers_event" value="AccountSelection.ToInsights"/>'
        f"</form></div>"
    )


def page(*divs: str) -> str:
    """Wrap account divs in a full HTML page."""
    return f"<html><body>{''.join(divs)}</body></html>"


def insights_page(p: str = PARTNER, c: str = CONTRACT, pr: str = PREMISE) -> str:
    """The MeterInsight page returned after account selection."""
    return (
        f'<html><body><div id="modelData" '
        f'data-partner="{p}" data-contract="{c}" data-premise="{pr}">'
        f"</div></body></html>"
    )


# ---------------------------------------------------------------------------
# JSON builders — MeterInsight hourly-usage responses
# ---------------------------------------------------------------------------
EMPTY_HOURLY: dict = {"isSuccess": True, "data": []}


def hourly_json(
    date: datetime,
    tariff: str = "flatRate",
    consumption: float = 0.5,
    cost: float = 0.10,
) -> dict:
    """Single-datapoint hourly-usage response for *date*."""
    end = date.replace(hour=1, minute=0, second=0, microsecond=0)
    buckets: dict = {tariff: {"consumption": consumption, "cost": cost}}
    for k in ("flatRate", "offPeak", "midPeak", "onPeak"):
        buckets.setdefault(k, None)
    return {
        "isSuccess": True,
        "data": [{"endDate": end.strftime("%Y-%m-%dT%H:%M:%SZ"), **buckets}],
    }


def make_hourly_callback(
    tariff_schedule: dict[int, str] | str = "flatRate",
    consumption_pattern: list[float] | None = None,
):
    """Factory for aioresponses callbacks with configurable tariff per hour.

    Args:
        tariff_schedule: Either a single tariff string (applied to all hours),
            or a dict mapping hour (0-23) to tariff key string.
            Hours not in the dict get no tariff bucket (all nulls).
    """

    def _callback(url, **kwargs):
        date_str = url.query.get("date", "2024-01-20")
        dt = datetime.fromisoformat(date_str).replace(tzinfo=UTC)
        prefix = dt.strftime("%Y-%m-%dT")

        data = []
        for hour in range(24):
            if isinstance(tariff_schedule, str):
                active: str | None = tariff_schedule
            elif hour in tariff_schedule:
                active = tariff_schedule[hour]
            else:
                active = None

            buckets: dict = {"flatRate": None, "offPeak": None, "midPeak": None, "onPeak": None}
            if active is not None:
                consumption = (
                    consumption_pattern[hour] if consumption_pattern is not None else round(0.5 + hour * 0.05, 2)
                )
                buckets[active] = {
                    "consumption": round(consumption, 4),
                    "cost": round(0.10 + hour * 0.01, 2),
                }

            data.append(
                {
                    "startDate": f"{prefix}{hour:02d}:00:00Z",
                    "endDate": f"{prefix}{hour:02d}:59:59Z",
                    **buckets,
                }
            )

        return CallbackResult(
            status=200,
            body=json.dumps({"isSuccess": True, "data": data}),
            content_type="application/json",
        )

    return _callback


def hourly_callback(url, **kwargs):
    """``aioresponses`` callback — returns date-aware hourly data."""
    date_str = url.query.get("date", "2024-01-20")
    date = datetime.fromisoformat(date_str).replace(tzinfo=UTC)
    return CallbackResult(
        status=200,
        body=json.dumps(hourly_json(date)),
        content_type="application/json",
    )


# ---------------------------------------------------------------------------
# Full HTTP-chain helper
# ---------------------------------------------------------------------------
def mock_ei_http(
    m,
    dashboard_html: str,
    *,
    insights_html: str | None = None,
    hourly: dict | None = EMPTY_HOURLY,
    hourly_cb=None,
    partner: str = PARTNER,
    contract: str = CONTRACT,
    premise: str = PREMISE,
    include_bill_period: bool = True,
    bill_period_response: dict | None = None,
) -> None:
    """Register every Electric Ireland endpoint inside an ``aioresponses`` block.

    * GET  /              → login page  (with ``rvt`` cookie)
    * POST /              → dashboard   (account list)
    * POST /Accounts/OnEvent → insights page
    * GET  /MeterInsight/…/hourly-usage → JSON data  (optional)
    * GET  /MeterInsight/…/bill-period → JSON data  (optional)
    """
    m.get(f"{BASE_URL}/", body=LOGIN_PAGE, repeat=True, headers={"Set-Cookie": "rvt=tok1"})
    m.post(f"{BASE_URL}/", body=dashboard_html, repeat=True)
    m.post(f"{BASE_URL}/Accounts/OnEvent", body=insights_html or insights_page(partner, contract, premise), repeat=True)

    url_re = re.compile(rf"{re.escape(BASE_URL)}/MeterInsight/{partner}/{contract}/{premise}/hourly-usage")
    if hourly_cb:
        m.get(url_re, callback=hourly_cb, repeat=True)
    elif hourly is not None:
        m.get(url_re, payload=hourly, repeat=True, content_type="application/json")

    if include_bill_period:
        bill_re = re.compile(rf"{re.escape(BASE_URL)}/MeterInsight/{partner}/{contract}/{premise}/bill-period")
        bp_payload = bill_period_response if bill_period_response is not None else {"isSuccess": True, "data": []}
        m.get(bill_re, payload=bp_payload, repeat=True, content_type="application/json")


SMART_TARIFF_SCHEDULE: dict[int, str] = {
    **{h: "offPeak" for h in range(8)},
    **{h: "onPeak" for h in range(8, 17)},
    **{h: "midPeak" for h in range(17, 23)},
    23: "offPeak",
}

_SMART_CONSUMPTION_PATTERN: list[float] = [
    0.18,
    0.15,
    0.14,
    0.13,
    0.13,
    0.15,
    0.20,
    0.35,
    0.48,
    0.52,
    0.55,
    0.57,
    0.58,
    0.60,
    0.61,
    0.60,
    0.58,
    0.56,
    0.54,
    0.51,
    0.47,
    0.42,
    0.36,
    0.27,
]

_SMART_RATES: dict[str, float] = {
    "offPeak": 0.18,
    "midPeak": 0.24,
    "onPeak": 0.32,
}


def make_smart_tariff_callback():
    def _callback(url, **kwargs):
        date_str = url.query.get("date", "2024-01-20")
        dt = datetime.fromisoformat(date_str).replace(tzinfo=UTC)
        prefix = dt.strftime("%Y-%m-%dT")

        data = []
        for hour in range(24):
            tariff = SMART_TARIFF_SCHEDULE.get(hour, "flatRate")
            consumption = _SMART_CONSUMPTION_PATTERN[hour]
            cost = round(consumption * _SMART_RATES.get(tariff, 0.20), 4)

            buckets: dict = {"flatRate": None, "offPeak": None, "midPeak": None, "onPeak": None}
            buckets[tariff] = {"consumption": round(consumption, 4), "cost": cost}

            data.append(
                {
                    "startDate": f"{prefix}{hour:02d}:00:00Z",
                    "endDate": f"{prefix}{hour:02d}:59:59Z",
                    **buckets,
                }
            )

        return CallbackResult(
            status=200,
            body=json.dumps({"isSuccess": True, "data": data}),
            content_type="application/json",
        )

    return _callback
