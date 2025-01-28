import asyncio
import itertools
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, UTC
from typing import List

from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity

from homeassistant_historical_sensor import (
    HistoricalSensor,
    HistoricalState,
    PollUpdateMixin,
)

from .api import ElectricIrelandScraper, BidgelyScraper
from .const import DOMAIN, LOOKUP_DAYS, PARALLEL_DAYS


class Sensor(PollUpdateMixin, HistoricalSensor, SensorEntity):
    #
    # Base clases:
    # - SensorEntity: This is a sensor, obvious
    # - HistoricalSensor: This sensor implements historical sensor methods
    # - PollUpdateMixin: Historical sensors disable poll, this mixing
    #                    reenables poll only for historical states and not for
    #                    present state
    #

    def __init__(self, device_id: str, ei_api: ElectricIrelandScraper, name: str, metric: str, measurement_unit: str, device_class: SensorDeviceClass):
        super().__init__()

        self._attr_has_entity_name = True
        self._attr_name = f"Electric Ireland {name}"

        self._attr_unique_id = f"{DOMAIN}_{metric}_{device_id}"
        self._attr_entity_id = f"{DOMAIN}_{metric}_{device_id}"

        self._attr_entity_registry_enabled_default = True
        self._attr_state = None

        # Define whatever you are
        self._attr_native_unit_of_measurement = measurement_unit
        self._attr_device_class = device_class

        self._api: ElectricIrelandScraper = ei_api
        self._metric = metric

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

    async def async_update_historical(self):
        # Fill `HistoricalSensor._attr_historical_states` with HistoricalState's
        # This functions is equivaled to the `Sensor.async_update` from
        # HomeAssistant core
        #
        # Important: You must provide datetime with tzinfo

        loop = asyncio.get_running_loop()

        await loop.run_in_executor(None, self._api.refresh_credentials)
        scraper: BidgelyScraper = self._api.scraper

        hist_states: List[HistoricalState] = []

        # We get the current time in UTC
        now = datetime.now(UTC)
        # Now, we build a datetime object with no time in UTC with the current date, but as of "yesterday" (as data is
        #   never published on the day after)
        today = datetime(year=now.year, month=now.month, day=now.day, tzinfo=UTC) - timedelta(days=1)

        # We store here a list of Futures, where each Future is a day and it contains a list of datapoints
        executor_results = []

        with ThreadPoolExecutor(max_workers=PARALLEL_DAYS) as executor:
            # We generate all the days to look up for, up to LOOKUP_DAYS
            current_date = today - timedelta(days=LOOKUP_DAYS + 1)
            while current_date <= now:
                # We launch a job for the target date, and we put it to the full list of results
                results = loop.run_in_executor(executor, scraper.get_data, current_date, self._metric == "consumption")
                executor_results.append(results)
                current_date += timedelta(days=1)

        # For every launched job
        for executor_result in results:
            # Now we block and wait for the result
            datapoints = await executor_result
            # And now we parse the datapoints
            for datapoint in datapoints:
                state = datapoint.get(self._metric)
                if state is None or not isinstance(state, (int, float,)):
                    continue

                hist_states.append(HistoricalState(
                    state=state,
                    dt=datetime.fromtimestamp(datapoint["intervalEnd"], tz=UTC),
                ))

        self._attr_historical_states = hist_states

    @property
    def statistic_id(self) -> str:
        return self.entity_id

    def get_statistic_metadata(self) -> StatisticMetaData:
        #
        # Add sum and mean to base statistics metadata
        # Important: HistoricalSensor.get_statistic_metadata returns an
        # internal source by default.
        #
        meta = super().get_statistic_metadata()
        meta["has_sum"] = True
        meta["has_mean"] = True

        return meta

    async def async_calculate_statistic_data(
            self, hist_states: list[HistoricalState], *, latest: dict | None = None
    ) -> list[StatisticData]:
        #
        # Group historical states by hour
        # Calculate sum, mean, etc...
        #

        accumulated = latest["sum"] if latest else 0

        def hour_block_for_hist_state(hist_state: HistoricalState) -> datetime:
            # XX:00:00 states belongs to previous hour block
            if hist_state.dt.minute == 0 and hist_state.dt.second == 0:
                dt = hist_state.dt - timedelta(hours=1)
                return dt.replace(minute=0, second=0, microsecond=0)

            else:
                return hist_state.dt.replace(minute=0, second=0, microsecond=0)

        ret = []
        for dt, collection_it in itertools.groupby(hist_states, key=hour_block_for_hist_state):
            collection = list(collection_it)
            mean = statistics.mean([x.state for x in collection])
            partial_sum = sum([x.state for x in collection])
            accumulated = accumulated + partial_sum

            ret.append(
                StatisticData(
                    start=dt,
                    state=partial_sum,
                    mean=mean,
                    sum=accumulated,
                )
            )

        return ret
