"""Type definitions for Electric Ireland Insights."""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict


class ElectricIrelandDatapoint(TypedDict):
    """A single hourly datapoint from the Electric Ireland API."""

    consumption: float
    cost: float
    intervalEnd: int
    tariff_bucket: str


class CoordinatorData(TypedDict):
    """Data returned by the coordinator update."""

    last_import: datetime | None
    datapoint_count: int
    latest_data_timestamp: datetime | None
    import_error: str | None
    appliance_count: int
    bill_periods_available: int
    tariff_buckets_seen: int


class MeterIds(TypedDict):
    """Meter identification data."""

    partner: str
    contract: str
    premise: str


class BillPeriod(TypedDict):
    startDate: str
    endDate: str
    current: bool
    hasAppliance: bool


class BillPeriodResponse(TypedDict):
    subStatusCode: str
    isSuccess: bool
    message: str
    data: list[BillPeriod]
