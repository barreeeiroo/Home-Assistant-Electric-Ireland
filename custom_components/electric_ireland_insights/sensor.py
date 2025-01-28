import logging

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, CURRENCY_EURO
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import DiscoveryInfoType

from .api import ElectricIrelandScraper
from .sensor_base import Sensor

PLATFORM = "sensor"

LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        async_add_devices: AddEntitiesCallback,
        discovery_info: DiscoveryInfoType | None = None,  # noqa DiscoveryInfoType | None
):
    username = config_entry.data["username"]
    password = config_entry.data["password"]
    account_number = config_entry.data["account_number"]

    ei_api = ElectricIrelandScraper(username, password, account_number)

    sensors = [
        ConsumptionSensor(device_id=config_entry.entry_id, ei_api=ei_api),
        CostSensor(device_id=config_entry.entry_id, ei_api=ei_api),
    ]
    async_add_devices(sensors)


class ConsumptionSensor(Sensor):
    def __init__(self, device_id: str, ei_api: ElectricIrelandScraper):
        super().__init__(device_id, ei_api,
                         "Consumption", "consumption",
                         UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY)


class CostSensor(Sensor):
    def __init__(self, device_id: str, ei_api: ElectricIrelandScraper):
        super().__init__(device_id, ei_api,
                         "Cost", "cost",
                         CURRENCY_EURO, SensorDeviceClass.MONETARY)
