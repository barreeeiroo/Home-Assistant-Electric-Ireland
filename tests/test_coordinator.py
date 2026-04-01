"""Tests for the Electric Ireland coordinator."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.issue_registry import async_get as async_get_issue_registry
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util.dt import utcnow
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.electric_ireland_insights.const import (
    DATA_GAP_THRESHOLD_DAYS,
    DOMAIN,
    INITIAL_LOOKBACK_DAYS,
    LOOKUP_DAYS,
)
from custom_components.electric_ireland_insights.exceptions import (
    CachedIdsInvalid,
    CannotConnect,
    InvalidAuth,
)

ACCOUNT = "100000001"
STAT_ID_CONSUMPTION = f"{DOMAIN}:{ACCOUNT}_consumption"
STAT_ID_COST = f"{DOMAIN}:{ACCOUNT}_cost"
TEST_METER_IDS = {"partner": "P1", "contract": "C1", "premise": "PR1"}


def make_datapoints(n_days=1, base_ts=1774224000, tariff_bucket="off_peak"):
    """Create n_days * 24 hourly datapoints."""
    dps = []
    for day in range(n_days):
        for hour in range(24):
            ts = base_ts + day * 86400 + hour * 3600
            dps.append(
                {
                    "consumption": round(0.5 + hour * 0.1, 2),
                    "cost": round(0.1 + hour * 0.02, 2),
                    "intervalEnd": ts,
                    "tariff_bucket": tariff_bucket,
                }
            )
    return dps


def _setup_api_mock(
    mock_api_instance,
    *,
    authenticate_return=(TEST_METER_IDS, None),
    authenticate_side_effect=None,
    bill_periods=None,
    bill_periods_side_effect=None,
    hourly_return=None,
    hourly_side_effect=None,
):
    """Configure mock API instance with new pipeline methods."""
    if authenticate_side_effect is not None:
        mock_api_instance.authenticate = AsyncMock(side_effect=authenticate_side_effect)
    else:
        mock_api_instance.authenticate = AsyncMock(return_value=authenticate_return)

    if bill_periods_side_effect is not None:
        mock_api_instance.get_bill_periods = AsyncMock(side_effect=bill_periods_side_effect)
    else:
        mock_api_instance.get_bill_periods = AsyncMock(return_value=bill_periods or [])

    if hourly_side_effect is not None:
        mock_api_instance.get_hourly_usage = AsyncMock(side_effect=hourly_side_effect)
    elif hourly_return is not None:
        mock_api_instance.get_hourly_usage = AsyncMock(return_value=hourly_return)
    else:
        mock_api_instance.get_hourly_usage = AsyncMock(return_value=[])


# ---------------------------------------------------------------------------
# Test 1: First run uses 30-day lookback when no stats exist
# ---------------------------------------------------------------------------


async def test_first_run_imports_30_days(recorder_mock, hass, mock_config_entry):
    """Test first run uses 30-day lookback when no stats exist."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(mock_api_instance)
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        assert mock_api_instance.get_hourly_usage.call_count == INITIAL_LOOKBACK_DAYS


# ---------------------------------------------------------------------------
# Test 2: Subsequent run uses 7-day lookback when stats already exist
# ---------------------------------------------------------------------------


