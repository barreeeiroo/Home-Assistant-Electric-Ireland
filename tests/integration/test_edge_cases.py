"""Edge case and error handling integration tests for Tasks 10-14.

Only fake: HTTP responses via aioresponses + dt_now for deterministic dates.
Real: coordinator, API parsing, recorder statistics, config flow.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from functools import partial
from unittest.mock import AsyncMock, patch

import pytest
from aioresponses import CallbackResult, aioresponses
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.electric_ireland_insights.const import DOMAIN
from tests.assertions import (
    assert_cumulative_sums_monotonic,
    assert_hour_aligned,
    assert_no_duplicate_hours,
)

from .conftest import (
    ACCOUNT_1,
    BASE_URL,
    CONTRACT,
    PARTNER,
    PREMISE,
    acct_div,
    insights_page,
    make_hourly_callback,
    mock_ei_http,
    page,
)

STAT_CONSUMPTION = f"{DOMAIN}:{ACCOUNT_1}_consumption"
STAT_COST = f"{DOMAIN}:{ACCOUNT_1}_cost"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_setup_entry():
    """Prevent full coordinator setup during config flow tests."""
    with patch(
        "custom_components.electric_ireland_insights.async_setup_entry",
        new=AsyncMock(return_value=True),
    ):
        yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entry(account: str = ACCOUNT_1, *, cached: bool = True) -> MockConfigEntry:
    data: dict = {
        "username": "u@test.com",
        "password": "pass",
        "account_number": account,
        "tariff_stats_initialized": True,
    }
    if cached:
        data.update(partner_id=PARTNER, contract_id=CONTRACT, premise_id=PREMISE)
    return MockConfigEntry(domain=DOMAIN, data=data, unique_id=account, version=2)


def _bp(start: date, end: date) -> dict:
    """Build a bill-period response covering start..end inclusive."""
    return {
        "isSuccess": True,
        "data": [
            {
                "startDate": f"{start.isoformat()}T00:00:00Z",
                "endDate": f"{end.isoformat()}T23:59:59Z",
            }
        ],
    }


async def _query(
    hass: HomeAssistant,
    stat_id: str,
    start: datetime,
    end: datetime,
    *,
    types: set[str] | None = None,
) -> list[dict]:
    t = types or {"sum", "state"}
    stats = await get_instance(hass).async_add_executor_job(
        partial(statistics_during_period, hass, start, end, {stat_id}, "hour", None, t)
    )
    return stats.get(stat_id, [])


# ==============================================================================
# Task 10: HTML Structure Variation Resilience
# ==============================================================================


async def test_dashboard_with_extra_classes_on_account_div(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
    mock_setup_entry,
) -> None:
    """Extra CSS classes on account div → account still discovered (BS4 partial class match)."""
    extra_class_div = (
        '<div class="my-accounts__item premium-account featured">'
        f'<p class="account-number">{ACCOUNT_1}</p>'
        '<h2 class="account-electricity-icon"></h2>'
        '<form action="/Accounts/OnEvent">'
        f'<input name="AccountId" value="{PARTNER}"/>'
        '<input name="triggers_event" value="AccountSelection.ToInsights"/>'
        "</form></div>"
    )
    db = f"<html><body>{extra_class_div}</body></html>"

    with aioresponses() as m:
        mock_ei_http(m, db)
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "u@test.com", "password": "pass"},
        )
        # Single account → auto-selected → options step
        if result.get("step_id") == "options":
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"import_full_history": False},
            )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["account_number"] == ACCOUNT_1


async def test_dashboard_with_nested_account_number(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
    mock_setup_entry,
) -> None:
    """Account number nested in <span> → BS4 .text.strip() still extracts it."""
    nested_div = (
        '<div class="my-accounts__item">'
        f'<p class="account-number"><span>{ACCOUNT_1}</span></p>'
        '<h2 class="account-electricity-icon"></h2>'
        '<form action="/Accounts/OnEvent">'
        f'<input name="AccountId" value="{PARTNER}"/>'
        '<input name="triggers_event" value="AccountSelection.ToInsights"/>'
        "</form></div>"
    )
    db = f"<html><body>{nested_div}</body></html>"

    with aioresponses() as m:
        mock_ei_http(m, db)
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "u@test.com", "password": "pass"},
        )
        if result.get("step_id") == "options":
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"import_full_history": False},
            )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["account_number"] == ACCOUNT_1


async def test_insights_page_missing_model_data(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Insights page without #modelData div → InvalidAuth → SETUP_ERROR."""
    entry = _entry(cached=False)
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))
    no_model = "<html><body><p>No model data here</p></body></html>"

    with aioresponses() as m:
        mock_ei_http(m, db, insights_html=no_model)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.SETUP_ERROR


