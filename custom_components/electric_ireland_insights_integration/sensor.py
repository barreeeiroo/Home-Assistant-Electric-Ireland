import logging
from datetime import timedelta, datetime
import csv
from io import StringIO
from abc import abstractmethod

from homeassistant.const import UnitOfEnergy
from homeassistant.helpers.entity import Entity

from custom_components.electric_ireland_insights_integration.api import ElectricIrelandScraper


LOGGER = logging.getLogger(__name__)

MIN_TIME_BETWEEN_UPDATES = timedelta(hours=12)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the Electric Ireland Insights sensor."""
    pass


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the Electric Ireland Insights sensor based on a config entry."""
    username = entry.data["username"]
    password = entry.data["password"]
    account_number = entry.data["account_number"]

    ei_api = EICachingApi(EIDataApi(hass=hass,
                                    username=username,
                                    password=password,
                                    account_number=account_number))

    now = datetime.now()
    last_month = now - timedelta(days=30)
    async_add_entities([
        BaseSensor(esb_api=ei_api, name='Electric Ireland Electricity Usage: Last Month', mode="month", target_date=last_month)
    ], True)


class BaseSensor(Entity):
    def __init__(self, *, esb_api, name, mode, target_date):
        self._name = name
        self._state = None
        self._esb_api = esb_api
        self._mode = mode
        self._target_date = target_date

    @property
    def name(self):
        return self._name

    @property
    def state(self):
        return self._state

    @property
    def unit_of_measurement(self):
        return UnitOfEnergy.KILO_WATT_HOUR

    @abstractmethod
    def _get_data(self, *, esb_data):
        pass

    @staticmethod
    def __sum_datapoints(datapoints):
        return sum([d["consumption"] for d in datapoints])

    async def async_update(self):
        datapoints = self._esb_api.fetch(self._mode, self._target_date)
        self._state = BaseSensor.__sum_datapoints(datapoints)


class EICachingApi:
    """To not poll Electric Ireland constantly. The data only updates like once a day anyway."""

    def __init__(self, ei_api) -> None:
        self._ei_api = ei_api
        self._cached_data = None
        self._cached_data_timestamp = None

    async def fetch(self, mode, target_date):
        if self._cached_data_timestamp is None or \
                self._cached_data_timestamp < datetime.now() - MIN_TIME_BETWEEN_UPDATES:
            try:
                self._cached_data = await self._ei_api.fetch(mode, target_date)
                self._cached_data_timestamp = datetime.now()
            except Exception as err:
                LOGGER.error('Error fetching data: %s', err)
                self._cached_data = None
                self._cached_data_timestamp = None
                raise err

        return self._cached_data


class EIDataApi:
    """Class for handling the data retrieval."""

    def __init__(self, *, hass, username, password, account_number):
        """Initialize the data object."""
        self._hass = hass
        self._ei = ElectricIrelandScraper(username, password, account_number)

    @staticmethod
    def __csv_to_dict(csv_data):
        reader = csv.DictReader(StringIO(csv_data))
        return [r for r in reader]

    async def fetch(self, mode, target_date):
        await self._hass.async_add_executor_job(self._ei.refresh_credentials)
        datapoints = await self._hass.async_add_executor_job(self._ei.scraper.get_data, mode, target_date)
        return datapoints