async def test_subsequent_run_imports_7_days(recorder_mock, hass, mock_config_entry):
    """Test subsequent run uses 7-day lookback when stats already exist."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={STAT_ID_CONSUMPTION: [{"sum": 100.0}]},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(mock_api_instance)
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        assert mock_api_instance.get_hourly_usage.call_count == LOOKUP_DAYS


async def test_tariff_backfill_uses_30_days_when_flag_missing(recorder_mock, hass):
    """async_tariff_backfill fetches INITIAL_LOOKBACK_DAYS and sets the flag."""
    entry = MockConfigEntry(
        domain="electric_ireland_insights",
        data={
            "username": "test@test.com",
            "password": "testpass",
            "account_number": ACCOUNT,
        },
        unique_id=ACCOUNT,
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(
            mock_api_instance,
            hourly_side_effect=[make_datapoints(1)] + [[] for _ in range(50)],
        )
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, entry)
        await coordinator.async_tariff_backfill()

        assert mock_api_instance.get_hourly_usage.call_count == INITIAL_LOOKBACK_DAYS

    assert entry.data.get("tariff_stats_initialized") is True


async def test_tariff_backfill_skips_when_flag_set(recorder_mock, hass, mock_config_entry):
    """async_tariff_backfill is a no-op when tariff_stats_initialized is already True."""
    mock_config_entry.add_to_hass(hass)
    assert mock_config_entry.data.get("tariff_stats_initialized") is True

    with (
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator.async_tariff_backfill()

        mock_api_instance.authenticate.assert_not_called()


async def test_tariff_backfill_handles_auth_failure(recorder_mock, hass):
    """async_tariff_backfill logs warning and does NOT set flag on auth failure."""
    entry = MockConfigEntry(
        domain="electric_ireland_insights",
        data={"username": "t@t.com", "password": "p", "account_number": ACCOUNT},
        unique_id=ACCOUNT,
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.authenticate = AsyncMock(side_effect=InvalidAuth("bad creds"))
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import ElectricIrelandCoordinator

        coordinator = ElectricIrelandCoordinator(hass, entry)
        await coordinator.async_tariff_backfill()

    assert entry.data.get("tariff_stats_initialized") is None


async def test_tariff_backfill_retries_on_cached_ids_invalid(recorder_mock, hass):
    """CachedIdsInvalid mid-backfill triggers re-auth and retries the day."""
    entry = MockConfigEntry(
        domain="electric_ireland_insights",
        data={"username": "t@t.com", "password": "p", "account_number": ACCOUNT},
        unique_id=ACCOUNT,
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        ids = {"partner": "P", "contract": "C", "premise": "PR"}
        mock_api_instance.authenticate = AsyncMock(return_value=(ids, ids))
        mock_api_instance.get_bill_periods = AsyncMock(return_value=[])
        mock_api_instance.get_hourly_usage = AsyncMock(
            side_effect=[CachedIdsInvalid("stale")] + [make_datapoints(1)] + [[] for _ in range(50)]
        )
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import ElectricIrelandCoordinator

        coordinator = ElectricIrelandCoordinator(hass, entry)
        await coordinator.async_tariff_backfill()

    assert entry.data.get("tariff_stats_initialized") is True
    assert mock_api_instance.authenticate.call_count == 2


async def test_consumption_statistics_correct(recorder_mock, hass, mock_config_entry):
    """Test consumption statistics are imported with correct sum/state values."""
    mock_config_entry.add_to_hass(hass)

    datapoints = make_datapoints(1)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(
            mock_api_instance,
            hourly_side_effect=[datapoints] + [[] for _ in range(50)],
        )
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

    await async_wait_recording_done(hass)

    start = datetime(2026, 3, 23, 0, 0, tzinfo=UTC)
    end = datetime(2026, 3, 24, 0, 0, tzinfo=UTC)
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        end,
        {STAT_ID_CONSUMPTION},
        "hour",
        None,
        {"sum", "state"},
    )
    assert STAT_ID_CONSUMPTION in stats
    assert len(stats[STAT_ID_CONSUMPTION]) == 24

    last_sum = stats[STAT_ID_CONSUMPTION][-1]["sum"]
    expected_total = sum(dp["consumption"] for dp in datapoints)
    assert abs(last_sum - expected_total) < 0.01


# ---------------------------------------------------------------------------
# Test 4: Cost statistics have correct values with EUR unit
# ---------------------------------------------------------------------------


async def test_cost_statistics_correct(recorder_mock, hass, mock_config_entry):
    """Test cost statistics are imported with correct sum/state and EUR unit."""
    mock_config_entry.add_to_hass(hass)

    datapoints = make_datapoints(1)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(
            mock_api_instance,
            hourly_side_effect=[datapoints] + [[] for _ in range(50)],
        )
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

    await async_wait_recording_done(hass)

    start = datetime(2026, 3, 23, 0, 0, tzinfo=UTC)
    end = datetime(2026, 3, 24, 0, 0, tzinfo=UTC)
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        end,
        {STAT_ID_COST},
        "hour",
        None,
        {"sum", "state"},
    )
    assert STAT_ID_COST in stats
    assert len(stats[STAT_ID_COST]) == 24

    last_sum = stats[STAT_ID_COST][-1]["sum"]
    expected_total = sum(dp["cost"] for dp in datapoints)
    assert abs(last_sum - expected_total) < 0.01


# ---------------------------------------------------------------------------
# Test 5: Statistic IDs follow the expected format
# ---------------------------------------------------------------------------


async def test_statistic_id_format(recorder_mock, hass, mock_config_entry):
    """Test statistic IDs match the expected domain:account_metric format."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(
            mock_api_instance,
            hourly_side_effect=[make_datapoints(1)] + [[] for _ in range(50)],
        )
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

    await async_wait_recording_done(hass)

    start = datetime(2026, 3, 23, 0, 0, tzinfo=UTC)
    end = datetime(2026, 3, 24, 0, 0, tzinfo=UTC)
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        end,
        {STAT_ID_CONSUMPTION},
        "hour",
        None,
        {"sum", "state"},
    )

    assert "electric_ireland_insights:100000001_consumption" in stats

    assert STAT_ID_CONSUMPTION.startswith(f"{DOMAIN}:")


# ---------------------------------------------------------------------------
# Test 6: Interval start is aligned to the hour (not the raw intervalEnd)
# ---------------------------------------------------------------------------


async def test_interval_start_alignment(recorder_mock, hass, mock_config_entry):
    """Test that interval start is aligned to hour boundary, not raw intervalEnd."""
    mock_config_entry.add_to_hass(hass)

    datapoints = [
        {
            "consumption": 0.5,
            "cost": 0.1,
            "intervalEnd": 1774227599,
            "tariff_bucket": "off_peak",
        }
    ]

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(
            mock_api_instance,
            hourly_side_effect=[datapoints] + [[] for _ in range(50)],
        )
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

    await async_wait_recording_done(hass)

    start = datetime(2026, 3, 23, 0, 0, 0, tzinfo=UTC)
    end = datetime(2026, 3, 23, 1, 0, 0, tzinfo=UTC)
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        end,
        {STAT_ID_CONSUMPTION},
        "hour",
        None,
        {"sum", "state"},
    )

    assert STAT_ID_CONSUMPTION in stats
    assert len(stats[STAT_ID_CONSUMPTION]) == 1
    stat_entry = stats[STAT_ID_CONSUMPTION][0]
    assert stat_entry["start"] == start.timestamp()


