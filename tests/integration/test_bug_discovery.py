"""Bug-discovery integration tests: cumulative sum continuity, overlap, FP precision, tariff partitioning.

Tasks 5, 5b, 6, 7, 8, 9 from the QA test strategy.

Only fake: HTTP responses via aioresponses + dt_now for deterministic dates.
Real: coordinator, API parsing, recorder statistics, overlap detection.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from functools import partial
from unittest.mock import patch

import pytest
from aioresponses import aioresponses
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.electric_ireland_insights.const import DOMAIN, LOOKUP_DAYS
from tests.assertions import (
    assert_conservation,
    assert_cumulative_sums_monotonic,
    assert_hour_aligned,
    assert_no_duplicate_hours,
)

from .conftest import (
    ACCOUNT_1,
    CONTRACT,
    PARTNER,
    PREMISE,
    acct_div,
    make_hourly_callback,
    make_smart_tariff_callback,
    mock_ei_http,
    page,
)

STAT_CONSUMPTION = f"{DOMAIN}:{ACCOUNT_1}_consumption"
STAT_COST = f"{DOMAIN}:{ACCOUNT_1}_cost"

# sum(round(0.5 + h * 0.05, 2) for h in range(24)) = 25.8
FLAT_DAILY_SUM = sum(round(0.5 + h * 0.05, 2) for h in range(24))


def _entry(account: str = ACCOUNT_1) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "u@test.com",
            "password": "pass",
            "account_number": account,
            "partner_id": PARTNER,
            "contract_id": CONTRACT,
            "premise_id": PREMISE,
            "tariff_stats_initialized": True,
        },
        unique_id=account,
        version=2,
    )


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


def _bp_multi(*ranges: tuple[date, date]) -> dict:
    """Build a bill-period response with multiple non-contiguous ranges."""
    return {
        "isSuccess": True,
        "data": [
            {
                "startDate": f"{s.isoformat()}T00:00:00Z",
                "endDate": f"{e.isoformat()}T23:59:59Z",
            }
            for s, e in ranges
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
# Task 5: Multi-Run Cumulative Sum Continuity
# ==============================================================================


async def test_cumulative_sum_continues_across_coordinator_refreshes(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Run 1 imports Jan 1-7, run 2 imports Jan 9-12 (1-day gap within 2-day window).

    The 2-day lookback from Jan 9 finds Jan 7 data, so base_sum carries over.
    """
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))
    flat_cb = make_hourly_callback("flatRate")

    bp = _bp(date(2026, 1, 1), date(2026, 1, 20))
    fake_now1 = datetime(2026, 1, 8, 12, 0, tzinfo=UTC)  # yesterday=Jan7, 4d → Jan4-7
    fake_now2 = datetime(2026, 1, 13, 12, 0, tzinfo=UTC)  # yesterday=Jan12, 4d → Jan9-12

    with (
        patch("custom_components.electric_ireland_insights.coordinator.dt_now") as mock_dt,
        aioresponses() as m,
    ):
        mock_ei_http(m, db, hourly_cb=flat_cb, bill_period_response=bp)

        mock_dt.return_value = fake_now1
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state == ConfigEntryState.LOADED
        await async_wait_recording_done(hass)

        start_q = datetime(2026, 1, 1, tzinfo=UTC)
        end_q = datetime(2026, 2, 1, tzinfo=UTC)
        stats_run1 = await _query(hass, STAT_CONSUMPTION, start_q, end_q)
        assert len(stats_run1) == LOOKUP_DAYS * 24
        sum_after_run1 = stats_run1[-1]["sum"]

        mock_dt.return_value = fake_now2
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

    await async_wait_recording_done(hass)

    stats_run2 = await _query(hass, STAT_CONSUMPTION, start_q, end_q)
    assert len(stats_run2) > len(stats_run1), "Run 2 should add new hourly entries"

    assert_cumulative_sums_monotonic(stats_run2)
    assert_no_duplicate_hours(stats_run2)
    assert_hour_aligned(stats_run2)

    sum_after_run2 = stats_run2[-1]["sum"]
    assert sum_after_run2 > sum_after_run1, "New days should increase total sum"


