"""Coordinator for Electric Ireland Insights."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Literal

import aiohttp
from homeassistant.components.recorder import get_instance  # type: ignore[attr-defined]
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue, async_delete_issue
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.dt import now as dt_now
from homeassistant.util.dt import utcnow

from .api import ElectricIrelandAPI
from .const import DATA_GAP_THRESHOLD_DAYS, DOMAIN, INITIAL_LOOKBACK_DAYS, LOOKUP_DAYS, SCAN_INTERVAL
from .exceptions import CachedIdsInvalid, CannotConnect, InvalidAuth
from .types import (
    BillPeriod,
    CoordinatorData,
    ElectricIrelandDatapoint,
    MeterIds,
)

_LOGGER = logging.getLogger(__name__)

TARIFF_BUCKET_MAP_DISPLAY: dict[str, str] = {
    "flat_rate": "Flat Rate",
    "off_peak": "Off-Peak",
    "mid_peak": "Mid-Peak",
    "on_peak": "On-Peak",
}


class ElectricIrelandCoordinator(DataUpdateCoordinator[CoordinatorData]):  # type: ignore[misc]
    """Coordinator to fetch EI data and import external statistics."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
            always_update=True,
        )
        self._config_entry = config_entry
        self._account = config_entry.data["account_number"]
        self._api = ElectricIrelandAPI(
            config_entry.data["username"],
            config_entry.data["password"],
            self._account,
        )
        self._last_update_success = True
        self._has_imported_before = False
        self._bill_periods: list[BillPeriod] = []
        self._bill_periods_fetched_at: datetime | None = None
        self._session = async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar())

    def _check_data_gap(self, result: CoordinatorData) -> None:
        latest_ts = result.get("latest_data_timestamp")
        if latest_ts is not None:
            gap_days = (utcnow() - latest_ts).total_seconds() / 86400
            if gap_days > DATA_GAP_THRESHOLD_DAYS:
                async_create_issue(
                    self.hass,
                    DOMAIN,
                    f"data_gap_{self._account}",
                    is_fixable=False,
                    severity=IssueSeverity.WARNING,
                    translation_key="data_gap",
                    translation_placeholders={
                        "account": self._account,
                        "days": str(round(gap_days, 1)),
                    },
                )
            else:
                async_delete_issue(self.hass, DOMAIN, f"data_gap_{self._account}")

    async def _async_update_data(self) -> CoordinatorData:
        session = self._session
        was_successful = self._last_update_success

        def _mark_success(result: CoordinatorData) -> CoordinatorData:
            self._last_update_success = True
            if not was_successful:
                _LOGGER.info("Connection restored — data import resumed")
            self._check_data_gap(result)
            return result

        try:
            stat_id = f"{DOMAIN}:{self._account}_consumption"
            statistic_types: set[Literal["last_reset", "max", "mean", "min", "state", "sum"]] = {"sum"}
            existing = await get_instance(self.hass).async_add_executor_job(
                partial(get_last_statistics, self.hass, 1, stat_id, True, statistic_types)
            )
            lookback = LOOKUP_DAYS if existing else INITIAL_LOOKBACK_DAYS

            if not self._has_imported_before:
                self._has_imported_before = bool(existing)

            entry_data = self._config_entry.data
            cached_ids: MeterIds | None = None
            if entry_data.get("partner_id") and entry_data.get("contract_id") and entry_data.get("premise_id"):
                cached_ids = {
                    "partner": entry_data["partner_id"],
                    "contract": entry_data["contract_id"],
                    "premise": entry_data["premise_id"],
                }

            try:
                meter_ids, discovered_ids = await self._api.authenticate(session, cached_ids)
            except CannotConnect:
                if cached_ids is None:
                    raise
                _LOGGER.warning("Cached meter IDs failed during login, falling back to full discovery")
                session.cookie_jar.clear()
                meter_ids, discovered_ids = await self._api.authenticate(session, None)

            if discovered_ids is not None:
                new_data = {
                    **dict(self._config_entry.data),
                    "partner_id": discovered_ids["partner"],
                    "contract_id": discovered_ids["contract"],
                    "premise_id": discovered_ids["premise"],
                }
                self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)
                _LOGGER.debug(
                    "Updated cached meter IDs: partner=%s",
                    discovered_ids["partner"],
                )

            bill_period_stale = (
                self._bill_periods_fetched_at is None
                or (utcnow() - self._bill_periods_fetched_at).total_seconds() > 86400
            )
            if bill_period_stale:
                try:
                    self._bill_periods = await self._api.get_bill_periods(session, meter_ids)
                    self._bill_periods_fetched_at = utcnow()
                except CannotConnect:
                    _LOGGER.warning("Failed to fetch bill periods, falling back to full lookback window")
                    if not self._bill_periods:
                        self._bill_periods = []

            yesterday = (dt_now() - timedelta(days=1)).date()
            all_lookback_dates = {yesterday - timedelta(days=i) for i in range(lookback)}

            if self._bill_periods:
                dates_in_periods: set[date] = set()
                for period in self._bill_periods:
                    period_start = date.fromisoformat(period["startDate"][:10])
                    period_end = date.fromisoformat(period["endDate"][:10])
                    d = period_start
                    while d <= period_end:
                        dates_in_periods.add(d)
                        d += timedelta(days=1)

                dates_to_fetch = dates_in_periods & all_lookback_dates

                if len(dates_to_fetch) < len(all_lookback_dates):
                    _LOGGER.debug(
                        "Billing periods cover %d of %d lookback days; skipping %d dates outside periods",
                        len(dates_to_fetch),
                        len(all_lookback_dates),
                        len(all_lookback_dates) - len(dates_to_fetch),
                    )
            else:
                dates_to_fetch = all_lookback_dates

            datapoints: list[ElectricIrelandDatapoint] = []
            for target_date in sorted(dates_to_fetch):  # SEQUENTIAL — never parallel
                try:
                    day_data = await self._api.get_hourly_usage(
                        session,
                        meter_ids,
                        target_date,
                    )
                    datapoints.extend(day_data)
                except CachedIdsInvalid:
                    _LOGGER.warning(
                        "Cached meter IDs failed during data fetch, re-authenticating",
                    )
                    session.cookie_jar.clear()
                    meter_ids, discovered_ids = await self._api.authenticate(
                        session,
                        None,
                    )
                    if discovered_ids is not None:
                        new_data = {
                            **dict(self._config_entry.data),
                            "partner_id": discovered_ids["partner"],
                            "contract_id": discovered_ids["contract"],
                            "premise_id": discovered_ids["premise"],
                        }
                        self.hass.config_entries.async_update_entry(
                            self._config_entry,
                            data=new_data,
                        )
                    day_data = await self._api.get_hourly_usage(
                        session,
                        meter_ids,
                        target_date,
                    )
                    datapoints.extend(day_data)

            if not datapoints:
                if self._has_imported_before:
                    if self.data is not None:
                        return _mark_success(self.data)
                    return _mark_success(
                        {
                            "last_import": None,
                            "datapoint_count": 0,
                            "latest_data_timestamp": None,
                            "import_error": "No new data available",
                            "appliance_count": 0,
                            "bill_periods_available": 0,
                            "tariff_buckets_seen": 0,
                        }
                    )
                return _mark_success(
                    {
                        "last_import": utcnow(),
                        "datapoint_count": 0,
                        "latest_data_timestamp": None,
                        "import_error": None,
                        "appliance_count": 0,
                        "bill_periods_available": 0,
                        "tariff_buckets_seen": 0,
                    }
                )

            self._has_imported_before = True

            await self._insert_statistics(
                datapoints,
                "consumption",
                f"{DOMAIN}:{self._account}_consumption",
                UnitOfEnergy.KILO_WATT_HOUR,
            )
            await self._insert_statistics(
                datapoints,
                "cost",
                f"{DOMAIN}:{self._account}_cost",
                "EUR",
            )

            buckets: dict[str, list[ElectricIrelandDatapoint]] = {}
            for dp in datapoints:
                buckets.setdefault(dp["tariff_bucket"], []).append(dp)

            seen_buckets = set(buckets.keys())
            if len(seen_buckets) > 1 or (len(seen_buckets) == 1 and "flat_rate" not in seen_buckets):
                for bucket_name, bucket_dps in buckets.items():
                    display = TARIFF_BUCKET_MAP_DISPLAY.get(bucket_name, bucket_name.replace("_", " ").title())
                    await self._insert_statistics(
                        bucket_dps,
                        "consumption",
                        f"{DOMAIN}:{self._account}_consumption_{bucket_name}",
                        UnitOfEnergy.KILO_WATT_HOUR,
                        name_override=f"Electric Ireland Consumption {display} ({self._account})",
                    )
                    await self._insert_statistics(
                        bucket_dps,
                        "cost",
                        f"{DOMAIN}:{self._account}_cost_{bucket_name}",
                        "EUR",
                        name_override=f"Electric Ireland Cost {display} ({self._account})",
                    )

            last_ts = max((dp["intervalEnd"] for dp in datapoints), default=None)
            latest_data_ts = datetime.fromtimestamp(last_ts, tz=UTC) if last_ts else None

            self.hass.bus.async_fire(
                f"{DOMAIN}_data_imported",
                {
                    "account": self._account,
                    "datapoint_count": len(datapoints),
                    "latest_data_timestamp": latest_data_ts.isoformat() if latest_data_ts else None,
                    "tariff_buckets": sorted(seen_buckets),
                },
            )

            return _mark_success(
                {
                    "last_import": utcnow(),
                    "datapoint_count": len(datapoints),
                    "latest_data_timestamp": latest_data_ts,
                    "import_error": None,
                    "appliance_count": 0,
                    "bill_periods_available": len(self._bill_periods),
                    "tariff_buckets_seen": len(seen_buckets),
                }
            )

        except InvalidAuth as err:
            self._last_update_success = False
            raise ConfigEntryAuthFailed from err
        except CannotConnect as err:
            if was_successful:
                _LOGGER.warning(
                    "Connection lost — data import paused: %s",
                    err,
                )
            self._last_update_success = False
            raise UpdateFailed(f"Connection error: {err}") from err
        except (ConfigEntryAuthFailed, UpdateFailed):
            self._last_update_success = False
            raise
        except Exception as err:
            self._last_update_success = False
            _LOGGER.exception("Unexpected error during update")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def async_tariff_backfill(self) -> None:
        """One-time background backfill using all available bill periods.

        Called once after setup when tariff_stats_initialized is unset.
        Uses bill periods to determine the full historical date range, then
        fetches every available day sequentially.
        """
        if self._config_entry.data.get("tariff_stats_initialized"):
            return

        session = async_create_clientsession(self.hass, cookie_jar=aiohttp.CookieJar())
        try:
            meter_ids, _ = await self._api.authenticate(session, None)

            try:
                bill_periods = await self._api.get_bill_periods(session, meter_ids)
            except CannotConnect:
                bill_periods = []

            yesterday = (dt_now() - timedelta(days=1)).date()

            if bill_periods:
                earliest = min(date.fromisoformat(bp["startDate"][:10]) for bp in bill_periods)
                all_dates: set[date] = set()
                d = earliest
                while d <= yesterday:
                    all_dates.add(d)
                    d += timedelta(days=1)
            else:
                all_dates = {yesterday - timedelta(days=i) for i in range(INITIAL_LOOKBACK_DAYS)}

            _LOGGER.info(
                "Starting background backfill (%d days, %s to %s)",
                len(all_dates),
                min(all_dates),
                max(all_dates),
            )

            dates = sorted(all_dates)

            datapoints: list[ElectricIrelandDatapoint] = []
            for target_date in dates:
                try:
                    day_data = await self._api.get_hourly_usage(session, meter_ids, target_date)
                    datapoints.extend(day_data)
                except CachedIdsInvalid:
                    session.cookie_jar.clear()
                    meter_ids, _ = await self._api.authenticate(session, None)
                    day_data = await self._api.get_hourly_usage(session, meter_ids, target_date)
                    datapoints.extend(day_data)

            if datapoints:
                await self._insert_statistics(
                    datapoints,
                    "consumption",
                    f"{DOMAIN}:{self._account}_consumption",
                    UnitOfEnergy.KILO_WATT_HOUR,
                )
                await self._insert_statistics(
                    datapoints,
                    "cost",
                    f"{DOMAIN}:{self._account}_cost",
                    "EUR",
                )

                buckets: dict[str, list[ElectricIrelandDatapoint]] = {}
                for dp in datapoints:
                    buckets.setdefault(dp["tariff_bucket"], []).append(dp)

                seen_buckets = set(buckets.keys())
                if len(seen_buckets) > 1 or (len(seen_buckets) == 1 and "flat_rate" not in seen_buckets):
                    for bucket_name, bucket_dps in buckets.items():
                        display = TARIFF_BUCKET_MAP_DISPLAY.get(bucket_name, bucket_name.replace("_", " ").title())
                        await self._insert_statistics(
                            bucket_dps,
                            "consumption",
                            f"{DOMAIN}:{self._account}_consumption_{bucket_name}",
                            UnitOfEnergy.KILO_WATT_HOUR,
                            name_override=f"Electric Ireland Consumption {display} ({self._account})",
                        )
                        await self._insert_statistics(
                            bucket_dps,
                            "cost",
                            f"{DOMAIN}:{self._account}_cost_{bucket_name}",
                            "EUR",
                            name_override=f"Electric Ireland Cost {display} ({self._account})",
                        )

            new_data = {**dict(self._config_entry.data), "tariff_stats_initialized": True}
            self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)
            _LOGGER.info("Background backfill complete (%d datapoints)", len(datapoints))

        except (InvalidAuth, CannotConnect) as err:
            _LOGGER.warning("Background backfill failed (will retry next restart): %s", err)
        except Exception:
            _LOGGER.exception("Unexpected error during background backfill")

    async def _insert_statistics(
        self,
        datapoints: list[ElectricIrelandDatapoint],
        metric: Literal["consumption", "cost"],
        statistic_id: str,
        unit: str,
        *,
        name_override: str | None = None,
    ) -> None:
        filtered = []
        for dp in datapoints:
            value = dp.get(metric)
            if value is None:
                continue
            interval_end = dp["intervalEnd"]
            start = datetime.fromtimestamp(interval_end, tz=UTC).replace(minute=0, second=0, microsecond=0)
            filtered.append((start, float(value)))

        if not filtered:
            return

        filtered.sort(key=lambda x: x[0])
        overlap_start = filtered[0][0]

        stat_types: set[Literal["change", "last_reset", "max", "mean", "min", "state", "sum"]] = {"sum"}
        existing_before = await get_instance(self.hass).async_add_executor_job(
            partial(
                statistics_during_period,
                self.hass,
                overlap_start - timedelta(days=INITIAL_LOOKBACK_DAYS),
                overlap_start,
                {statistic_id},
                "hour",
                None,
                stat_types,
            )
        )

        base_sum = 0.0
        rows = (existing_before or {}).get(statistic_id, [])
        if rows:
            base_sum = rows[-1].get("sum") or 0.0

        statistics: list[StatisticData] = []
        current_sum = base_sum
        for start, value in filtered:
            current_sum += value
            statistics.append(
                StatisticData(
                    start=start,
                    state=value,
                    sum=current_sum,
                )
            )

        default_name = f"Electric Ireland {'Consumption' if metric == 'consumption' else 'Cost'} ({self._account})"
        metadata_kwargs: dict[str, object] = {
            "has_sum": True,
            "name": name_override or default_name,
            "source": DOMAIN,
            "statistic_id": statistic_id,
            "unit_of_measurement": unit,
        }
        try:
            from homeassistant.components.recorder.models import StatisticMeanType  # type: ignore[attr-defined]

            metadata_kwargs["mean_type"] = StatisticMeanType.NONE
            metadata_kwargs["unit_class"] = "energy" if metric == "consumption" else None
        except ImportError:
            metadata_kwargs["has_mean"] = False
        metadata = StatisticMetaData(**metadata_kwargs)  # type: ignore[arg-type]

        async_add_external_statistics(self.hass, metadata, statistics)