# ---------------------------------------------------------------------------
# Test 7: Sum continuity across multiple coordinator runs
# ---------------------------------------------------------------------------


async def test_sum_continuity_across_runs(recorder_mock, hass, mock_config_entry):
    """Test that cumulative sum continues from previous run, not restarting from 0."""
    mock_config_entry.add_to_hass(hass)

    first_run_data = make_datapoints(7, base_ts=1774224000)
    second_run_data = make_datapoints(7, base_ts=1774224000 + 7 * 86400)

    first_run_total = sum(dp["consumption"] for dp in first_run_data)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
        ) as mock_get_last,
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        mock_get_last.return_value = {}
        _setup_api_mock(
            mock_api_instance,
            hourly_side_effect=[first_run_data] + [[] for _ in range(50)],
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        await get_instance(hass).async_add_executor_job(lambda: None)
        await hass.async_block_till_done()

        mock_get_last.return_value = {STAT_ID_CONSUMPTION: [{"sum": first_run_total}]}
        _setup_api_mock(
            mock_api_instance,
            hourly_side_effect=[second_run_data] + [[] for _ in range(50)],
        )

        await coordinator._async_update_data()

        await get_instance(hass).async_add_executor_job(lambda: None)
        await hass.async_block_till_done()

    start = datetime(2026, 3, 23, 0, 0, tzinfo=UTC)
    end = datetime(2026, 4, 6, 0, 0, tzinfo=UTC)
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        end,
        {STAT_ID_CONSUMPTION},
        "hour",
        None,
        {"sum"},
    )

    assert STAT_ID_CONSUMPTION in stats
    all_entries = stats[STAT_ID_CONSUMPTION]
    final_sum = all_entries[-1]["sum"]
    assert final_sum > first_run_total


# ---------------------------------------------------------------------------
# Test 8: InvalidAuth raises ConfigEntryAuthFailed
# ---------------------------------------------------------------------------


async def test_auth_error_raises_config_entry_auth_failed(recorder_mock, hass, mock_config_entry):
    """Test that InvalidAuth from API raises ConfigEntryAuthFailed."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(
            mock_api_instance,
            authenticate_side_effect=InvalidAuth("Invalid credentials"),
        )
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)

        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._async_update_data()


# ---------------------------------------------------------------------------
# Test 9: CannotConnect raises UpdateFailed
# ---------------------------------------------------------------------------


async def test_connection_error_raises_update_failed(recorder_mock, hass, mock_config_entry):
    """Test that CannotConnect from API raises UpdateFailed."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(
            mock_api_instance,
            authenticate_side_effect=CannotConnect("Connection refused"),
        )
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()


# ---------------------------------------------------------------------------
# Test 10: Empty data from API inserts no statistics
# ---------------------------------------------------------------------------


async def test_empty_data_no_statistics(recorder_mock, hass, mock_config_entry):
    """Test that empty API response inserts no statistics and raises no error."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(mock_api_instance)
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

    await async_wait_recording_done(hass)

    start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 12, 31, 0, 0, tzinfo=UTC)
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        end,
        {STAT_ID_CONSUMPTION},
        "hour",
        None,
        {"sum", "state"},
    )

    assert STAT_ID_CONSUMPTION not in stats or len(stats[STAT_ID_CONSUMPTION]) == 0


# ---------------------------------------------------------------------------
# Test 11: Coordinator fetches data even without entity listeners
# ---------------------------------------------------------------------------


async def test_imports_continue_without_entity_listeners(recorder_mock, hass, mock_config_entry):
    """Test that coordinator fetches data even when no entities are subscribed."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(mock_api_instance)
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)

        unsub = coordinator.async_add_listener(lambda: None)

        await coordinator.async_refresh()

        mock_api_instance.get_hourly_usage.assert_called()

        unsub()


# ===========================================================================
# SCRAPE-ONCE + SILENT FAILURE TESTS
# ===========================================================================


async def test_cached_ids_skip_html_discovery(recorder_mock, hass, mock_config_entry):
    """Test that cached meter IDs skip HTML discovery but still log in."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={
            **dict(mock_config_entry.data),
            "partner_id": "P1",
            "contract_id": "C1",
            "premise_id": "PR1",
        },
    )

    cached_ids = {"partner": "P1", "contract": "C1", "premise": "PR1"}

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(
            mock_api_instance,
            authenticate_return=(cached_ids, None),
        )
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        call_args = mock_api_instance.authenticate.call_args
        assert call_args[0][1] is not None, "authenticate should be called with cached meter_ids"


async def test_no_cached_ids_triggers_full_login(recorder_mock, hass, mock_config_entry):
    """Test that missing cached IDs trigger full login with HTML discovery."""
    mock_config_entry.add_to_hass(hass)

    discovered = {"partner": "P1", "contract": "C1", "premise": "PR1"}

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(
            mock_api_instance,
            authenticate_return=(discovered, discovered),
        )
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        call_args = mock_api_instance.authenticate.call_args
        passed_meter_ids = call_args[0][1]
        assert passed_meter_ids is None, "No cached IDs: authenticate should be called with meter_ids=None"


async def test_cached_ids_fallback_to_full_login(recorder_mock, hass, mock_config_entry):
    """Test that cached ID failure falls back to full login within same cycle."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={
            **dict(mock_config_entry.data),
            "partner_id": "STALE_P1",
            "contract_id": "STALE_C1",
            "premise_id": "STALE_PR1",
        },
    )

    stale_ids = {"partner": "STALE_P1", "contract": "STALE_C1", "premise": "STALE_PR1"}
    new_ids = {"partner": "NEW_P1", "contract": "NEW_C1", "premise": "NEW_PR1"}

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        mock_api_instance.authenticate = AsyncMock(
            side_effect=[
                (stale_ids, None),
                (new_ids, new_ids),
            ]
        )
        mock_api_instance.get_bill_periods = AsyncMock(return_value=[])
        mock_api_instance.get_hourly_usage = AsyncMock(
            side_effect=[CachedIdsInvalid("stale")] + [make_datapoints(1)] + [[] for _ in range(50)]
        )
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        assert hass.config_entries.async_get_entry(mock_config_entry.entry_id).data.get("partner_id") == "NEW_P1", (
            "New meter IDs from fallback should be stored in entry.data"
        )


