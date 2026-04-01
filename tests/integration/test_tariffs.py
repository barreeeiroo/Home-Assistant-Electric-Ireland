"""End-to-end integration tests for per-tariff statistics.

Only fake: HTTP responses via aioresponses.
Real: API parsing, coordinator, recorder statistics.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aioresponses import aioresponses
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

from custom_components.electric_ireland_insights.const import DOMAIN

from .conftest import (
    ACCOUNT_1,
    CONTRACT,
    PARTNER,
    PREMISE,
    acct_div,
    make_hourly_callback,
    mock_ei_http,
    page,
)

STAT_CONSUMPTION = f"{DOMAIN}:{ACCOUNT_1}_consumption"
STAT_COST = f"{DOMAIN}:{ACCOUNT_1}_cost"


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


async def _query_stats(hass: HomeAssistant, stat_id: str, *, types: set[str] | None = None) -> list:
    now = datetime.now(UTC)
    start = now - timedelta(days=35)
    end = now + timedelta(days=1)
    t = types or {"sum", "state"}
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period, hass, start, end, {stat_id}, "hour", None, t
    )
    return stats.get(stat_id, [])


# ===================================================================
# Test 1: Flat-rate only → no per-tariff stats
# ===================================================================


async def test_flat_rate_only_no_per_tariff_stats(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """All 24 hours use flatRate → aggregate exists, no per-tariff stats."""
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))

    with aioresponses() as m:
        mock_ei_http(m, db, hourly_cb=make_hourly_callback("flatRate"))
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    await async_wait_recording_done(hass)

    data = entry.runtime_data.data
    assert data["tariff_buckets_seen"] == 1

    agg = await _query_stats(hass, STAT_CONSUMPTION)
    assert len(agg) > 0
    agg_cost = await _query_stats(hass, STAT_COST)
    assert len(agg_cost) > 0

    flat_c = await _query_stats(hass, f"{STAT_CONSUMPTION}_flat_rate")
    assert len(flat_c) == 0
    flat_k = await _query_stats(hass, f"{STAT_COST}_flat_rate")
    assert len(flat_k) == 0


# ===================================================================
# Test 2: Single non-flat bucket (all off-peak)
# ===================================================================


async def test_single_off_peak_creates_per_tariff_stats(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """All 24 hours use offPeak → aggregate + per-tariff off_peak stats exist."""
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))

    with aioresponses() as m:
        mock_ei_http(m, db, hourly_cb=make_hourly_callback("offPeak"))
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    await async_wait_recording_done(hass)

    data = entry.runtime_data.data
    assert data["tariff_buckets_seen"] == 1

    agg = await _query_stats(hass, STAT_CONSUMPTION)
    assert len(agg) > 0

    off_c = await _query_stats(hass, f"{STAT_CONSUMPTION}_off_peak")
    assert len(off_c) > 0
    off_k = await _query_stats(hass, f"{STAT_COST}_off_peak")
    assert len(off_k) > 0

    assert abs(agg[-1]["sum"] - off_c[-1]["sum"]) < 0.01


# ===================================================================
# Test 3: Two-bucket smart meter (off-peak + on-peak)
# ===================================================================


async def test_two_bucket_off_peak_on_peak(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Hours 0-7: offPeak, hours 8-23: onPeak → both per-tariff stat pairs exist."""
    schedule = {h: "offPeak" for h in range(8)} | {h: "onPeak" for h in range(8, 24)}
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))

    with aioresponses() as m:
        mock_ei_http(m, db, hourly_cb=make_hourly_callback(schedule))
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    await async_wait_recording_done(hass)

    data = entry.runtime_data.data
    assert data["tariff_buckets_seen"] == 2

    for suffix in ("off_peak", "on_peak"):
        c = await _query_stats(hass, f"{STAT_CONSUMPTION}_{suffix}")
        assert len(c) > 0
        k = await _query_stats(hass, f"{STAT_COST}_{suffix}")
        assert len(k) > 0


# ===================================================================
# Test 4: Three-bucket smart meter (off-peak + mid-peak + on-peak)
# ===================================================================


