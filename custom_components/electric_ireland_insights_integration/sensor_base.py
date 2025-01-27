import asyncio
import itertools
import statistics
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
from .const import DOMAIN


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
        self._attr_name = name

        self._attr_unique_id = f"{DOMAIN}_{device_id}"
        self._attr_entity_id = f"{DOMAIN}_{device_id}"

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

        now = datetime.now()
        current_date = now - timedelta(days=10)
        while current_date <= now:
            datapoints = await loop.run_in_executor(None, scraper.get_data, current_date)
            for datapoint in datapoints:
                hist_states.append(HistoricalState(
                    state=datapoint[self._metric],
                    dt=datetime.fromtimestamp(datapoint["intervalEnd"], tz=UTC),
                ))
            current_date += timedelta(days=1)

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
        for dt, collection_it in itertools.groupby(
                hist_states, key=hour_block_for_hist_state
        ):
            collection = list(collection_it)
            mean = statistics.mean([x.state or 0 for x in collection])
            partial_sum = sum([x.state or 0 for x in collection])
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
