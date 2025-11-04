# Home Assistant Electric Ireland Integration

> **Note:** This is a temporary fork of [RobinJ1995/home-assistant-esb-smart-meter-integration](https://github.com/RobinJ1995/home-assistant-esb-smart-meter-integration)

[![Open Integration](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=antoine-voiry&repository=Home-Assistant-Electric-Ireland&category=integration)

Home Assistant integration with **Electric Ireland insights**.

It is capable of:

* Reporting **consumed energy** in kWh.
* Reporting **usage cost** in EUR (see the FAQ below for more details on this).

It will also aggregate the report data into statistical buckets, so they can be fed into the Energy Dashboard.

![](https://i.imgur.com/6ew3JIf.png)

## FAQs

### How does it work?

It basically scrapes the Insights page that Electric Ireland provides. It will first mimic a user login interaction,
and then will navigate to the page to fetch the data.

As this data is also feed from ESB ([Electrical Supply Board](https://esb.ie)), it is not in real time. They publish
data with 1-3 days delay; this integration takes care of that and will fetch every hour and ingest data dated back up
to 10 days. This job runs every hour, so whenever it gets published it should get feed into Home Assistant within 60
minutes.

### Why not fetching from ESB directly?

I have Electric Ireland, and ESB has a captcha in their login. I just didn't want to bother to investigate how to
bypass it.

### Why not applying the 30% Off DD discount?

This is tariff-dependant. The Electric Ireland API reports cost as per tariff price (24h, smart, etc.), so in case some
tariff does not offer the 30% Off Direct Debit, this integration will apply a transformation incorrect for the user.

So, in summary: Cost reports gross usage cost with VAT, without discount but also without standing charge or levy.

### Why does the individual reporte device sometimes exceed the reported usage in Electric Ireland?

I don't have a clear answer to this. I have noticed this in some buckets, but there it is an issue in how the metrics
are reported into buckets. It is an issue either in ESB / Electric Ireland reporting, that they report the intervals
incorrectly; or it is the device meters that they may do the same.

In either case, I would not expect the total amount to differ: it is just a matter of consumption/cost being reported
into the wrong hour. If you take the previous and after, the total should be the same.

## Technical Details

### Sensors

* **Electric Ireland Consumption**: reports consumed data in kWh, in 30 minute intervals.
* **Electric Ireland Cost**: reports the total cost charged in 60 minute intervals (without discounts and without
  standing charge, just the gross "usage" as per the contracted tariff).

### Data Retrieval Flow

1. Open a `requests` session against Electric Ireland website, and:
    1. Create a GET request to retrieve the cookies and the state.
    2. Do a POST request to login into Electric Ireland.
    3. Scrape the dashboard to try to find the `div` with the target Account Number.
    4. Navigate to the Insights page for that Account Number.
2. Now, once we have that Insights page, we don't need the ELectric Ireland session anymore:
    1. The page contains a payload to call Bidgely API (data API provider for Electric Ireland).
    2. Authenticate using that payload against Bidgely API (no need for session or cookies).
    3. Send requests to the API to fetch the data for required intervals.
    4. Profit! 🎉

### Schedule

Every hour:

* Performs once the flow mentioned above to get the API credentials.
* Launches requests for the 11th to 1st days before "now": if today is 20th January, then it will retrieve data
  for all days between the 9th and 19th.
* For Cost, it will receive 24 datapoints within the date.
* For Consumption, it will receive 48 datapoints within the date.
* It will ingest the data taking the last minute of the interval: if querying for 00:00 to 00:30, it will ingest it
  effective at 00:29.

## Acknowledgements

* [Historical sensors for Home Assistant](https://github.com/ldotlopez/ha-historical-sensor): provided the library and 
  skeleton to create the bare minimum working version.