# ==============================================================================
# Task 5b: >2-Day Data Gap Bug Discovery
# ==============================================================================


async def test_data_gap_greater_than_2_days_preserves_cumulative_sum(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Run 1: Jan 1-3. Run 2: Jan 10-12 (7-day gap). Cumulative sum must carry over.

    Regression test: previously used a 2-day statistics_during_period window that
    missed run-1 data when the gap exceeded 2 days, resetting base_sum to 0.
    Fixed by switching to get_last_statistics which has no time-window limitation.
    """
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))
    flat_cb = make_hourly_callback("flatRate")

    # Wide bill period covering both runs' date ranges
    bp = _bp(date(2026, 1, 1), date(2026, 1, 20))
    fake_now1 = datetime(2026, 1, 4, 12, 0, tzinfo=UTC)  # yesterday=Jan3, 30d covers Jan1-3
    fake_now2 = datetime(2026, 1, 13, 12, 0, tzinfo=UTC)  # yesterday=Jan12, 4d → Jan9-12

    with (
        patch("custom_components.electric_ireland_insights.coordinator.dt_now") as mock_dt,
        aioresponses() as m,
    ):
        mock_ei_http(m, db, hourly_cb=flat_cb, bill_period_response=bp)

        mock_dt.return_value = fake_now1
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state == ConfigEntryState.LOADED
        await async_wait_recording_done(hass)

        start_q = datetime(2025, 12, 1, tzinfo=UTC)
        end_q = datetime(2026, 2, 1, tzinfo=UTC)
        stats_run1 = await _query(hass, STAT_CONSUMPTION, start_q, end_q)
        sum_run1 = stats_run1[-1]["sum"]
        assert sum_run1 > 0

        mock_dt.return_value = fake_now2
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

    await async_wait_recording_done(hass)

    stats_run2 = await _query(hass, STAT_CONSUMPTION, start_q, end_q)
    sum_run2 = stats_run2[-1]["sum"]

    # BUG: overlap_start=Jan9T00, search (Jan7,Jan9) finds nothing → base_sum=0
    expected = sum_run1 + 4 * FLAT_DAILY_SUM  # 4 new days (Jan 9-12)
    assert abs(sum_run2 - expected) < 0.1, (
        f"Cumulative sum broken: expected ~{expected:.1f} "
        f"(run1={sum_run1:.1f} + new={4 * FLAT_DAILY_SUM:.1f}), "
        f"got {sum_run2:.1f}"
    )


async def test_data_gap_exactly_2_days_preserves_sum(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Run 1: Jan 5-7. Run 2: Jan 7,9 (1 missing day). 2-day window (Jan 5,Jan 7) finds data."""
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))
    flat_cb = make_hourly_callback("flatRate")

    # Bill period with gap at Jan 8 to simulate missing day
    bp = _bp_multi(
        (date(2026, 1, 5), date(2026, 1, 7)),
        (date(2026, 1, 9), date(2026, 1, 9)),
    )
    fake_now1 = datetime(2026, 1, 8, 12, 0, tzinfo=UTC)  # yesterday=Jan7, 30d covers Jan5-7
    fake_now2 = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)  # yesterday=Jan9, 4d → Jan6-9

    with (
        patch("custom_components.electric_ireland_insights.coordinator.dt_now") as mock_dt,
        aioresponses() as m,
    ):
        mock_ei_http(m, db, hourly_cb=flat_cb, bill_period_response=bp)

        mock_dt.return_value = fake_now1
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state == ConfigEntryState.LOADED
        await async_wait_recording_done(hass)

        start_q = datetime(2026, 1, 1, tzinfo=UTC)
        end_q = datetime(2026, 2, 1, tzinfo=UTC)
        stats_run1 = await _query(hass, STAT_CONSUMPTION, start_q, end_q)
        assert len(stats_run1) == 3 * 24  # Jan 5-7
        sum_run1 = stats_run1[-1]["sum"]

        mock_dt.return_value = fake_now2
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

    await async_wait_recording_done(hass)

    stats_run2 = await _query(hass, STAT_CONSUMPTION, start_q, end_q)
    sum_run2 = stats_run2[-1]["sum"]

    # Run 2 fetches Jan 6,7,9 (Jan 8 not in bill period). Overlap Jan 6-7, new Jan 9.
    # overlap_start=Jan6T00 → search (Jan4,Jan6) → finds Jan5 data → base_sum carries
    expected = sum_run1 + FLAT_DAILY_SUM  # 1 new day (Jan 9)
    assert abs(sum_run2 - expected) < 0.1, f"Sum not preserved: expected ~{expected:.1f}, got {sum_run2:.1f}"
    assert_cumulative_sums_monotonic(stats_run2)


