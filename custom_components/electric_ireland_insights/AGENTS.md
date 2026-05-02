# INTEGRATION MODULE: electric_ireland_insights

## OVERVIEW

14-file HA custom integration that scrapes Electric Ireland for hourly energy data and imports it as external statistics. No sensor entities for core data — only diagnostic sensors for health monitoring.

## STRUCTURE

```
electric_ireland_insights/
├── __init__.py         # Entry point: setup, unload, migration (v1→v2)
├── api.py              # Scraping client: login, account discovery, MeterInsight API
├── coordinator.py      # DataUpdateCoordinator: fetch + external statistics import
├── config_flow.py      # Config flow: user, account select, reauth, reconfigure
├── sensor.py           # Diagnostic sensors only (last_import_time, data_freshness)
├── types.py            # TypedDicts: ElectricIrelandDatapoint, CoordinatorData, MeterIds
├── exceptions.py       # InvalidAuth, CannotConnect, AccountNotFound, CachedIdsInvalid
├── diagnostics.py      # async_get_config_entry_diagnostics with redaction
├── const.py            # DOMAIN, NAME, SCAN_INTERVAL, LOOKBACK constants
├── manifest.json       # Integration metadata, deps: [recorder], req: [beautifulsoup4]
├── strings.json        # Translations source: config flow steps/errors, entity names
├── translations/
│   └── en.json         # Runtime translations (must mirror strings.json for HACS)
├── icons.json          # Entity icons: mdi:clock-check-outline, mdi:calendar-clock
└── quality_scale.yaml  # IQS self-assessment: 52/52 rules addressed
```

## FILE-BY-FILE GUIDE

| File | Key Symbols | Responsibility |
|------|-------------|---------------|
| `__init__.py` | `async_setup_entry`, `async_unload_entry`, `async_migrate_entry`, `ElectricIrelandConfigEntry` | Creates coordinator, assigns `entry.runtime_data`, forwards sensor platform. Migration adds meter ID caching fields. |
| `api.py` | `ElectricIrelandAPI`, `MeterInsightClient` | Session-based scraping: GET login page → extract CSRF → POST credentials → scrape account div → navigate Insights → call MeterInsight/hourly-usage. Sequential day-by-day. |
| `coordinator.py` | `ElectricIrelandCoordinator`, `_async_update_data`, `_insert_statistics` | 3-hour polling. First run: 30-day backfill. Subsequent: 4-day lookback. Imports consumption + cost (aggregate + per-tariff) via `async_add_external_statistics`. Handles cumulative sum continuity with overlap detection. Fires `electric_ireland_insights_data_imported` event. Creates repair issue if data stale >5 days. |
| `config_flow.py` | `ElectricIrelandInsightsConfigFlow` | Steps: `user` (credentials) → `account` (dropdown if multiple, auto-selected if one) → `options` (import full history toggle) → create entry. `reauth_confirm` for expired passwords. `reconfigure` for password change + meter ID rediscovery + full history import. |
| `sensor.py` | `ElectricIrelandDiagnosticSensor`, `DIAGNOSTIC_SENSORS`, `PARALLEL_UPDATES = 0` | One `CoordinatorEntity` subclass instantiated per diagnostic description: last import timestamp + data freshness days. Disabled by default. EntityCategory.DIAGNOSTIC. |
| `types.py` | `ElectricIrelandDatapoint`, `CoordinatorData`, `MeterIds` | TypedDicts for type safety. Omitted from coverage (TypedDict-only). |
| `exceptions.py` | `InvalidAuth`, `CannotConnect`, `AccountNotFound`, `CachedIdsInvalid` | Auth errors → reauth flow. Connect errors → retry. CachedIdsInvalid → full login fallback (not auth failure). |
| `diagnostics.py` | `async_get_config_entry_diagnostics` | Redacts: username, password, account_number, partner_id, contract_id, premise_id. Exposes coordinator data for debugging. |

## DATA FLOW

```
Electric Ireland Website
    ↓ (aiohttp session with cookie jar)
ElectricIrelandAPI.fetch_day_range()
    ↓ (list[ElectricIrelandDatapoint])
ElectricIrelandCoordinator._async_update_data()
    ↓ (StatisticData with cumulative sums)
async_add_external_statistics(hass, metadata, stats)
    ↓
HA Recorder → Energy Dashboard
```

## CONVENTIONS (THIS MODULE)

- **Config entry version**: 2 (v1→v2 migration adds meter ID fields for caching).
- **Typed config entry**: `type ElectricIrelandConfigEntry = ConfigEntry[ElectricIrelandCoordinator]` used throughout.
- **Unique ID**: `account_number` (set in config flow, prevents duplicates).
- **Statistic IDs**: `electric_ireland_insights:{account_number}_consumption`, `electric_ireland_insights:{account_number}_cost` (aggregate); plus per-tariff variants like `_consumption_off_peak`, `_cost_mid_peak` etc. for time-of-use accounts.
- **Tariff bucket selection**: Active bucket (flatRate, offPeak, midPeak, onPeak) extracted per hour — only one is active at a time.
- **State logging**: Coordinator logs state transitions (unavailable ↔ available) once per transition, not every poll.

## ANTI-PATTERNS (THIS MODULE)

- **NEVER** create sensor entities for consumption/cost — external statistics only.
- **NEVER** fire concurrent API requests — Electric Ireland rate-limits aggressively.
- **NEVER** store runtime data in `hass.data[DOMAIN]` — use `entry.runtime_data`.
- **NEVER** use `requests` or any sync HTTP library — async only via `async_create_clientsession`.
- **NEVER** hardcode meter IDs — discover from website, cache in config entry.