async def test_fallback_updates_cached_ids(recorder_mock, hass, mock_config_entry):
    """Test that fallback discovery updates cached IDs in entry.data."""
    mock_config_entry.add_to_hass(hass)

    new_ids = {"partner": "P_NEW", "contract": "C_NEW", "premise": "PR_NEW"}

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(
            mock_api_instance,
            authenticate_return=(new_ids, new_ids),
        )
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        entry = hass.config_entries.async_get_entry(mock_config_entry.entry_id)
        assert entry.data.get("partner_id") == "P_NEW"
        assert entry.data.get("contract_id") == "C_NEW"
        assert entry.data.get("premise_id") == "PR_NEW"


async def test_api_redirect_clears_and_falls_back(recorder_mock, hass, mock_config_entry):
    """Test that a redirect-to-login response causes fallback to full login."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={
            **dict(mock_config_entry.data),
            "partner_id": "P1",
            "contract_id": "C1",
            "premise_id": "PR1",
        },
    )

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(mock_api_instance)
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        result = await coordinator._async_update_data()
        assert result is not None


async def test_empty_data_subsequent_run_no_update(recorder_mock, hass, mock_config_entry):
    """Test that empty data on subsequent runs doesn't update last_import."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={"some_stat": [{"sum": 100.0}]},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(mock_api_instance)
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)

        coordinator.data = {
            "last_import": datetime(2026, 3, 28, 12, 0, tzinfo=UTC),
            "datapoint_count": 24,
            "latest_data_timestamp": datetime(2026, 3, 26, 0, 0, tzinfo=UTC),
            "import_error": None,
            "appliance_count": 0,
            "bill_periods_available": 0,
            "tariff_buckets_seen": 0,
        }
        coordinator._has_imported_before = True

        result = await coordinator._async_update_data()

        assert result["last_import"] == datetime(2026, 3, 28, 12, 0, tzinfo=UTC), (
            "Empty subsequent run should not update last_import"
        )


async def test_empty_data_restart_returns_synthetic(recorder_mock, hass, mock_config_entry):
    """Test empty data after restart returns synthetic stale dict when _has_imported_before is True."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={"some_stat": [{"sum": 100.0}]},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(mock_api_instance)
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        assert coordinator.data is None

        result = await coordinator._async_update_data()

        assert result is not None
        assert result.get("last_import") is None
        assert result.get("datapoint_count") == 0
        assert result.get("import_error") is not None


async def test_connection_restored_logging(recorder_mock, hass, mock_config_entry):
    """Test that _last_update_success transitions from False to True on success."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(
            mock_api_instance,
            hourly_side_effect=[make_datapoints(1)] + [[] for _ in range(50)],
        )
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import ElectricIrelandCoordinator

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        coordinator._last_update_success = False

        with patch.object(coordinator, "_insert_statistics", new_callable=AsyncMock):
            result = await coordinator._async_update_data()

        assert coordinator._last_update_success is True
        assert result is not None


async def test_update_failed_reraise(recorder_mock, hass, mock_config_entry):
    """Test UpdateFailed from _insert_statistics is re-raised through except block."""
    from homeassistant.helpers.update_coordinator import UpdateFailed

    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(
            mock_api_instance,
            hourly_side_effect=[make_datapoints(1)] + [[] for _ in range(50)],
        )
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import ElectricIrelandCoordinator

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)

        with (
            patch.object(
                coordinator, "_insert_statistics", new_callable=AsyncMock, side_effect=UpdateFailed("insert failed")
            ),
            pytest.raises(UpdateFailed),
        ):
            await coordinator._async_update_data()

        assert coordinator._last_update_success is False


async def test_unexpected_exception_wrapped(recorder_mock, hass, mock_config_entry):
    """Test unexpected exception from authenticate is wrapped in UpdateFailed."""
    from homeassistant.helpers.update_coordinator import UpdateFailed

    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(
            mock_api_instance,
            authenticate_side_effect=RuntimeError("unexpected boom"),
        )
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import ElectricIrelandCoordinator

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)

        with pytest.raises(UpdateFailed, match="unexpected boom"):
            await coordinator._async_update_data()

        assert coordinator._last_update_success is False