# ==============================================================================
# Task 6: Re-import Idempotency and Partial Overlap
# ==============================================================================


async def test_reimporting_same_day_does_not_double_count(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Re-importing the exact same single day produces identical stats, no duplicates."""
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))
    flat_cb = make_hourly_callback("flatRate")
    bp = _bp(date(2026, 1, 15), date(2026, 1, 15))
    fake_now = datetime(2026, 1, 16, 12, 0, tzinfo=UTC)

    with (
        patch("custom_components.electric_ireland_insights.coordinator.dt_now") as mock_dt,
        aioresponses() as m,
    ):
        mock_ei_http(m, db, hourly_cb=flat_cb, bill_period_response=bp)
        mock_dt.return_value = fake_now

        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state == ConfigEntryState.LOADED
        await async_wait_recording_done(hass)

        start_q = datetime(2026, 1, 15, tzinfo=UTC)
        end_q = datetime(2026, 1, 16, tzinfo=UTC)
        stats_run1 = await _query(hass, STAT_CONSUMPTION, start_q, end_q)
        count1 = len(stats_run1)
        sum1 = stats_run1[-1]["sum"]

        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

    await async_wait_recording_done(hass)

    stats_run2 = await _query(hass, STAT_CONSUMPTION, start_q, end_q)
    assert len(stats_run2) == count1, "Re-import should not create extra entries"
    assert abs(stats_run2[-1]["sum"] - sum1) < 0.01, "Sum should be unchanged"
    assert_no_duplicate_hours(stats_run2)


async def test_partial_overlap_sums_correctly(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Run 1: Jan 1-3. Run 2: Jan 2-5 (overlap Jan 2-3, new Jan 4-5). Total 5 days."""
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))
    flat_cb = make_hourly_callback("flatRate")

    bp = _bp(date(2026, 1, 1), date(2026, 1, 5))
    fake_now1 = datetime(2026, 1, 4, 12, 0, tzinfo=UTC)  # yesterday=Jan3, 30d covers Jan1-3
    fake_now2 = datetime(2026, 1, 6, 12, 0, tzinfo=UTC)  # yesterday=Jan5, 4d → Jan2-5

    with (
        patch("custom_components.electric_ireland_insights.coordinator.dt_now") as mock_dt,
        aioresponses() as m,
    ):
        mock_ei_http(m, db, hourly_cb=flat_cb, bill_period_response=bp)

        mock_dt.return_value = fake_now1
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state == ConfigEntryState.LOADED
        await async_wait_recording_done(hass)

        start_q = datetime(2026, 1, 1, tzinfo=UTC)
        end_q = datetime(2026, 1, 6, tzinfo=UTC)
        stats_run1 = await _query(hass, STAT_CONSUMPTION, start_q, end_q)
        assert abs(stats_run1[-1]["sum"] - 3 * FLAT_DAILY_SUM) < 0.1

        mock_dt.return_value = fake_now2
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

    await async_wait_recording_done(hass)

    stats_run2 = await _query(hass, STAT_CONSUMPTION, start_q, end_q)
    assert len(stats_run2) == 5 * 24, f"Expected 120 entries, got {len(stats_run2)}"

    assert_no_duplicate_hours(stats_run2)
    assert_cumulative_sums_monotonic(stats_run2)
    assert_hour_aligned(stats_run2)

    expected = 5 * FLAT_DAILY_SUM
    assert abs(stats_run2[-1]["sum"] - expected) < 0.1, (
        f"Expected ~{expected:.1f} for 5 days, got {stats_run2[-1]['sum']:.1f}"
    )


