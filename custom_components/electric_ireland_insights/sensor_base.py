import itertools
import logging
import statistics
from datetime import datetime, timedelta, UTC

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData, StatisticMeanType
from homeassistant.components.recorder.statistics import async_add_external_statistics, get_last_statistics
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import DOMAIN, DEFAULT_LOOKUP_DAYS

LOGGER = logging.getLogger(DOMAIN)


class Sensor(CoordinatorEntity, SensorEntity):
    #
    # Base classes:
    # - SensorEntity: This is a sensor, obvious
    # - CoordinatorEntity: Subscribes to DataUpdateCoordinator updates
    #

    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = True
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: DataUpdateCoordinator, device_id: str, name: str, metric: str,
                 unit: str, device_class: SensorDeviceClass, unit_class: str | None = None,
                 lookup_days: int = DEFAULT_LOOKUP_DAYS, account_number: str | None = None):
        super().__init__(coordinator)

        self._attr_name = f"Electric Ireland {name}"
        # device_id (config entry id) is included so two accounts never share a statistic_id
        self._attr_unique_id = f"{DOMAIN}_{metric}_{device_id}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._metric = metric
        self._unit_class = unit_class
        self._lookup_days = lookup_days
        self._account_number = account_number
        # statistic_id includes device_id to avoid collision across multiple accounts
        self._statistic_id = f"{DOMAIN}:{metric}_{device_id.replace('-', '_').lower()}"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Only import on startup — coordinator refresh will call _handle_coordinator_update
        # for subsequent updates, avoiding double import on init.
        if self.coordinator.data:
            await self._import_statistics()

    @property
    def native_value(self):
        datapoints = self.coordinator.data or []
        values = [dp[self._metric] for dp in datapoints if isinstance(dp.get(self._metric), (int, float))]
        return round(sum(values), 2) if values else None

    @property
    def extra_state_attributes(self):
        datapoints = self.coordinator.data or []
        values = [dp[self._metric] for dp in datapoints if isinstance(dp.get(self._metric), (int, float))]
        timestamps = [
            datetime.fromtimestamp(dp["intervalEnd"], tz=UTC)
            for dp in datapoints
            if isinstance(dp.get(self._metric), (int, float))
        ]
        missing = sum(1 for dp in datapoints if dp.get(self._metric) is None)
        invalid = sum(1 for dp in datapoints if dp.get(self._metric) is not None and not isinstance(dp.get(self._metric), (int, float)))

        return {
            "account_number": self._account_number,
            "period_days": self._lookup_days,
            "start_date": timestamps[0].isoformat() if timestamps else None,
            "end_date": timestamps[-1].isoformat() if timestamps else None,
            "latest_hour_timestamp": timestamps[-1].isoformat() if timestamps else None,
            "hours_recorded": len(values),
            "missing_hours": missing,
            "invalid_hours": invalid,
            "average_daily_value": round(sum(values) / self._lookup_days, 4) if values else None,
            "max_hourly_value": max(values) if values else None,
            "min_hourly_value": min(values) if values else None,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        # Coordinator fires listeners synchronously — schedule the async import as a task,
        # then immediately update state so the sensor doesn't freeze between refreshes.
        self.hass.async_create_task(self._import_statistics())
        self.async_write_ha_state()

    async def _import_statistics(self) -> None:
        # Push historical datapoints into the recorder via async_add_external_statistics.
        # This replaces the homeassistant-historical-sensor library, which caused
        # StaleDataError races on MariaDB/SQLite (issues #4, #13).
        datapoints = self.coordinator.data or []
        if not datapoints:
            return

        hist = sorted(
            [
                (datetime.fromtimestamp(dp["intervalEnd"], tz=UTC), dp.get(self._metric))
                for dp in datapoints
                if isinstance(dp.get(self._metric), (int, float))
            ],
            key=lambda x: x[0],
        )

        if not hist:
            return

        # Find the last recorded sum so we can resume accumulation from that point.
        # We only re-import buckets that are newer than what's already in the DB,
        # so the cumulative sum is never double-counted across refreshes.
        last_stats = await get_instance(self.hass).async_add_executor_job(
            lambda: get_last_statistics(self.hass, 1, self._statistic_id, True, {"sum", "start"})
        )
        if last_stats and self._statistic_id in last_stats:
            last_row = last_stats[self._statistic_id][0]
            accumulated = last_row.get("sum") or 0
            s = last_row.get("start") or 0
            last_start_ts = s.timestamp() if isinstance(s, datetime) else float(s)
        else:
            accumulated = 0
            last_start_ts = 0

        def hour_block(dt: datetime) -> datetime:
            # XX:00:00 states belong to previous hour block
            if dt.minute == 0 and dt.second == 0:
                dt = dt - timedelta(hours=1)
            return dt.replace(minute=0, second=0, microsecond=0)

        #
        # Group historical states by hour
        # Calculate sum, mean, etc...
        # Only process buckets after the last already-stored bucket.
        #
        stat_data = []
        for dt, group in itertools.groupby(hist, key=lambda x: hour_block(x[0])):
            if dt.timestamp() <= last_start_ts:
                continue
            values = [v for _, v in group]
            partial = sum(values)
            accumulated += partial
            stat_data.append(StatisticData(
                start=dt,
                state=partial,
                mean=statistics.mean(values),
                sum=accumulated,
            ))

        if not stat_data:
            return

        #
        # Add sum and mean to statistics metadata.
        # mean_type must be set explicitly to avoid HA 2026.11 deprecation warning (issue #14).
        #
        metadata = StatisticMetaData(
            has_mean=True,
            mean_type=StatisticMeanType.ARITHMETIC,
            has_sum=True,
            name=self._attr_name,
            source=DOMAIN,
            statistic_id=self._statistic_id,
            unit_of_measurement=self._attr_native_unit_of_measurement,
            unit_class=self._unit_class,
        )

        async_add_external_statistics(self.hass, metadata, stat_data)
        LOGGER.info(f"Imported {len(stat_data)} new hourly stat buckets for {self._metric}")