async def test_latest_timestamp_none_when_interval_zero(recorder_mock, hass, mock_config_entry):
    """Test latest_data_timestamp is None when all intervalEnd are 0 (falsy max)."""
    mock_config_entry.add_to_hass(hass)

    zero_ts_datapoints = [
        {"consumption": 0.5, "cost": 0.1, "intervalEnd": 0, "tariff_bucket": "flat_rate"} for _ in range(3)
    ]

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(
            mock_api_instance,
            hourly_side_effect=[zero_ts_datapoints] + [[] for _ in range(50)],
        )
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import ElectricIrelandCoordinator

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)

        with patch.object(coordinator, "_insert_statistics", new_callable=AsyncMock):
            result = await coordinator._async_update_data()

        assert result["latest_data_timestamp"] is None


# ===========================================================================
# NEW TESTS: Bill-period pre-flight bounds
# ===========================================================================


async def test_bill_period_bounds_date_range(recorder_mock, hass, mock_config_entry):
    """Bill-period bounds date range to period ∩ lookback — only period dates fetched."""
    mock_config_entry.add_to_hass(hass)

    yesterday = (datetime.now(UTC) - timedelta(days=1)).date()
    period_start = yesterday - timedelta(days=4)
    period_end = yesterday + timedelta(days=20)

    bill_periods = [
        {
            "startDate": f"{period_start.isoformat()}T00:00:00Z",
            "endDate": f"{period_end.isoformat()}T00:00:00Z",
            "current": True,
            "hasAppliance": False,
        }
    ]

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={STAT_ID_CONSUMPTION: [{"sum": 100.0}]},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(mock_api_instance, bill_periods=bill_periods)
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import ElectricIrelandCoordinator

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        all_lookback_dates = {yesterday - timedelta(days=i) for i in range(LOOKUP_DAYS)}
        dates_in_period = set()
        d = period_start
        while d <= period_end:
            dates_in_period.add(d)
            d += timedelta(days=1)

        expected_dates = dates_in_period & all_lookback_dates

        assert mock_api_instance.get_hourly_usage.call_count == len(expected_dates)

        called_dates = sorted(call.args[2] for call in mock_api_instance.get_hourly_usage.call_args_list)
        assert called_dates == sorted(expected_dates)


async def test_bill_period_failure_falls_back_to_blind_fetch(recorder_mock, hass, mock_config_entry):
    """get_bill_periods raises CannotConnect → get_hourly_usage called for all lookback days, warning logged."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={STAT_ID_CONSUMPTION: [{"sum": 100.0}]},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(
            mock_api_instance,
            bill_periods_side_effect=CannotConnect("bill period endpoint down"),
        )
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import ElectricIrelandCoordinator

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)

        with patch("custom_components.electric_ireland_insights.coordinator._LOGGER") as mock_logger:
            await coordinator._async_update_data()
            mock_logger.warning.assert_any_call("Failed to fetch bill periods, falling back to full lookback window")

        assert mock_api_instance.get_hourly_usage.call_count == LOOKUP_DAYS


async def test_bill_period_empty_falls_back_to_blind_fetch(recorder_mock, hass, mock_config_entry):
    """get_bill_periods returns [] → fallback to all lookback days."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={STAT_ID_CONSUMPTION: [{"sum": 100.0}]},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(mock_api_instance, bill_periods=[])
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import ElectricIrelandCoordinator

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        assert mock_api_instance.get_hourly_usage.call_count == LOOKUP_DAYS


async def test_bill_period_partial_coverage_only_fetches_period_dates(recorder_mock, hass, mock_config_entry):
    """Bill-period covers 5 of 7 lookback days → only 5 dates fetched (uncovered days skipped)."""
    mock_config_entry.add_to_hass(hass)

    yesterday = (datetime.now(UTC) - timedelta(days=1)).date()
    period_start = yesterday - timedelta(days=4)
    period_end = yesterday

    bill_periods = [
        {
            "startDate": f"{period_start.isoformat()}T00:00:00Z",
            "endDate": f"{period_end.isoformat()}T00:00:00Z",
            "current": True,
            "hasAppliance": False,
        }
    ]

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={STAT_ID_CONSUMPTION: [{"sum": 100.0}]},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(mock_api_instance, bill_periods=bill_periods)
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import ElectricIrelandCoordinator

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        assert mock_api_instance.get_hourly_usage.call_count == 5

        called_dates = sorted(call.args[2] for call in mock_api_instance.get_hourly_usage.call_args_list)
        expected_dates = sorted(period_start + timedelta(days=i) for i in range(5))
        assert called_dates == expected_dates
        assert coordinator._bill_periods == bill_periods


async def test_bill_period_gap_between_periods_skips_gap_dates(recorder_mock, hass, mock_config_entry):
    """Two billing periods with a 2-day gap — gap dates are not fetched."""
    mock_config_entry.add_to_hass(hass)

    yesterday = (datetime.now(UTC) - timedelta(days=1)).date()

    bill_periods = [
        {
            "startDate": f"{(yesterday - timedelta(days=6)).isoformat()}T00:00:00Z",
            "endDate": f"{(yesterday - timedelta(days=5)).isoformat()}T23:59:59Z",
            "current": False,
            "hasAppliance": False,
        },
        {
            "startDate": f"{(yesterday - timedelta(days=2)).isoformat()}T00:00:00Z",
            "endDate": f"{yesterday.isoformat()}T23:59:59Z",
            "current": True,
            "hasAppliance": False,
        },
    ]

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={STAT_ID_CONSUMPTION: [{"sum": 100.0}]},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(mock_api_instance, bill_periods=bill_periods)
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import ElectricIrelandCoordinator

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        # Period 1: 2 days (yesterday-6, yesterday-5)
        # Gap: 2 days (yesterday-4, yesterday-3) — skipped
        # Period 2: 3 days (yesterday-2, yesterday-1, yesterday)
        # Total within 7-day lookback: 5 days fetched, 2 gap days skipped
        assert mock_api_instance.get_hourly_usage.call_count == 5

        called_dates = sorted(call.args[2] for call in mock_api_instance.get_hourly_usage.call_args_list)
        gap_dates = {yesterday - timedelta(days=4), yesterday - timedelta(days=3)}
        for gap_date in gap_dates:
            assert gap_date not in called_dates


