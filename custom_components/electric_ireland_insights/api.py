import logging
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from requests import RequestException

from .const import DOMAIN


LOGGER = logging.getLogger(DOMAIN)

BASE_URL = "https://youraccountonline.electricireland.ie"


class ElectricIrelandScraper:
    def __init__(self, username, password, account_number):
        self.__scraper = None

        self.__username = username
        self.__password = password
        self.__account_number = account_number

    def refresh_credentials(self):
        LOGGER.info("Trying to refresh credentials...")
        session = requests.Session()

        meter_ids = self.__login_and_get_meter_ids(session)
        if not meter_ids:
            return

        self.__scraper = MeterInsightScraper(session, meter_ids)

    @property
    def scraper(self):
        if not self.__scraper:
            self.refresh_credentials()
        return self.__scraper

    def __login_and_get_meter_ids(self, session):
        # REQUEST 1: Get the Source token, and initialize the session
        LOGGER.debug("Getting Source Token...")
        res1 = session.get(f"{BASE_URL}/")
        try:
            res1.raise_for_status()
        except RequestException as err:
            LOGGER.error(f"Failed to Get Source Token: {err}")
            return None

        soup1 = BeautifulSoup(res1.text, "html.parser")
        source_input = soup1.find('input', attrs={'name': 'Source'})
        source = source_input.get('value') if source_input else None
        rvt = session.cookies.get_dict().get("rvt")

        if not source:
            LOGGER.error("Could not retrieve Source")
            return None
        if not rvt:
            LOGGER.error("Could not find rvt cookie")
            return None

        # REQUEST 2: Perform Login
        LOGGER.debug("Performing Login...")
        res2 = session.post(
            f"{BASE_URL}/",
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
        )
        try:
            res2.raise_for_status()
        except RequestException as err:
            LOGGER.error(f"Failed to Perform Login: {err}")
            return None

        soup2 = BeautifulSoup(res2.text, "html.parser")
        account_divs = soup2.find_all("div", {"class": "my-accounts__item"})
        target_account = None
        for account_div in account_divs:
            account_number_el = account_div.find("p", {"class": "account-number"})
            if not account_number_el:
                continue
            account_number = account_number_el.text
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

        # REQUEST 3: Navigate to Insights page to get meter IDs
        LOGGER.debug("Navigating to Insights page...")
        event_form = target_account.find("form", {"action": "/Accounts/OnEvent"})
        req3 = {"triggers_event": "AccountSelection.ToInsights"}
        for form_input in event_form.find_all("input"):
            req3[form_input.get("name")] = form_input.get("value")

        res3 = session.post(
            f"{BASE_URL}/Accounts/OnEvent",
            data=req3,
        )
        try:
            res3.raise_for_status()
        except RequestException as err:
            LOGGER.error(f"Failed to Navigate to Insights: {err}")
            return None

        # Extract meter IDs from #modelData div
        soup3 = BeautifulSoup(res3.text, "html.parser")
        model_data = soup3.find("div", {"id": "modelData"})

        if not model_data:
            LOGGER.error("Failed to find modelData div on Insights page")
            return None

        partner = model_data.get("data-partner")
        contract = model_data.get("data-contract")
        premise = model_data.get("data-premise")

        if not all([partner, contract, premise]):
            LOGGER.error(f"Missing meter IDs: partner={partner}, contract={contract}, premise={premise}")
            return None

        LOGGER.info(f"Found meter IDs: partner={partner}, contract={contract}, premise={premise}")
        return {"partner": partner, "contract": contract, "premise": premise}


class MeterInsightScraper:
    """Scraper for the new Electric Ireland MeterInsight API."""

    def __init__(self, session, meter_ids):
        self.__session = session
        self.__partner = meter_ids["partner"]
        self.__contract = meter_ids["contract"]
        self.__premise = meter_ids["premise"]

    def get_data(self, target_date, is_granular=False):
        """Fetch hourly usage data for a specific date.

        Args:
            target_date: The date to fetch data for
            is_granular: Ignored (kept for API compatibility)

        Returns:
            List of datapoints with 'consumption', 'cost', and 'intervalEnd' keys
        """
        date_str = target_date.strftime("%Y-%m-%d")
        LOGGER.debug(f"Getting hourly data for {date_str}...")

        url = f"{BASE_URL}/MeterInsight/{self.__partner}/{self.__contract}/{self.__premise}/hourly-usage"

        try:
            response = self.__session.get(url, params={"date": date_str})
            response.raise_for_status()
        except RequestException as err:
            LOGGER.error(f"Failed to get hourly usage data: {err}")
            return []

        # Check if we got JSON or an error page
        content_type = response.headers.get('content-type', '')
        if 'application/json' not in content_type:
            LOGGER.error(f"Expected JSON but got {content_type}. Response: {response.text[:500]}")
            return []

        try:
            data = response.json()
        except Exception as err:
            LOGGER.error(f"Failed to parse JSON: {err}. Response: {response.text[:500]}")
            return []

        if not data.get("isSuccess"):
            LOGGER.error(f"API returned error: {data.get('message')}")
            return []

        raw_datapoints = data.get("data", [])
        LOGGER.debug(f"Found {len(raw_datapoints)} hourly datapoints for {date_str}")

        # Transform to expected format with 'consumption', 'cost', 'intervalEnd'
        datapoints = []
        for dp in raw_datapoints:
            flat_rate = dp.get("flatRate") or {}
            end_date_str = dp.get("endDate")

            if not end_date_str:
                continue

            # Parse ISO date and convert to Unix timestamp
            # Format: "2025-12-01T00:59:59Z"
            try:
                end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                interval_end = int(end_dt.timestamp())
            except (ValueError, AttributeError) as err:
                LOGGER.warning(f"Failed to parse date {end_date_str}: {err}")
                continue

            datapoints.append({
                "consumption": flat_rate.get("consumption"),
                "cost": flat_rate.get("cost"),
                "intervalEnd": interval_end,
            })

        return datapoints
