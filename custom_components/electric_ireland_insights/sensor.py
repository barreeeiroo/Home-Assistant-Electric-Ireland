import calendar
import logging
from datetime import datetime, timezone

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, CURRENCY_EURO
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DEFAULT_BILLING_DAY, DEFAULT_LOOKUP_DAYS
from .sensor_base import Sensor

LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_devices: AddEntitiesCallback,
):
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    # NumberSelector returns float — cast to int
    billing_day = int(config_entry.data.get("billing_day", DEFAULT_BILLING_DAY))
    lookup_days = int(config_entry.data.get("lookup_days", DEFAULT_LOOKUP_DAYS))
    account_number = config_entry.data.get("account_number")

    async_add_devices([
        ConsumptionSensor(coordinator, config_entry.entry_id, lookup_days, account_number),
        CostSensor(coordinator, config_entry.entry_id, lookup_days, account_number),
        BillingConsumptionSensor(coordinator, config_entry.entry_id, billing_day, account_number),
        BillingCostSensor(coordinator, config_entry.entry_id, billing_day, account_number),
    ])


class ConsumptionSensor(Sensor):
    def __init__(self, coordinator, device_id, lookup_days, account_number=None):
        super().__init__(coordinator, device_id, "Consumption", "consumption",
                         UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, unit_class="energy",
                         lookup_days=lookup_days, account_number=account_number)


class CostSensor(Sensor):
    def __init__(self, coordinator, device_id, lookup_days, account_number=None):
        super().__init__(coordinator, device_id, "Cost", "cost",
                         CURRENCY_EURO, SensorDeviceClass.MONETARY, unit_class=None,
                         lookup_days=lookup_days, account_number=account_number)

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        datapoints = self.coordinator.data or []
        cost_values = [dp["cost"] for dp in datapoints if isinstance(dp.get("cost"), (int, float))]
        attrs["average_hourly_value"] = round(sum(cost_values) / len(cost_values), 4) if cost_values else None
        attrs["latest_hour_value"] = cost_values[-1] if cost_values else None
        return attrs


def _billing_start(now: datetime, billing_day: int) -> datetime:
    # Clamp billing_day to the actual number of days in the target month to
    # avoid ValueError when billing_day=31 but the month has fewer days.
    def safe_day(year, month, day):
        return min(day, calendar.monthrange(year, month)[1])

    if now.day >= billing_day:
        return datetime(now.year, now.month, safe_day(now.year, now.month, billing_day), tzinfo=timezone.utc)
    prev_month = now.month - 1 or 12
    prev_year = now.year if now.month > 1 else now.year - 1
    return datetime(prev_year, prev_month, safe_day(prev_year, prev_month, billing_day), tzinfo=timezone.utc)


class BillingSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = True
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator, device_id, name, metric, unit, device_class, billing_day, account_number=None):
        super().__init__(coordinator)
        self._attr_name = f"Electric Ireland {name}"
        self._attr_unique_id = f"{DOMAIN}_{metric}_billing_{device_id}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._metric = metric
        self._billing_day = billing_day
        self._account_number = account_number

    def _billing_datapoints(self):
        cutoff = _billing_start(datetime.now(timezone.utc), self._billing_day)
        return [
            dp for dp in (self.coordinator.data or [])
            if isinstance(dp.get(self._metric), (int, float))
            and dp.get("intervalEnd") is not None
            and datetime.fromtimestamp(dp["intervalEnd"], tz=timezone.utc) >= cutoff
        ]

    @property
    def native_value(self):
        return round(sum(dp[self._metric] for dp in self._billing_datapoints()), 2)

    @property
    def extra_state_attributes(self):
        dps = self._billing_datapoints()
        values = [dp[self._metric] for dp in dps]
        timestamps = [datetime.fromtimestamp(dp["intervalEnd"], tz=timezone.utc) for dp in dps]
        cutoff = _billing_start(datetime.now(timezone.utc), self._billing_day)
        period_days = (datetime.now(timezone.utc).date() - cutoff.date()).days + 1
        return {
            "start_date": timestamps[0].isoformat() if timestamps else cutoff.isoformat(),
            "end_date": timestamps[-1].isoformat() if timestamps else None,
            "period_days": period_days,
            "hours_recorded": len(values),
            "average_daily_value": round(sum(values) / period_days, 4) if values and period_days else None,
        }


class BillingConsumptionSensor(BillingSensor):
    def __init__(self, coordinator, device_id, billing_day, account_number=None):
        super().__init__(coordinator, device_id, "Consumption (Billing Cycle)", "consumption",
                         UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, billing_day, account_number)


class BillingCostSensor(BillingSensor):
    def __init__(self, coordinator, device_id, billing_day, account_number=None):
        super().__init__(coordinator, device_id, "Cost (Billing Cycle)", "cost",
                         CURRENCY_EURO, SensorDeviceClass.MONETARY, billing_day, account_number)

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        values = [dp["cost"] for dp in self._billing_datapoints()]
        attrs["average_hourly_value"] = round(sum(values) / len(values), 4) if values else None
        attrs["latest_hour_value"] = values[-1] if values else None
        return attrs