async def test_login_page_csrf_in_cookie_only(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
    mock_setup_entry,
) -> None:
    """rvt in cookie only (not in HTML input) → login succeeds."""
    # Login page has Source but NOT rvt input
    login_html = '<html><body><input name="Source" value="src_token"/></body></html>'
    db = page(acct_div(ACCOUNT_1))

    with aioresponses() as m:
        m.get(f"{BASE_URL}/", body=login_html, repeat=True, headers={"Set-Cookie": "rvt=tok1"})
        m.post(f"{BASE_URL}/", body=db, repeat=True)
        m.post(f"{BASE_URL}/Accounts/OnEvent", body=insights_page(), repeat=True)

        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "u@test.com", "password": "pass"},
        )
        if result.get("step_id") == "options":
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"import_full_history": False},
            )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_login_page_csrf_in_input_only(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
    mock_setup_entry,
) -> None:
    """rvt in HTML input only (no cookie) → login succeeds via fallback."""
    login_html = (
        '<html><body><input name="Source" value="src_token"/><input name="rvt" value="rvt_from_input"/></body></html>'
    )
    db = page(acct_div(ACCOUNT_1))

    with aioresponses() as m:
        # No Set-Cookie header for rvt
        m.get(f"{BASE_URL}/", body=login_html, repeat=True)
        m.post(f"{BASE_URL}/", body=db, repeat=True)
        m.post(f"{BASE_URL}/Accounts/OnEvent", body=insights_page(), repeat=True)

        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "u@test.com", "password": "pass"},
        )
        if result.get("step_id") == "options":
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"import_full_history": False},
            )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY


# ==============================================================================
# Task 11: Timestamp Edge Cases
# ==============================================================================