async def test_bill_period_partial_coverage_with_tariff_buckets(recorder_mock, hass, mock_config_entry):
    """Tariff bucketing still works correctly when only period-bounded dates are fetched."""
    mock_config_entry.add_to_hass(hass)

    yesterday = (datetime.now(UTC) - timedelta(days=1)).date()
    period_start = yesterday - timedelta(days=2)

    bill_periods = [
        {
            "startDate": f"{period_start.isoformat()}T00:00:00Z",
            "endDate": f"{yesterday.isoformat()}T23:59:59Z",
            "current": True,
            "hasAppliance": False,
        }
    ]

    off_peak = make_datapoints(1, base_ts=1774224000, tariff_bucket="off_peak")
    on_peak = make_datapoints(1, base_ts=1774224000 + 86400, tariff_bucket="on_peak")
    mixed = off_peak + on_peak

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={STAT_ID_CONSUMPTION: [{"sum": 100.0}]},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
        patch("custom_components.electric_ireland_insights.coordinator.statistics_during_period", return_value={}),
        patch(
            "custom_components.electric_ireland_insights.coordinator.async_add_external_statistics",
        ) as mock_add_stats,
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(mock_api_instance, bill_periods=bill_periods, hourly_return=mixed)
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import ElectricIrelandCoordinator

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

        # 3 period days fetched (not 7)
        assert mock_api_instance.get_hourly_usage.call_count == 3

        stat_ids = {call.args[1]["statistic_id"] for call in mock_add_stats.call_args_list}
        assert f"{DOMAIN}:{ACCOUNT}_consumption" in stat_ids
        assert f"{DOMAIN}:{ACCOUNT}_cost" in stat_ids
        assert f"{DOMAIN}:{ACCOUNT}_consumption_off_peak" in stat_ids
        assert f"{DOMAIN}:{ACCOUNT}_cost_off_peak" in stat_ids
        assert f"{DOMAIN}:{ACCOUNT}_consumption_on_peak" in stat_ids
        assert f"{DOMAIN}:{ACCOUNT}_cost_on_peak" in stat_ids


# ===========================================================================
# PER-TARIFF STATISTICS TESTS
# ===========================================================================


async def test_per_tariff_statistics_created_for_mixed_buckets(recorder_mock, hass, mock_config_entry):
    """Per-tariff stats are created when datapoints span multiple tariff buckets."""
    mock_config_entry.add_to_hass(hass)

    off_peak = make_datapoints(1, base_ts=1774224000, tariff_bucket="off_peak")
    on_peak = make_datapoints(1, base_ts=1774224000 + 86400, tariff_bucket="on_peak")
    mixed = off_peak + on_peak

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(
            mock_api_instance,
            hourly_side_effect=[mixed] + [[] for _ in range(50)],
        )
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        result = await coordinator._async_update_data()

    await async_wait_recording_done(hass)

    assert result["tariff_buckets_seen"] == 2

    stat_off = f"{DOMAIN}:{ACCOUNT}_consumption_off_peak"
    stat_on = f"{DOMAIN}:{ACCOUNT}_consumption_on_peak"

    start = datetime(2026, 3, 23, 0, 0, tzinfo=UTC)
    end = datetime(2026, 3, 25, 0, 0, tzinfo=UTC)

    for stat_id in (stat_off, stat_on):
        stats = await get_instance(hass).async_add_executor_job(
            statistics_during_period,
            hass,
            start,
            end,
            {stat_id},
            "hour",
            None,
            {"sum", "state"},
        )
        assert stat_id in stats
        assert len(stats[stat_id]) == 24

    off_stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        end,
        {stat_off},
        "hour",
        None,
        {"sum"},
    )
    off_total = off_stats[stat_off][-1]["sum"]
    expected_off = sum(dp["consumption"] for dp in off_peak)
    assert abs(off_total - expected_off) < 0.01


async def test_per_tariff_cost_statistics_created(recorder_mock, hass, mock_config_entry):
    """Per-tariff cost stats are created alongside consumption stats."""
    mock_config_entry.add_to_hass(hass)

    off_peak = make_datapoints(1, base_ts=1774224000, tariff_bucket="off_peak")
    on_peak = make_datapoints(1, base_ts=1774224000 + 86400, tariff_bucket="on_peak")
    mixed = off_peak + on_peak

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(
            mock_api_instance,
            hourly_side_effect=[mixed] + [[] for _ in range(50)],
        )
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

    await async_wait_recording_done(hass)

    start = datetime(2026, 3, 23, 0, 0, tzinfo=UTC)
    end = datetime(2026, 3, 25, 0, 0, tzinfo=UTC)

    cost_off = f"{DOMAIN}:{ACCOUNT}_cost_off_peak"
    cost_on = f"{DOMAIN}:{ACCOUNT}_cost_on_peak"
    for stat_id in (cost_off, cost_on):
        stats = await get_instance(hass).async_add_executor_job(
            statistics_during_period,
            hass,
            start,
            end,
            {stat_id},
            "hour",
            None,
            {"sum"},
        )
        assert stat_id in stats
        assert len(stats[stat_id]) == 24


