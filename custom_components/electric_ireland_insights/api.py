import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

import requests
from bs4 import BeautifulSoup
from requests import RequestException

from .const import DOMAIN
from .utils import date_to_unix

LOGGER = logging.getLogger(DOMAIN)

# Request timeout in seconds
REQUEST_TIMEOUT = 30


class ElectricIrelandScraper:
    """Scraper for Electric Ireland website to obtain Bidgely API credentials."""

    def __init__(self, username: str, password: str, account_number: str) -> None:
        """Initialize the scraper.

        Args:
            username: Electric Ireland account username
            password: Electric Ireland account password
            account_number: Electric Ireland account number
        """
        self.__bidgely: Optional[BidgelyScraper] = None

        self.__username = username
        self.__password = password
        self.__account_number = account_number

    def refresh_credentials(self) -> None:
        """Refresh Bidgely API credentials by logging into Electric Ireland."""
        LOGGER.info("Trying to refresh credentials...")
        session = requests.Session()

        bidgely_token = self.__get_bidgely_token(session)
        if not bidgely_token:
            return

        self.__bidgely = BidgelyScraper(session, bidgely_token)

    @property
    def scraper(self) -> Optional['BidgelyScraper']:
        """Get the Bidgely scraper instance, refreshing credentials if needed."""
        if not self.__bidgely:
            self.refresh_credentials()
        return self.__bidgely

    def __get_bidgely_token(self, session: requests.Session) -> Optional[str]:
        """Obtain Bidgely API token by logging into Electric Ireland.

        Args:
            session: Requests session to use for HTTP calls

        Returns:
            Bidgely API token if successful, None otherwise
        """
        # REQUEST 1: Get the Source token, and initialize the session
        LOGGER.debug("Getting Source Token...")
        try:
            res1 = session.get(
                "https://youraccountonline.electricireland.ie/",
                timeout=REQUEST_TIMEOUT
            )
            res1.raise_for_status()
        except RequestException as err:
            LOGGER.error(f"Failed to Get Source Token: {err}")
            return None

        soup1 = BeautifulSoup(res1.text, "html.parser")
        source_input = soup1.find('input', attrs={'name': 'Source'})
        if not source_input:
            LOGGER.error("Could not find Source input field in page")
            return None
        source = source_input.get('value')

        rvt = session.cookies.get_dict().get("rvt")

        if not source:
            LOGGER.error("Could not retrieve Source value")
            return None
        if not rvt:
            LOGGER.error("Could not find rvt cookie")
            return None

        # REQUEST 2: Perform Login
        LOGGER.debug("Performing Login...")
        try:
            res2 = session.post(
                "https://youraccountonline.electricireland.ie/",
                data={
                    "LoginFormData.UserName": self.__username,
                    "LoginFormData.Password": self.__password,
                    "rvt": rvt,
                    "Source": source,
                    "PotText": "",
                    "__EiTokPotText": "",
                    "ReturnUrl": "",
                    "AccountNumber": "",
                },
                timeout=REQUEST_TIMEOUT
            )
            res2.raise_for_status()
        except RequestException as err:
            LOGGER.error(f"Failed to Perform Login: {err}")
            return None

        soup2 = BeautifulSoup(res2.text, "html.parser")
        account_divs = soup2.find_all("div", {"class": "my-accounts__item"})
        target_account = None
        for account_div in account_divs:
            account_number_elem = account_div.find("p", {"class": "account-number"})
            if not account_number_elem:
                LOGGER.debug("Skipping account div without account number")
                continue

            account_number = account_number_elem.text
            if account_number != self.__account_number:
                LOGGER.debug(f"Skipping account {account_number} as it is not target")
                continue

            is_elec_divs = account_div.find_all("h2", {"class": "account-electricity-icon"})
            if len(is_elec_divs) != 1:
                LOGGER.info(f"Found account {account_number} but is not Electricity")
                continue

            target_account = account_div
            break

        if not target_account:
            LOGGER.warning("Failed to find Target Account; please verify it is the correct one")
            return None

        # REQUEST 3: Perform "Insights" Navigation to retrieve Bidgely Token
        LOGGER.debug("Perform Insights Navigation...")
        event_form = target_account.find("form", {"action": "/Accounts/OnEvent"})
        if not event_form:
            LOGGER.error("Could not find event form for Insights navigation")
            return None

        req3 = {"triggers_event": "AccountSelection.ToInsights"}
        for form_input in event_form.find_all("input"):
            input_name = form_input.get("name")
            input_value = form_input.get("value")
            if input_name:
                req3[input_name] = input_value

        try:
            res3 = session.post(
                "https://youraccountonline.electricireland.ie/Accounts/OnEvent",
                data=req3,
                timeout=REQUEST_TIMEOUT
            )
            res3.raise_for_status()
        except RequestException as err:
            LOGGER.error(f"Failed to Perform Insights Navigation: {err}")
            return None

        soup3 = BeautifulSoup(res3.text, "html.parser")
        scripts = soup3.find_all("script")
        bidgely_payload = None
        for script in scripts:
            if "bidgelyWebSdkPayload" not in script.text:
                continue

            for line in script.text.strip().split("\n"):
                if "bidgelyWebSdkPayload" not in line:
                    continue
                _, value = line.strip().split(" = ")
                bidgely_payload = value.strip()[1:-2]

        if not bidgely_payload:
            LOGGER.error("Failed to find Bidgely token")
            return None

        return bidgely_payload