async def test_midnight_timestamp_aligns_correctly(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Hour 0 with endDate at exactly midnight → aligns to T00:00:00 start."""
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))

    def midnight_cb(url, **kwargs):
        date_str = url.query.get("date", "2026-03-24")
        dt = datetime.fromisoformat(date_str).replace(tzinfo=UTC)
        prefix = dt.strftime("%Y-%m-%dT")
        data = []
        for hour in range(24):
            # endDate at exact hour boundary (e.g. 00:00:00, 01:00:00, ...)
            end_dt = dt + timedelta(hours=hour)
            data.append(
                {
                    "startDate": f"{prefix}{hour:02d}:00:00Z",
                    "endDate": end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "flatRate": {"consumption": 0.5, "cost": 0.10},
                    "offPeak": None,
                    "midPeak": None,
                    "onPeak": None,
                }
            )
        return CallbackResult(
            status=200,
            body=json.dumps({"isSuccess": True, "data": data}),
            content_type="application/json",
        )

    bp = _bp(date(2026, 3, 24), date(2026, 3, 24))
    fake_now = datetime(2026, 3, 25, 12, 0, tzinfo=UTC)

    with (
        patch("custom_components.electric_ireland_insights.coordinator.dt_now") as mock_dt,
        aioresponses() as m,
    ):
        mock_dt.return_value = fake_now
        mock_ei_http(m, db, hourly_cb=midnight_cb, bill_period_response=bp)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    await async_wait_recording_done(hass)

    start_q = datetime(2026, 3, 24, tzinfo=UTC)
    end_q = datetime(2026, 3, 25, tzinfo=UTC)
    stats = await _query(hass, STAT_CONSUMPTION, start_q, end_q)
    assert len(stats) == 24
    assert_hour_aligned(stats)


async def test_end_of_hour_timestamp_aligns_correctly(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """endDate at HH:59:59 → start aligns to HH:00:00."""
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))

    def end_of_hour_cb(url, **kwargs):
        date_str = url.query.get("date", "2026-03-23")
        dt = datetime.fromisoformat(date_str).replace(tzinfo=UTC)
        prefix = dt.strftime("%Y-%m-%dT")
        data = [
            {
                "startDate": f"{prefix}{hour:02d}:00:00Z",
                "endDate": f"{prefix}{hour:02d}:59:59Z",
                "flatRate": {"consumption": 0.5, "cost": 0.10},
                "offPeak": None,
                "midPeak": None,
                "onPeak": None,
            }
            for hour in range(24)
        ]
        return CallbackResult(
            status=200,
            body=json.dumps({"isSuccess": True, "data": data}),
            content_type="application/json",
        )

    bp = _bp(date(2026, 3, 23), date(2026, 3, 23))
    fake_now = datetime(2026, 3, 24, 12, 0, tzinfo=UTC)

    with (
        patch("custom_components.electric_ireland_insights.coordinator.dt_now") as mock_dt,
        aioresponses() as m,
    ):
        mock_dt.return_value = fake_now
        mock_ei_http(m, db, hourly_cb=end_of_hour_cb, bill_period_response=bp)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    await async_wait_recording_done(hass)

    start_q = datetime(2026, 3, 23, tzinfo=UTC)
    end_q = datetime(2026, 3, 24, tzinfo=UTC)
    stats = await _query(hass, STAT_CONSUMPTION, start_q, end_q)
    assert len(stats) == 24
    assert_hour_aligned(stats)
    assert_no_duplicate_hours(stats)

    last_start = stats[-1]["start"]
    last_dt = datetime.fromtimestamp(last_start, tz=UTC) if isinstance(last_start, (int, float)) else last_start
    assert last_dt.hour == 23
    assert last_dt.minute == 0
    assert last_dt.second == 0


async def test_year_boundary_timestamps(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Datapoints spanning Dec 31 → Jan 1 both import correctly."""
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))
    flat_cb = make_hourly_callback("flatRate")
    bp = _bp(date(2025, 12, 31), date(2026, 1, 1))
    fake_now = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)

    with (
        patch("custom_components.electric_ireland_insights.coordinator.dt_now") as mock_dt,
        aioresponses() as m,
    ):
        mock_dt.return_value = fake_now
        mock_ei_http(m, db, hourly_cb=flat_cb, bill_period_response=bp)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    await async_wait_recording_done(hass)

    start_q = datetime(2025, 12, 31, tzinfo=UTC)
    end_q = datetime(2026, 1, 2, tzinfo=UTC)
    stats = await _query(hass, STAT_CONSUMPTION, start_q, end_q)
    assert len(stats) == 48, f"Expected 48 entries (2 days x 24h), got {len(stats)}"
    assert_cumulative_sums_monotonic(stats)
    assert_no_duplicate_hours(stats)
    assert_hour_aligned(stats)