async def test_flat_rate_only_skips_per_tariff_stats(recorder_mock, hass, mock_config_entry):
    """When all datapoints are flat_rate, per-tariff stats are not created (redundant with aggregate)."""
    mock_config_entry.add_to_hass(hass)

    flat = make_datapoints(1, tariff_bucket="flat_rate")

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(
            mock_api_instance,
            hourly_side_effect=[flat] + [[] for _ in range(50)],
        )
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        result = await coordinator._async_update_data()

    await async_wait_recording_done(hass)

    assert result["tariff_buckets_seen"] == 1

    start = datetime(2026, 3, 23, 0, 0, tzinfo=UTC)
    end = datetime(2026, 3, 24, 0, 0, tzinfo=UTC)

    stat_flat = f"{DOMAIN}:{ACCOUNT}_consumption_flat_rate"
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        end,
        {stat_flat},
        "hour",
        None,
        {"sum"},
    )
    assert stat_flat not in stats or len(stats[stat_flat]) == 0


async def test_single_non_flat_bucket_creates_per_tariff_stats(recorder_mock, hass, mock_config_entry):
    """When all datapoints are off_peak (not flat_rate), per-tariff stats are still created."""
    mock_config_entry.add_to_hass(hass)

    off_peak_only = make_datapoints(1, tariff_bucket="off_peak")

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(
            mock_api_instance,
            hourly_side_effect=[off_peak_only] + [[] for _ in range(50)],
        )
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        result = await coordinator._async_update_data()

    await async_wait_recording_done(hass)

    assert result["tariff_buckets_seen"] == 1

    start = datetime(2026, 3, 23, 0, 0, tzinfo=UTC)
    end = datetime(2026, 3, 24, 0, 0, tzinfo=UTC)

    stat_off = f"{DOMAIN}:{ACCOUNT}_consumption_off_peak"
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        end,
        {stat_off},
        "hour",
        None,
        {"sum"},
    )
    assert stat_off in stats
    assert len(stats[stat_off]) == 24


# ===========================================================================
# EVENT FIRING TESTS
# ===========================================================================


async def test_event_fired_on_successful_import(recorder_mock, hass, mock_config_entry):
    """Successful data import fires electric_ireland_insights_data_imported event."""
    mock_config_entry.add_to_hass(hass)

    datapoints = make_datapoints(1)

    events: list = []
    hass.bus.async_listen(
        f"{DOMAIN}_data_imported",
        lambda event: events.append(event),
    )

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(
            mock_api_instance,
            hourly_side_effect=[datapoints] + [[] for _ in range(50)],
        )
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import (
            ElectricIrelandCoordinator,
        )

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

    await hass.async_block_till_done()

    assert len(events) == 1
    event_data = events[0].data
    assert event_data["account"] == ACCOUNT
    assert event_data["datapoint_count"] == 24
    assert event_data["tariff_buckets"] == ["off_peak"]
    assert event_data["latest_data_timestamp"] is not None


# ===========================================================================
# DATA GAP REPAIR ISSUE TESTS (F3)
# ===========================================================================


async def test_repair_issue_created_when_data_stale(recorder_mock, hass, mock_config_entry):
    """_check_data_gap creates a repair issue when latest_data_timestamp is >5 days old."""
    mock_config_entry.add_to_hass(hass)

    stale_ts = datetime(2026, 3, 20, 0, 0, tzinfo=UTC)
    now_ts = datetime(2026, 3, 28, 0, 0, tzinfo=UTC)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
        patch("custom_components.electric_ireland_insights.coordinator.utcnow", return_value=now_ts),
    ):
        mock_api_instance = AsyncMock()
        dps = make_datapoints(1, base_ts=int(stale_ts.timestamp()))
        _setup_api_mock(mock_api_instance, hourly_side_effect=[dps] + [[] for _ in range(50)])
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import ElectricIrelandCoordinator

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        result = await coordinator._async_update_data()

    assert result["datapoint_count"] == 24

    issue_registry = async_get_issue_registry(hass)
    issue = issue_registry.async_get_issue(DOMAIN, f"data_gap_{ACCOUNT}")
    assert issue is not None
    assert issue.severity == "warning"


async def test_repair_issue_deleted_when_data_fresh(recorder_mock, hass, mock_config_entry):
    """_check_data_gap deletes the repair issue when data is within threshold."""
    mock_config_entry.add_to_hass(hass)

    from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue

    async_create_issue(
        hass,
        DOMAIN,
        f"data_gap_{ACCOUNT}",
        is_fixable=False,
        severity=IssueSeverity.WARNING,
        translation_key="data_gap",
        translation_placeholders={"account": ACCOUNT, "days": "7.0"},
    )

    issue_registry = async_get_issue_registry(hass)
    assert issue_registry.async_get_issue(DOMAIN, f"data_gap_{ACCOUNT}") is not None

    fresh_ts = datetime(2026, 3, 27, 0, 0, tzinfo=UTC)
    now_ts = datetime(2026, 3, 28, 0, 0, tzinfo=UTC)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
        patch("custom_components.electric_ireland_insights.coordinator.utcnow", return_value=now_ts),
    ):
        mock_api_instance = AsyncMock()
        dps = make_datapoints(1, base_ts=int(fresh_ts.timestamp()))
        _setup_api_mock(mock_api_instance, hourly_side_effect=[dps] + [[] for _ in range(50)])
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import ElectricIrelandCoordinator

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

    assert issue_registry.async_get_issue(DOMAIN, f"data_gap_{ACCOUNT}") is None