class BidgelyScraper:
    """Scraper for Bidgely API to fetch energy usage data."""

    def __init__(self, session: requests.Session, bidgely_payload: str) -> None:
        """Initialize the Bidgely scraper.

        Args:
            session: Requests session to use for HTTP calls
            bidgely_payload: Authentication payload for Bidgely API
        """
        self.__session = session
        self.__access_token: Optional[str] = None
        self.__user_id: Optional[str] = None
        self.__access_token, self.__user_id = self.__get_auth(bidgely_payload)

    def __get_auth(self, bidgely_payload: str) -> tuple[Optional[str], Optional[str]]:
        """Get Bidgely authentication details.

        Args:
            bidgely_payload: Authentication payload for Bidgely API

        Returns:
            Tuple of (access_token, user_id) or (None, None) if failed
        """
        if not bidgely_payload:
            return None, None

        # REQUEST 4: Get Bidgely Auth Details
        LOGGER.debug("Getting Auth Details...")
        try:
            res4 = self.__session.post(
                "https://ssoprod.bidgely.com/prod-na/widgetSso",
                headers={
                    "Origin": "https://ssoprod.bidgely.com",
                },
                json={
                    "params": {
                        "payload": bidgely_payload,
                        "allDetails": True,
                    }
                },
                timeout=REQUEST_TIMEOUT
            )
            res4.raise_for_status()
        except RequestException as err:
            LOGGER.error(f"Failed to Get Auth Details: {err}")
            return None, None

        res4_json = res4.json()

        access_token = res4_json.get("tokenDetails", {}).get("accessToken")
        user_id = res4_json.get("userProfileDetails", {}).get("userId")

        return access_token, user_id

    def get_data(self, target_date: datetime, is_granular: bool = False) -> Optional[List[Dict[str, Any]]]:
        """Get usage data for a specific date.

        Args:
            target_date: Date to fetch data for
            is_granular: Whether to fetch granular (30-min) or hourly data

        Returns:
            List of data points if successful, None otherwise
        """
        if not self.__user_id:
            return None

        # REQUEST 5: Get Data
        LOGGER.debug(f"Getting Data for {target_date}...")
        try:
            res5 = self.__session.get(
                f"https://api.eu.bidgely.com/v2.0/dashboard/users/{self.__user_id}/usage-chart-details",
                headers={
                    "Authorization": f"Bearer {self.__access_token}",
                    "Origin": "https://ssoprod.bidgely.com",
                },
                params={
                    "measurement-type": "ELECTRIC",
                    "mode": "day",
                    "start": date_to_unix(target_date),
                    "end": date_to_unix(target_date + timedelta(days=1) - timedelta(seconds=1)),
                    "date-format": "DATE_TIME",
                    "locale": "en_IE",
                    "next-bill-cycle": "false",
                    "show-at-granularity": "true" if is_granular else "false",
                    "skip-ongoing-cycle": "false",
                },
                timeout=REQUEST_TIMEOUT
            )
            res5.raise_for_status()
        except RequestException as err:
            LOGGER.error(f"Failed to Get Data: {err}")
            return None

        data = res5.json()
        datapoints = data.get("payload", {}).get("usageChartDataList", [])
        LOGGER.debug(f"Found {len(datapoints)} for {target_date}")

        return datapoints