async def test_leap_year_feb_29(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Feb 29 in a leap year (2028) → 24 statistics entries."""
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))
    flat_cb = make_hourly_callback("flatRate")
    bp = _bp(date(2028, 2, 29), date(2028, 2, 29))
    fake_now = datetime(2028, 3, 1, 12, 0, tzinfo=UTC)

    with (
        patch("custom_components.electric_ireland_insights.coordinator.dt_now") as mock_dt,
        aioresponses() as m,
    ):
        mock_dt.return_value = fake_now
        mock_ei_http(m, db, hourly_cb=flat_cb, bill_period_response=bp)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    await async_wait_recording_done(hass)

    start_q = datetime(2028, 2, 29, tzinfo=UTC)
    end_q = datetime(2028, 3, 1, tzinfo=UTC)
    stats = await _query(hass, STAT_CONSUMPTION, start_q, end_q)
    assert len(stats) == 24
    assert_hour_aligned(stats)
    assert_no_duplicate_hours(stats)


# ==============================================================================
# Task 12: Zero and Null Consumption/Cost Values
# ==============================================================================


async def test_zero_consumption_is_valid_data(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """24 datapoints with consumption=0.0, cost=0.0 → 24 entries, final sum=0.0."""
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))

    def zero_cb(url, **kwargs):
        date_str = url.query.get("date", "2026-03-24")
        dt = datetime.fromisoformat(date_str).replace(tzinfo=UTC)
        prefix = dt.strftime("%Y-%m-%dT")
        data = [
            {
                "startDate": f"{prefix}{hour:02d}:00:00Z",
                "endDate": f"{prefix}{hour:02d}:59:59Z",
                "flatRate": {"consumption": 0.0, "cost": 0.0},
                "offPeak": None,
                "midPeak": None,
                "onPeak": None,
            }
            for hour in range(24)
        ]
        return CallbackResult(
            status=200,
            body=json.dumps({"isSuccess": True, "data": data}),
            content_type="application/json",
        )

    bp = _bp(date(2026, 3, 24), date(2026, 3, 24))
    fake_now = datetime(2026, 3, 25, 12, 0, tzinfo=UTC)

    with (
        patch("custom_components.electric_ireland_insights.coordinator.dt_now") as mock_dt,
        aioresponses() as m,
    ):
        mock_dt.return_value = fake_now
        mock_ei_http(m, db, hourly_cb=zero_cb, bill_period_response=bp)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    await async_wait_recording_done(hass)

    start_q = datetime(2026, 3, 24, tzinfo=UTC)
    end_q = datetime(2026, 3, 25, tzinfo=UTC)
    stats = await _query(hass, STAT_CONSUMPTION, start_q, end_q)
    assert len(stats) == 24, f"Expected 24 entries for zero consumption, got {len(stats)}"
    assert stats[-1]["sum"] == 0.0
    assert_hour_aligned(stats)
    assert_no_duplicate_hours(stats)


async def test_none_consumption_is_skipped(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Hours with all-null tariff buckets → no datapoints from API → excluded from statistics."""
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))

    # Only hours 0-11 have data; hours 12-23 have all-null buckets (no active tariff)
    partial_schedule: dict[int, str] = {h: "flatRate" for h in range(12)}
    partial_cb = make_hourly_callback(partial_schedule)

    bp = _bp(date(2026, 3, 24), date(2026, 3, 24))
    fake_now = datetime(2026, 3, 25, 12, 0, tzinfo=UTC)

    with (
        patch("custom_components.electric_ireland_insights.coordinator.dt_now") as mock_dt,
        aioresponses() as m,
    ):
        mock_dt.return_value = fake_now
        mock_ei_http(m, db, hourly_cb=partial_cb, bill_period_response=bp)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    await async_wait_recording_done(hass)

    start_q = datetime(2026, 3, 24, tzinfo=UTC)
    end_q = datetime(2026, 3, 25, tzinfo=UTC)
    stats = await _query(hass, STAT_CONSUMPTION, start_q, end_q)
    assert len(stats) == 12, f"Expected 12 entries (null hours skipped), got {len(stats)}"
    assert_hour_aligned(stats)
    assert_no_duplicate_hours(stats)


