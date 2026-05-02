from __future__ import annotations

import re
from typing import Any

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_NINE_DIGIT_RE = re.compile(r"\b\d{9}\b")

_ALLOWED_EMAIL = "test@example.com"
_ALLOWED_ACCOUNT = "100000001"
_TARIFF_KEYS = ("flatRate", "offPeak", "midPeak", "onPeak")


def validate_hourly_response(data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise ValueError("hourly response must be an object")
    if "isSuccess" not in data or not isinstance(data["isSuccess"], bool):
        raise ValueError("hourly response must include boolean isSuccess")
    if "data" not in data or not isinstance(data["data"], list):
        raise ValueError("hourly response must include data list")

    for index, entry in enumerate(data["data"]):
        if not isinstance(entry, dict):
            raise ValueError(f"hourly entry {index} must be an object")
        if "endDate" not in entry or not isinstance(entry["endDate"], str):
            raise ValueError(f"hourly entry {index} must include string endDate")

        active_tariffs = [key for key in _TARIFF_KEYS if key in entry]
        if not active_tariffs:
            raise ValueError(f"hourly entry {index} must include at least one tariff key")
        if not any(entry.get(key) is not None for key in _TARIFF_KEYS):
            raise ValueError(f"hourly entry {index} must include one populated tariff bucket")

        for key in _TARIFF_KEYS:
            bucket = entry.get(key)
            if bucket is None:
                continue
            if not isinstance(bucket, dict):
                raise ValueError(f"hourly entry {index} tariff {key} must be an object")
            if "consumption" not in bucket or "cost" not in bucket:
                raise ValueError(f"hourly entry {index} tariff {key} must include consumption and cost")


def validate_bill_period_response(data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise ValueError("bill period response must be an object")
    if "isSuccess" not in data or not isinstance(data["isSuccess"], bool):
        raise ValueError("bill period response must include boolean isSuccess")
    if "data" not in data or not isinstance(data["data"], list):
        raise ValueError("bill period response must include data list")

    for index, period in enumerate(data["data"]):
        if not isinstance(period, dict):
            raise ValueError(f"bill period {index} must be an object")
        if "startDate" not in period or not isinstance(period["startDate"], str):
            raise ValueError(f"bill period {index} must include string startDate")
        if "endDate" not in period or not isinstance(period["endDate"], str):
            raise ValueError(f"bill period {index} must include string endDate")


def validate_no_pii(text: str) -> None:
    for match in _EMAIL_RE.findall(text):
        if match.lower() != _ALLOWED_EMAIL:
            raise ValueError(f"PII detected: email address {match!r}")

    for match in _NINE_DIGIT_RE.findall(text):
        if match != _ALLOWED_ACCOUNT:
            raise ValueError(f"PII detected: 9-digit account number {match!r}")
