---
title: Electric Ireland Insights (Unofficial)
description: Instructions on how to integrate Electric Ireland energy data into Home Assistant.
ha_category:
  - Energy
ha_release: "2024.1"
ha_iot_class: Cloud Polling
ha_config_flow: true
ha_codeowners:
  - "@barreeeiroo"
ha_domain: electric_ireland_insights
ha_platforms:
  - diagnostics
  - sensor
ha_integration_type: service
ha_quality_scale: platinum
---

# Electric Ireland Insights (Unofficial)

[Electric Ireland](https://www.electricireland.ie/) is an Irish electricity and gas supplier. The Electric Ireland Insights integration imports hourly energy consumption and cost data from the Electric Ireland Insights portal directly into the Home Assistant Energy Dashboard as external statistics.

> **Note**: This is an independent, community-built integration. It is not affiliated with, authorized by, or endorsed by Electric Ireland, ESB Group, or any of their subsidiaries. This integration works by scraping the Electric Ireland web portal — there is no official API. Changes to the website may break this integration at any time without notice. Users are solely responsible for ensuring their use complies with Electric Ireland's terms of service and applicable laws. The authors accept no responsibility for any consequences arising from its use, including account restrictions or legal action. All data remains on the user's local Home Assistant instance. See [LEGAL.md](https://github.com/barreeeiroo/Home-Assistant-Electric-Ireland/blob/master/LEGAL.md) for full details.

## Prerequisites

- **Home Assistant 2025.4.0** or newer
- An active Electric Ireland account with **Insights access** enabled
- An **electricity** account (gas-only accounts are not supported)
- A **smart meter** installed at your premises (required for hourly data)

## Installation

1. Install via [HACS](https://hacs.xyz/) (search for "Electric Ireland Insights") or manually copy the `electric_ireland_insights` folder into `<config>/custom_components/` (the final path should be `<config>/custom_components/electric_ireland_insights/`).
2. Restart Home Assistant.
3. Go to **Settings** → **Devices & services**.
4. Click **+ Add integration**.
5. Search for and select **Electric Ireland Insights**.
6. Follow the on-screen instructions to complete the setup.

During setup you will be asked for:

| Parameter | Description |
|-----------|-------------|
| **Username** | Your Electric Ireland portal email address |
| **Password** | Your Electric Ireland portal password |

After authenticating, the integration discovers all electricity accounts linked to your login. If only one account is found, it is selected automatically. If multiple accounts are found, a dropdown is shown for you to select which account to configure. Each config entry supports one account — add the integration again for additional accounts.

A final **Import Options** step is shown before setup completes:

| Option | Default | Description |
|--------|---------|-------------|
| **Import full history** | Checked | Fetch all available historical data from your bill periods (typically 6–13 months) as a background task. Uncheck if you only want the last 30 days. This can also be triggered later via Reconfigure. |

### Adding to the Energy Dashboard

After setup, add the imported statistics to the Energy Dashboard:

1. Go to **Settings → Dashboards → Energy**.
2. Under **Grid consumption**, click **Add consumption**.
3. Search for and select `Electric Ireland Consumption ({account})`.
4. For **Use an entity tracking the total costs**, select `Electric Ireland Cost ({account})`.

For per-tariff breakdown (stacked colored bars by time-of-use), see the [per-tariff setup](#setting-up-the-energy-dashboard-with-per-tariff-breakdown) section below.

## Removal

1. Go to **Settings** → **Devices & services**.
2. Select the **Electric Ireland Insights** integration card.
3. Click the three-dot menu (**⋮**) and select **Delete**.

Imported statistics remain in the Home Assistant recorder after removal. To also delete historical energy data, use **Developer tools → Statistics** and search for `electric_ireland_insights` to remove individual statistics.

## Data updates

The integration fetches data from the Electric Ireland portal **every 3 hours**.

- **First install**: the initial setup fetches up to **30 days** of data (this may take a few minutes as each day requires a separate request to the Electric Ireland portal).
- **Full history (opt-in)**: to import all available historical data (typically 6–13 months), go to **Reconfigure** and check **Import full history**. This runs as a background task without blocking Home Assistant, typically taking 10–30 minutes.
- **Subsequent runs**: fetches up to the last **4 days**, limited to dates within known billing periods, to pick up newly published readings. Dates outside any billing period are skipped.
- **Pre-flight optimization**: the integration periodically queries billing period boundaries (cached for 24 hours) to identify which dates contain meter data, reducing unnecessary API calls. If the query fails entirely (no cached data available), the integration falls back to the full lookback window.
- **Provider delay**: Electric Ireland publishes meter data with a **1–3 day delay** (data comes from ESB). The Data Freshness diagnostic sensor shows how old the latest available reading is (see [Diagnostic entities](#diagnostic-entities)).
- **Data gap detection**: if no new data arrives for more than **5 days**, the integration creates a **repair issue** in Home Assistant (visible in **Settings → Repairs**). The issue is automatically removed when data resumes.

## Statistics

The integration imports data as **external statistics** directly into the HA recorder — no sensor entities are needed for the Energy Dashboard.

### Grid consumption and cost (hourly resolution)

| Statistic ID | Description | Unit |
|---|---|---|
| `electric_ireland_insights:{account}_consumption` | Hourly electricity consumption (total) | kWh |
| `electric_ireland_insights:{account}_cost` | Hourly electricity cost (total, gross with VAT, no discounts or standing charge) | EUR |

### Per-tariff breakdown

For smart meter accounts on a time-of-use tariff, the integration automatically detects which tariff buckets are active and imports separate statistics for each:

| Statistic ID | Description | Unit |
|---|---|---|
| `electric_ireland_insights:{account}_consumption_off_peak` | Off-peak consumption | kWh |
| `electric_ireland_insights:{account}_consumption_mid_peak` | Mid-peak consumption | kWh |
| `electric_ireland_insights:{account}_consumption_on_peak` | On-peak consumption | kWh |
| `electric_ireland_insights:{account}_cost_off_peak` | Off-peak cost | EUR |
| `electric_ireland_insights:{account}_cost_mid_peak` | Mid-peak cost | EUR |
| `electric_ireland_insights:{account}_cost_on_peak` | On-peak cost | EUR |

- If you're on a **flat-rate** tariff (single bucket), per-tariff statistics are not created (they would be identical to the totals).
- If only one non-flat bucket appears (e.g., off-peak only), per-tariff statistics are still created.
- Historical accounts that switched from flat-rate to smart meter will also show a `_flat_rate` statistic for the period before the switch.
- Per-tariff statistics may not appear immediately after setup — they are populated during the background backfill and on subsequent hourly updates.

### Setting up the Energy Dashboard with per-tariff breakdown

To see stacked colored bars showing consumption broken down by tariff:

1. Go to **Settings → Dashboards → Energy**.
2. Under **Grid consumption**, click **Add consumption**.
3. Search for and add each per-tariff consumption statistic that the integration created for your account. The available tariff buckets depend on your plan and may include off-peak, mid-peak, on-peak, or flat-rate.
4. For each consumption statistic, select the matching cost statistic (e.g., `Electric Ireland Cost Off-Peak ({account})` for the off-peak consumption entry).
5. **Remove** the original aggregate `Electric Ireland Consumption ({account})` entry to avoid double-counting.

The Energy Dashboard will now display separate colored bars per hour/day for each tariff bucket.

> **Note**: Do not add both aggregate and per-tariff statistics to the Energy Dashboard grid consumption at the same time — this will result in double-counted consumption. The aggregate statistics remain available in the recorder for historical queries but are not usable as entity states in automations.

## Diagnostic entities

Two diagnostic sensor entities are created under the integration's device. Entity IDs include the account number (e.g., `sensor.electric_ireland_100000001_timestamp`). In multi-account setups, each account has its own set of diagnostic sensors.

| Entity | Description |
|--------|-------------|
| **Last Import Time** | Timestamp of the last successful data import |
| **Data Freshness** | How many days since the latest available reading (as a decimal, e.g., 1.3 days) |

These entities are **disabled by default**. Enable them in **Settings → Devices & services → Electric Ireland Insights → device → entities**.

## Reconfiguration

To update your password or troubleshoot data import issues, use **Settings → Devices & services → Electric Ireland Insights → ⋮ → Reconfigure**.

| Option | Description |
|--------|-------------|
| **Password** | Re-enter your current password (required to re-authenticate the session, even if unchanged) |
| **Re-discover meter IDs** | Clears the cached meter identifiers (partner, contract, premise) and forces the integration to re-discover them from the Electric Ireland portal on the next refresh. Use this when data imports have stopped but your credentials are still valid — typically caused by Electric Ireland changing internal account identifiers after a meter swap or account migration. |
| **Import full history** | Fetches all available historical data from your bill periods (typically 6–13 months). Runs as a background task without blocking Home Assistant. Only needed once — subsequent polls keep data current automatically. |

If the password has changed, cached meter IDs are cleared automatically — you don't need to check the re-discovery option.

## Events

The integration fires an event after each successful data import:

| Event | Description |
|-------|-------------|
| `electric_ireland_insights_data_imported` | Fired when new data is imported into the recorder |

**Payload fields:**

| Field | Type | Description |
|-------|------|-------------|
| `account` | string | Account number |
| `datapoint_count` | integer | Number of hourly datapoints fetched in this update (includes re-fetched overlap days, not just new data) |
| `latest_data_timestamp` | string or null | ISO 8601 timestamp of the newest datapoint, or null if no data was available |
| `tariff_buckets` | list of strings | Sorted list of tariff bucket names seen (e.g., `["mid_peak", "off_peak", "on_peak"]`) |

### Automation: notify when new data arrives

```yaml
automation:
  - alias: "Electric Ireland: new data imported"
    triggers:
      - trigger: event
        event_type: electric_ireland_insights_data_imported
    actions:
      - action: notify.mobile_app
        data:
          message: >
            Electric Ireland imported {{ trigger.event.data.datapoint_count }} datapoints.
            Tariffs: {{ trigger.event.data.tariff_buckets | join(', ') }}
```

### Automation: alert when data is stale

> **Note**: The Data Freshness sensor is disabled by default. Enable it first in **Settings → Devices & services → Electric Ireland Insights → device → entities**.

Replace `ACCOUNT` below with your account number (e.g., `100000001`):

```yaml
automation:
  - alias: "Alert: Electric Ireland data stale"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.electric_ireland_ACCOUNT
        above: 5
    actions:
      - action: notify.mobile_app
        data:
          message: "Electric Ireland data is {{ states('sensor.electric_ireland_ACCOUNT') }} days old."
```

## Known limitations

- **1–3 day data delay**: Hourly readings are published by ESB with a delay; the integration cannot fetch data faster than ESB publishes it.
- **Cost excludes discounts and standing charges**: The reported cost is the gross tariff cost with VAT. It does not include the 30% Off Direct Debit discount, standing charges, or levies.
- **Scraping dependency**: The integration authenticates via the Electric Ireland web portal. Changes to the portal's HTML structure may break the login flow until the integration is updated.
- **Single account per entry**: Each config entry supports one electricity account. To monitor multiple accounts, add the integration once per account.

## Troubleshooting

### Login failure / Invalid credentials

Verify your username (email address) and password by logging in at [youraccountonline.electricireland.ie](https://youraccountonline.electricireland.ie). If your password has changed, use **Reconfigure** to update it.

### Account not found

The integration automatically discovers electricity accounts linked to your login. If no accounts are found, ensure your login has an **electricity** account with Insights access enabled (gas-only accounts are not supported). You can verify by logging in at [youraccountonline.electricireland.ie](https://youraccountonline.electricireland.ie) and checking the Insights section.

### No data / Data freshness increasing

Electric Ireland publishes data with a 1–3 day delay. If no new data arrives for more than 5 days, the integration automatically creates a **repair issue** visible in **Settings → Repairs**.

To investigate further:

1. Check that your smart meter is functioning correctly.
2. Verify the Electric Ireland Insights portal shows data at [youraccountonline.electricireland.ie](https://youraccountonline.electricireland.ie).
3. Check the integration logs for errors (**Settings → System → Logs**, filter by `electric_ireland_insights`).

The Data Freshness diagnostic sensor can also help monitor this, but it must be **enabled** first (it is disabled by default).

### Re-authentication required

If the integration enters a re-authentication state, go to **Settings → Devices & services → Electric Ireland Insights** and follow the re-authentication flow to update your credentials.

### Debug logging

To help diagnose issues, enable debug logging for the integration:

1. Go to **Settings → Devices & services → Electric Ireland Insights → ⋮ → Enable debug logging**.
2. Reproduce the issue.
3. Go back and select **Disable debug logging** to download the log file.

Alternatively, add the following to your `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.electric_ireland_insights: debug
```