async def test_mixed_zero_and_normal_values(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Hours 0-6: consumption=0.0, hours 7-23: 0.5 → all 24 recorded, sum=8.5."""
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))

    mixed = [0.0] * 7 + [0.5] * 17
    mixed_cb = make_hourly_callback("flatRate", consumption_pattern=mixed)

    bp = _bp(date(2026, 3, 24), date(2026, 3, 24))
    fake_now = datetime(2026, 3, 25, 12, 0, tzinfo=UTC)

    with (
        patch("custom_components.electric_ireland_insights.coordinator.dt_now") as mock_dt,
        aioresponses() as m,
    ):
        mock_dt.return_value = fake_now
        mock_ei_http(m, db, hourly_cb=mixed_cb, bill_period_response=bp)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    await async_wait_recording_done(hass)

    start_q = datetime(2026, 3, 24, tzinfo=UTC)
    end_q = datetime(2026, 3, 25, tzinfo=UTC)
    stats = await _query(hass, STAT_CONSUMPTION, start_q, end_q)
    assert len(stats) == 24, f"All 24 entries should be recorded, got {len(stats)}"
    final_sum = stats[-1]["sum"]
    expected = 17 * 0.5  # 8.5
    assert abs(final_sum - expected) < 0.01, f"Expected sum={expected}, got {final_sum}"


# ==============================================================================
# Task 13: Session Expiry Mid-Multi-Day Fetch With Recovery
# ==============================================================================


async def test_session_expiry_mid_fetch_recovers_via_reauth(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Day 2 returns 401 → CachedIdsInvalid → re-auth → retry succeeds → all 3 days present."""
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))

    flat_cb = make_hourly_callback("flatRate")
    call_count = 0

    def stateful_hourly_cb(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            return CallbackResult(status=401, body="Unauthorized")
        return flat_cb(url, **kwargs)

    bp = _bp(date(2026, 3, 22), date(2026, 3, 24))
    fake_now = datetime(2026, 3, 25, 12, 0, tzinfo=UTC)

    with (
        patch("custom_components.electric_ireland_insights.coordinator.dt_now") as mock_dt,
        aioresponses() as m,
    ):
        mock_dt.return_value = fake_now
        mock_ei_http(m, db, hourly_cb=stateful_hourly_cb, bill_period_response=bp)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    await async_wait_recording_done(hass)

    start_q = datetime(2026, 3, 22, tzinfo=UTC)
    end_q = datetime(2026, 3, 25, tzinfo=UTC)
    stats = await _query(hass, STAT_CONSUMPTION, start_q, end_q)
    # 3 days x 24h = 72 entries (day 1 ok, day 2 retried after re-auth, day 3 ok)
    assert len(stats) == 72, f"Expected 72 entries (3 days x 24h), got {len(stats)}"
    assert_cumulative_sums_monotonic(stats)
    assert_hour_aligned(stats)
    assert_no_duplicate_hours(stats)


async def test_session_expiry_returns_html_instead_of_json(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Hourly endpoint returns text/html → CachedIdsInvalid → recovery via re-auth."""
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))

    flat_cb = make_hourly_callback("flatRate")
    call_count = 0

    def html_then_json_cb(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return CallbackResult(
                status=200,
                body="<html><body>Session expired</body></html>",
                content_type="text/html",
            )
        return flat_cb(url, **kwargs)

    bp = _bp(date(2026, 3, 24), date(2026, 3, 24))
    fake_now = datetime(2026, 3, 25, 12, 0, tzinfo=UTC)

    with (
        patch("custom_components.electric_ireland_insights.coordinator.dt_now") as mock_dt,
        aioresponses() as m,
    ):
        mock_dt.return_value = fake_now
        mock_ei_http(m, db, hourly_cb=html_then_json_cb, bill_period_response=bp)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    await async_wait_recording_done(hass)

    start_q = datetime(2026, 3, 24, tzinfo=UTC)
    end_q = datetime(2026, 3, 25, tzinfo=UTC)
    stats = await _query(hass, STAT_CONSUMPTION, start_q, end_q)
    assert len(stats) == 24, f"Expected 24 entries after recovery, got {len(stats)}"
    assert_hour_aligned(stats)
    assert_no_duplicate_hours(stats)


# ==============================================================================
# Task 14: Bill Period Edge Cases
# ==============================================================================


async def test_bill_period_with_enddate_before_startdate(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """End date before start date → no dates generated from period → 0 datapoints, no crash."""
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))

    # end < start: while loop at coordinator.py:167 never executes
    bp = {
        "isSuccess": True,
        "data": [
            {
                "startDate": "2026-03-20T00:00:00Z",
                "endDate": "2026-03-15T23:59:59Z",
            }
        ],
    }
    fake_now = datetime(2026, 3, 25, 12, 0, tzinfo=UTC)

    with (
        patch("custom_components.electric_ireland_insights.coordinator.dt_now") as mock_dt,
        aioresponses() as m,
    ):
        mock_dt.return_value = fake_now
        mock_ei_http(m, db, hourly_cb=make_hourly_callback("flatRate"), bill_period_response=bp)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    data = entry.runtime_data.data
    assert data["datapoint_count"] == 0


async def test_bill_period_with_identical_start_and_end(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Same start and end date → exactly 1 day fetched → 24 entries."""
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))
    flat_cb = make_hourly_callback("flatRate")
    bp = _bp(date(2026, 3, 20), date(2026, 3, 20))
    fake_now = datetime(2026, 3, 21, 12, 0, tzinfo=UTC)

    with (
        patch("custom_components.electric_ireland_insights.coordinator.dt_now") as mock_dt,
        aioresponses() as m,
    ):
        mock_dt.return_value = fake_now
        mock_ei_http(m, db, hourly_cb=flat_cb, bill_period_response=bp)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    await async_wait_recording_done(hass)

    start_q = datetime(2026, 3, 20, tzinfo=UTC)
    end_q = datetime(2026, 3, 21, tzinfo=UTC)
    stats = await _query(hass, STAT_CONSUMPTION, start_q, end_q)
    assert len(stats) == 24, f"Expected 24 entries for 1 day, got {len(stats)}"
    assert_hour_aligned(stats)
    assert_cumulative_sums_monotonic(stats)


