import logging
from datetime import timedelta

import requests
from bs4 import BeautifulSoup
from requests import RequestException

from .const import DOMAIN
from .utils import date_to_unix


LOGGER = logging.getLogger(DOMAIN)


class ElectricIrelandScraper:
    def __init__(self, username, password, account_number):
        self.__bidgely = None

        self.__username = username
        self.__password = password
        self.__account_number = account_number

    def refresh_credentials(self):
        LOGGER.info("Trying to refresh credentials...")
        session = requests.Session()

        bidgely_token = self.__get_bidgely_token(session)
        if not bidgely_token:
            return

        self.__bidgely = BidgelyScraper(session, bidgely_token)

    @property
    def scraper(self):
        if not self.__bidgely:
            self.refresh_credentials()
        return self.__bidgely

    def __get_bidgely_token(self, session):
        # REQUEST 1: Get the Source token, and initialize the session
        LOGGER.debug("Getting Source Token...")
        res1 = session.get("https://youraccountonline.electricireland.ie/")
        try:
            res1.raise_for_status()
        except RequestException as err:
            LOGGER.error(f"Failed to Get Source Token: {err}")
            return None

        soup1 = BeautifulSoup(res1.text, "html.parser")
        source = soup1.find('input', attrs={'name': 'Source'}).get('value')
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
            account_number = account_div.find("p", {"class": "account-number"}).text
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
        req3 = {"triggers_event": "AccountSelection.ToInsights"}
        for form_input in event_form.find_all("input"):
            req3[form_input.get("name")] = form_input.get("value")

        res3 = session.post(
            "https://youraccountonline.electricireland.ie/Accounts/OnEvent",
            data=req3,
        )
        try:
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
    def __init__(self, session, bidgely_payload):
        self.__session = session
        self.__access_token, self.__user_id = self.__get_auth(bidgely_payload)

    def __get_auth(self, bidgely_payload):
        if not bidgely_payload:
            return

        # REQUEST 4: Get Bidgely Auth Details
        LOGGER.debug("Getting Auth Details...")
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
            }
        )
        try:
            res4.raise_for_status()
        except RequestException as err:
            LOGGER.error(f"Failed to Get Auth Details: {err}")
            return None

        res4_json = res4.json()

        access_token = res4_json.get("tokenDetails", {}).get("accessToken")
        user_id = res4_json.get("userProfileDetails", {}).get("userId")

        return access_token, user_id

    def get_data(self, target_date, is_granular=False):
        if not self.__user_id:
            return None

        # REQUEST 5: Get Data
        LOGGER.debug(f"Getting Data for {target_date}...")
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
        )
        try:
            res5.raise_for_status()
        except RequestException as err:
            LOGGER.error(f"Failed to Get Data: {err}")
            return None

        data = res5.json()
        datapoints = data.get("payload", {}).get("usageChartDataList", [])
        LOGGER.debug(f"Found {len(datapoints)} for {target_date}")

        return datapoints
