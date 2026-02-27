import asyncio
import logging
from datetime import datetime, timedelta, UTC
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass

from .api import ElectricIrelandScraper
from .const import DOMAIN

LOGGER = logging.getLogger(DOMAIN)


class Sensor(SensorEntity):
    """Base sensor for Electric Ireland metrics.

    This forked version intentionally does NOT use homeassistant-historical-sensor.
    It provides a normal HA sensor state (yesterday's total), which is stable and
    compatible with newer Home Assistant versions.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        device_id: str,
        ei_api: ElectricIrelandScraper,
        name: str,
        metric: str,
        measurement_unit: str,
        device_class: SensorDeviceClass,
    ) -> None:
        super().__init__()

        self._api = ei_api
        self._metric = metric
        self._device_id = device_id

        self._attr_name = f"Electric Ireland {name}"
        self._attr_unique_id = f"{DOMAIN}_{metric}_{device_id}"

        self._attr_native_unit_of_measurement = measurement_unit
        self._attr_device_class = device_class

        # This sensor represents a daily total (yesterday).
        # For energy, HA expects total or total_increasing. Daily totals are "total".
        if device_class == SensorDeviceClass.ENERGY:
            self._attr_state_class = SensorStateClass.TOTAL
        elif device_class == SensorDeviceClass.MONETARY:
            self._attr_state_class = SensorStateClass.TOTAL
        else:
            self._attr_state_class = None

        self._attr_native_value = None
        self._attr_extra_state_attributes = {}

    async def async_update(self) -> None:
        """Fetch and update yesterday's total for this metric."""

        loop = asyncio.get_running_loop()

        # Refresh credentials (run in executor if it's blocking)
        try:
            await loop.run_in_executor(None, self._api.refresh_credentials)
        except Exception:  # noqa: BLE001
            LOGGER.exception("Failed to refresh Electric Ireland credentials")
            self._attr_native_value = None
            return

        scraper = self._api.scraper
        if not scraper:
            LOGGER.error("Failed to get scraper - login may have failed")
            self._attr_native_value = None
            return

        now = datetime.now(UTC)
        yesterday = datetime(year=now.year, month=now.month,
                             day=now.day, tzinfo=UTC) - timedelta(days=1)

        # Fetch datapoints for yesterday. The original integration expects datapoints
        # with keys including `intervalEnd` and your metric field (kWh/cost).
        try:
            datapoints = await loop.run_in_executor(None, scraper.get_data, yesterday)
        except Exception:  # noqa: BLE001
            LOGGER.exception(
                "Failed to fetch Electric Ireland data for %s", yesterday.date())
            self._attr_native_value = None
            return

        if not datapoints:
            LOGGER.warning("No datapoints returned for %s", yesterday.date())
            self._attr_native_value = None
            self._attr_extra_state_attributes = {
                "date": str(yesterday.date()),
                "points": 0,
            }
            return

        total = 0.0
        valid_points = 0
        last_interval_end: int | None = None

        for dp in datapoints:
            value = dp.get(self._metric)
            interval_end = dp.get("intervalEnd")

            if interval_end is not None:
                try:
                    last_interval_end = max(
                        last_interval_end or interval_end, interval_end)
                except TypeError:
                    # If intervalEnd is malformed, ignore it
                    pass

            if value is None:
                continue
            if not isinstance(value, (int, float)):
                continue

            total += float(value)
            valid_points += 1

        # If nothing usable, mark unknown
        if valid_points == 0:
            LOGGER.warning("No valid datapoints for metric '%s' on %s",
                           self._metric, yesterday.date())
            self._attr_native_value = None
        else:
            # Round: energy often 3dp, cost often 2dp; keep it simple and not over-round here.
            self._attr_native_value = total

        attrs: dict[str, Any] = {
            "date": str(yesterday.date()),
            "points": len(datapoints),
            "valid_points": valid_points,
        }

        if last_interval_end is not None:
            try:
                attrs["last_interval_end"] = datetime.fromtimestamp(
                    last_interval_end, tz=UTC).isoformat()
            except Exception:  # noqa: BLE001
                attrs["last_interval_end"] = last_interval_end

        self._attr_extra_state_attributes = attrs