# ==============================================================================
# Task 7: DST Transition Tests (Placeholder -- require real fixtures)
# ==============================================================================


@pytest.mark.skip(
    reason=(
        "Requires real DST-day fixture from capture script. "
        "Run: python scripts/capture_fixtures.py --username ... --account-number ... "
        "See tests/fixtures/real/hourly_dst_spring_forward.json"
    )
)
async def test_spring_forward_handles_actual_api_response(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """DST spring-forward day (Ireland: last Sunday of March, UTC+0 -> UTC+1).

    This test activates after running the capture script.
    The fixture may have 23 or 24 datapoints depending on how EI's
    backend handles the missing hour.
    """
    pytest.skip("Requires real DST fixture")


@pytest.mark.skip(
    reason=(
        "Requires real DST-day fixture from capture script. "
        "Run: python scripts/capture_fixtures.py --username ... --account-number ... "
        "See tests/fixtures/real/hourly_dst_fall_back.json"
    )
)
async def test_fall_back_handles_actual_api_response(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """DST fall-back day (Ireland: last Sunday of October, UTC+1 -> UTC+0).

    Fall-back may produce 24 or 25 datapoints if the repeated hour is
    recorded twice.
    """
    pytest.skip("Requires real DST fixture")


# ==============================================================================
# Task 8: Floating-Point Precision
# ==============================================================================


async def test_floating_point_precision_over_many_hours(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """30 days * 24h of consumption=0.1 sums to 72.0 without significant FP drift."""
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))
    fp_cb = make_hourly_callback("flatRate", consumption_pattern=[0.1] * 24)

    bp = _bp(date(2026, 1, 1), date(2026, 1, 30))
    fake_now = datetime(2026, 1, 31, 12, 0, tzinfo=UTC)  # yesterday=Jan30, 4d → Jan27-30

    with (
        patch("custom_components.electric_ireland_insights.coordinator.dt_now") as mock_dt,
        aioresponses() as m,
    ):
        mock_dt.return_value = fake_now
        mock_ei_http(m, db, hourly_cb=fp_cb, bill_period_response=bp)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    await async_wait_recording_done(hass)

    start_q = datetime(2026, 1, 1, tzinfo=UTC)
    end_q = datetime(2026, 2, 1, tzinfo=UTC)
    stats = await _query(hass, STAT_CONSUMPTION, start_q, end_q)
    assert len(stats) == LOOKUP_DAYS * 24, f"Expected {LOOKUP_DAYS * 24} entries, got {len(stats)}"

    final_sum = stats[-1]["sum"]
    expected = LOOKUP_DAYS * 24 * 0.1
    assert abs(final_sum - expected) < 0.01, (
        f"FP precision issue: expected ~{expected}, got {final_sum} (drift={abs(final_sum - expected):.6f})"
    )

    assert_conservation(stats, [0.1] * (LOOKUP_DAYS * 24), tolerance=0.1)
    assert_hour_aligned(stats)


async def test_very_small_values_not_lost(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Tiny consumption=0.001 (1 Wh) * 24h = 0.024 kWh must not vanish."""
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))
    tiny_cb = make_hourly_callback("flatRate", consumption_pattern=[0.001] * 24)
    bp = _bp(date(2026, 1, 15), date(2026, 1, 15))
    fake_now = datetime(2026, 1, 16, 12, 0, tzinfo=UTC)

    with (
        patch("custom_components.electric_ireland_insights.coordinator.dt_now") as mock_dt,
        aioresponses() as m,
    ):
        mock_dt.return_value = fake_now
        mock_ei_http(m, db, hourly_cb=tiny_cb, bill_period_response=bp)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    await async_wait_recording_done(hass)

    start_q = datetime(2026, 1, 15, tzinfo=UTC)
    end_q = datetime(2026, 1, 16, tzinfo=UTC)
    stats = await _query(hass, STAT_CONSUMPTION, start_q, end_q)

    assert len(stats) > 0, "Should have stats even for tiny values"
    final_sum = stats[-1]["sum"]
    assert final_sum > 0, "Tiny values must not round to zero"
    assert abs(final_sum - 0.024) < 0.001, f"Expected ~0.024, got {final_sum}"


# ==============================================================================
# Task 9: Smart Tariff Per-Bucket Statistics
# ==============================================================================


async def test_smart_tariff_produces_per_bucket_statistics(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Smart tariff with off_peak/on_peak/mid_peak produces per-bucket stat IDs."""
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))
    smart_cb = make_smart_tariff_callback()
    bp = _bp(date(2026, 1, 20), date(2026, 1, 21))
    fake_now = datetime(2026, 1, 22, 12, 0, tzinfo=UTC)

    with (
        patch("custom_components.electric_ireland_insights.coordinator.dt_now") as mock_dt,
        aioresponses() as m,
    ):
        mock_dt.return_value = fake_now
        mock_ei_http(m, db, hourly_cb=smart_cb, bill_period_response=bp)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    await async_wait_recording_done(hass)

    start_q = datetime(2026, 1, 20, tzinfo=UTC)
    end_q = datetime(2026, 1, 22, tzinfo=UTC)

    for bucket_suffix in ("off_peak", "on_peak", "mid_peak"):
        stat_id = f"{DOMAIN}:{ACCOUNT_1}_consumption_{bucket_suffix}"
        stats = await _query(hass, stat_id, start_q, end_q)
        assert len(stats) > 0, f"No stats found for {stat_id}"
        assert_hour_aligned(stats)


