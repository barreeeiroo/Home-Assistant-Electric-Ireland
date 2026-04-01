"""Constants for Electric Ireland Insights."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "electric_ireland_insights"
NAME = "Electric Ireland Insights (Unofficial)"

LOOKUP_DAYS = 4
INITIAL_LOOKBACK_DAYS = 30
SCAN_INTERVAL = timedelta(hours=3)
DATA_GAP_THRESHOLD_DAYS = 5

# Maps API tariff bucket keys to stable snake_case identifiers used in
# statistic IDs (e.g. ``electric_ireland_insights:{acct}_consumption_off_peak``).
TARIFF_BUCKET_MAP: dict[str, str] = {
    "flatRate": "flat_rate",
    "offPeak": "off_peak",
    "midPeak": "mid_peak",
    "onPeak": "on_peak",
}
