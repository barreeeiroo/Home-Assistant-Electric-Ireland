# Home Assistant Electric Ireland Integration

[![Open Integration](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=barreeeiroo&repository=Home-Assistant-Electric-Ireland&category=integration)

Home Assistant integration with **Electric Ireland insights**.

It is capable of:

* Reporting **consumed energy** in kWh.
* Reporting **cost** in EUR (note this does not take into account discounts like _30% Off with Direct Debit_).

## How does it work?

It basically scrapes the Insights page that Electric Ireland provides. It will first mimic a user login interaction,
and then will navigate to the page to fetch the data.

As this data is also feed from ESB ([Electrical Supply Board](https://esb.ie)), it is not in real time. They publish
data with 1-3 days delay; this integration takes care of that and will fetch every hour and ingest data dated back up
to 10 days.

## Why not fetching from ESB directly?

I have Electric Ireland, and ESB has a captcha in their login. I just didn't want to bother to investigate how to
bypass it.

## Acknowledgements

* [Historical sensors for Home Assistant](https://github.com/ldotlopez/ha-historical-sensor): provided the library and 
  skeleton to create the bare minimum working version.