async def test_tariff_bucket_sums_equal_aggregate_sum(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Conservation law: aggregate consumption = sum of all tariff buckets."""
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))
    smart_cb = make_smart_tariff_callback()
    bp = _bp(date(2026, 1, 20), date(2026, 1, 21))
    fake_now = datetime(2026, 1, 22, 12, 0, tzinfo=UTC)

    with (
        patch("custom_components.electric_ireland_insights.coordinator.dt_now") as mock_dt,
        aioresponses() as m,
    ):
        mock_dt.return_value = fake_now
        mock_ei_http(m, db, hourly_cb=smart_cb, bill_period_response=bp)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    await async_wait_recording_done(hass)

    start_q = datetime(2026, 1, 20, tzinfo=UTC)
    end_q = datetime(2026, 1, 22, tzinfo=UTC)

    agg = await _query(hass, STAT_CONSUMPTION, start_q, end_q, types={"sum"})
    assert len(agg) > 0

    bucket_total = 0.0
    for bucket_suffix in ("off_peak", "on_peak", "mid_peak"):
        stat_id = f"{DOMAIN}:{ACCOUNT_1}_consumption_{bucket_suffix}"
        bucket_stats = await _query(hass, stat_id, start_q, end_q, types={"sum"})
        if bucket_stats:
            bucket_total += bucket_stats[-1]["sum"]

    agg_total = agg[-1]["sum"]
    assert abs(agg_total - bucket_total) < 0.01, (
        f"Conservation violated: aggregate={agg_total:.4f}, "
        f"bucket sum={bucket_total:.4f} (diff={abs(agg_total - bucket_total):.4f})"
    )