async def test_three_bucket_all_tariffs(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Hours 0-7: offPeak, 8-16: onPeak, 17-23: midPeak → all three pairs exist."""
    schedule = (
        {h: "offPeak" for h in range(8)} | {h: "onPeak" for h in range(8, 17)} | {h: "midPeak" for h in range(17, 24)}
    )
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))

    with aioresponses() as m:
        mock_ei_http(m, db, hourly_cb=make_hourly_callback(schedule))
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    await async_wait_recording_done(hass)

    data = entry.runtime_data.data
    assert data["tariff_buckets_seen"] == 3

    for suffix in ("off_peak", "on_peak", "mid_peak"):
        c = await _query_stats(hass, f"{STAT_CONSUMPTION}_{suffix}")
        assert len(c) > 0
        k = await _query_stats(hass, f"{STAT_COST}_{suffix}")
        assert len(k) > 0


# ===================================================================
# Test 5: Partition integrity — per-tariff sums equal aggregate
# ===================================================================


async def test_partition_integrity_sums_match(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Per-tariff cumulative sums equal aggregate sum for both consumption and cost."""
    schedule = (
        {h: "offPeak" for h in range(8)} | {h: "onPeak" for h in range(8, 17)} | {h: "midPeak" for h in range(17, 24)}
    )
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))

    with aioresponses() as m:
        mock_ei_http(m, db, hourly_cb=make_hourly_callback(schedule))
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    await async_wait_recording_done(hass)

    for base_stat in (STAT_CONSUMPTION, STAT_COST):
        agg = await _query_stats(hass, base_stat, types={"sum"})
        off = await _query_stats(hass, f"{base_stat}_off_peak", types={"sum"})
        mid = await _query_stats(hass, f"{base_stat}_mid_peak", types={"sum"})
        on = await _query_stats(hass, f"{base_stat}_on_peak", types={"sum"})

        agg_total = agg[-1]["sum"]
        tariff_total = off[-1]["sum"] + mid[-1]["sum"] + on[-1]["sum"]
        assert abs(tariff_total - agg_total) < 0.01, (
            f"{base_stat}: per-tariff sum {tariff_total:.4f} != aggregate {agg_total:.4f}"
        )


# ===================================================================
# Test 6: All tariff buckets null → no datapoints, no stats
# ===================================================================


async def test_all_null_buckets_no_stats(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """24 hours with all null tariff buckets → 0 datapoints, no stats."""
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))

    with aioresponses() as m:
        mock_ei_http(m, db, hourly_cb=make_hourly_callback({}))
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    await async_wait_recording_done(hass)

    data = entry.runtime_data.data
    assert data["datapoint_count"] == 0
    assert data["tariff_buckets_seen"] == 0

    agg = await _query_stats(hass, STAT_CONSUMPTION)
    assert len(agg) == 0

    for suffix in ("flat_rate", "off_peak", "mid_peak", "on_peak"):
        c = await _query_stats(hass, f"{STAT_CONSUMPTION}_{suffix}")
        assert len(c) == 0


# ===================================================================
# Test 7: Mixed flat-rate + smart buckets → all get per-tariff stats
# ===================================================================


async def test_mixed_flat_rate_and_smart_all_get_per_tariff(
    recorder_mock,
    hass: HomeAssistant,
    enable_custom_integrations,
) -> None:
    """Hours 0-7: flatRate, 8-16: onPeak, 17-23: offPeak → all three get per-tariff stats."""
    schedule = (
        {h: "flatRate" for h in range(8)} | {h: "onPeak" for h in range(8, 17)} | {h: "offPeak" for h in range(17, 24)}
    )
    entry = _entry()
    entry.add_to_hass(hass)
    db = page(acct_div(ACCOUNT_1))

    with aioresponses() as m:
        mock_ei_http(m, db, hourly_cb=make_hourly_callback(schedule))
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    await async_wait_recording_done(hass)

    data = entry.runtime_data.data
    assert data["tariff_buckets_seen"] == 3

    for suffix in ("flat_rate", "on_peak", "off_peak"):
        c = await _query_stats(hass, f"{STAT_CONSUMPTION}_{suffix}")
        assert len(c) > 0
        k = await _query_stats(hass, f"{STAT_COST}_{suffix}")
        assert len(k) > 0