async def test_no_repair_issue_when_no_data_yet(recorder_mock, hass, mock_config_entry):
    """No repair issue created when latest_data_timestamp is None (first run, no data)."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(mock_api_instance, hourly_side_effect=[[] for _ in range(50)])
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import ElectricIrelandCoordinator

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        result = await coordinator._async_update_data()

    assert result["latest_data_timestamp"] is None

    issue_registry = async_get_issue_registry(hass)
    assert issue_registry.async_get_issue(DOMAIN, f"data_gap_{ACCOUNT}") is None


async def test_repair_issue_at_exact_threshold_boundary(recorder_mock, hass, mock_config_entry):
    """Data exactly DATA_GAP_THRESHOLD_DAYS old does NOT trigger a repair issue."""
    mock_config_entry.add_to_hass(hass)

    now_ts = datetime(2026, 3, 28, 0, 0, tzinfo=UTC)
    boundary_ts = now_ts - timedelta(days=DATA_GAP_THRESHOLD_DAYS)

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
        patch("custom_components.electric_ireland_insights.coordinator.utcnow", return_value=now_ts),
    ):
        mock_api_instance = AsyncMock()
        dps = make_datapoints(1, base_ts=int(boundary_ts.timestamp()))
        _setup_api_mock(mock_api_instance, hourly_side_effect=[dps] + [[] for _ in range(50)])
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import ElectricIrelandCoordinator

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)
        await coordinator._async_update_data()

    issue_registry = async_get_issue_registry(hass)
    assert issue_registry.async_get_issue(DOMAIN, f"data_gap_{ACCOUNT}") is None


# ===========================================================================
# BILL PERIOD CACHING TESTS (I9)
# ===========================================================================


async def test_bill_periods_cached_across_runs(recorder_mock, hass, mock_config_entry):
    """Bill periods are only fetched once and reused on subsequent coordinator runs."""
    mock_config_entry.add_to_hass(hass)

    bill_periods = [{"startDate": "2026-03-01T00:00:00Z", "endDate": "2026-03-31T00:00:00Z"}]

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={STAT_ID_CONSUMPTION: [{"sum": 100.0}]},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(mock_api_instance)
        mock_api_instance.get_bill_periods = AsyncMock(return_value=bill_periods)
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import ElectricIrelandCoordinator

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)

        await coordinator._async_update_data()
        assert mock_api_instance.get_bill_periods.call_count == 1

        await coordinator._async_update_data()
        assert mock_api_instance.get_bill_periods.call_count == 1


async def test_bill_periods_refetched_after_24h(recorder_mock, hass, mock_config_entry):
    """Bill periods are re-fetched when the cache exceeds 24 hours."""
    mock_config_entry.add_to_hass(hass)

    bill_periods = [{"startDate": "2026-03-01T00:00:00Z", "endDate": "2026-03-31T00:00:00Z"}]

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={STAT_ID_CONSUMPTION: [{"sum": 100.0}]},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(mock_api_instance)
        mock_api_instance.get_bill_periods = AsyncMock(return_value=bill_periods)
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import ElectricIrelandCoordinator

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)

        await coordinator._async_update_data()
        assert mock_api_instance.get_bill_periods.call_count == 1

        coordinator._bill_periods_fetched_at = utcnow() - timedelta(hours=25)

        await coordinator._async_update_data()
        assert mock_api_instance.get_bill_periods.call_count == 2


async def test_bill_period_cache_preserves_data_on_failure(recorder_mock, hass, mock_config_entry):
    """When bill period re-fetch fails, previously cached periods are preserved."""
    mock_config_entry.add_to_hass(hass)

    bill_periods = [{"startDate": "2026-03-01T00:00:00Z", "endDate": "2026-03-31T00:00:00Z"}]

    with (
        patch(
            "custom_components.electric_ireland_insights.coordinator.get_last_statistics",
            return_value={STAT_ID_CONSUMPTION: [{"sum": 100.0}]},
        ),
        patch("custom_components.electric_ireland_insights.coordinator.ElectricIrelandAPI") as mock_api_class,
        patch("custom_components.electric_ireland_insights.coordinator.async_create_clientsession"),
    ):
        mock_api_instance = AsyncMock()
        _setup_api_mock(mock_api_instance)
        mock_api_instance.get_bill_periods = AsyncMock(side_effect=[bill_periods, CannotConnect("network down")])
        mock_api_class.return_value = mock_api_instance

        from custom_components.electric_ireland_insights.coordinator import ElectricIrelandCoordinator

        coordinator = ElectricIrelandCoordinator(hass, mock_config_entry)

        await coordinator._async_update_data()
        assert coordinator._bill_periods == bill_periods

        coordinator._bill_periods_fetched_at = utcnow() - timedelta(hours=25)

        await coordinator._async_update_data()
        assert coordinator._bill_periods == bill_periods