async def test_bill_period_data_with_extra_fields(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Extra fields in bill period JSON → ignored, coordinator processes normally."""
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))
    flat_cb = make_hourly_callback("flatRate")

    bp = {
        "isSuccess": True,
        "data": [
            {
                "startDate": "2026-03-20T00:00:00Z",
                "endDate": "2026-03-20T23:59:59Z",
                "meterType": "smart",
                "extra": 42,
                "current": True,
                "hasAppliance": False,
            }
        ],
    }
    fake_now = datetime(2026, 3, 21, 12, 0, tzinfo=UTC)

    with (
        patch("custom_components.electric_ireland_insights.coordinator.dt_now") as mock_dt,
        aioresponses() as m,
    ):
        mock_dt.return_value = fake_now
        mock_ei_http(m, db, hourly_cb=flat_cb, bill_period_response=bp)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    await async_wait_recording_done(hass)

    start_q = datetime(2026, 3, 20, tzinfo=UTC)
    end_q = datetime(2026, 3, 21, tzinfo=UTC)
    stats = await _query(hass, STAT_CONSUMPTION, start_q, end_q)
    assert len(stats) == 24
    assert_hour_aligned(stats)
    assert_cumulative_sums_monotonic(stats)


async def test_bill_period_empty_date_strings(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Empty date strings → ValueError in date.fromisoformat('') → UpdateFailed → SETUP_RETRY."""
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))

    bp = {
        "isSuccess": True,
        "data": [{"startDate": "", "endDate": ""}],
    }
    fake_now = datetime(2026, 3, 25, 12, 0, tzinfo=UTC)

    with (
        patch("custom_components.electric_ireland_insights.coordinator.dt_now") as mock_dt,
        aioresponses() as m,
    ):
        mock_dt.return_value = fake_now
        mock_ei_http(m, db, hourly_cb=make_hourly_callback("flatRate"), bill_period_response=bp)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Empty date strings cause ValueError in date.fromisoformat("")
    # Caught by generic Exception handler → UpdateFailed → ConfigEntryNotReady → SETUP_RETRY
    assert entry.state == ConfigEntryState.SETUP_RETRY
