"""Diagnostic sensor entities for Electric Ireland Insights."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.dt import utcnow

from . import ElectricIrelandConfigEntry
from .const import DOMAIN
from .coordinator import ElectricIrelandCoordinator
from .types import CoordinatorData

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ElectricIrelandSensorDescription(SensorEntityDescription):  # type: ignore[misc]
    value_fn: Callable[[CoordinatorData], datetime | float | int | None]


DIAGNOSTIC_SENSORS: tuple[ElectricIrelandSensorDescription, ...] = (
    ElectricIrelandSensorDescription(
        key="last_import_time",
        translation_key="last_import_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("last_import"),
    ),
    ElectricIrelandSensorDescription(
        key="data_freshness_days",
        translation_key="data_freshness_days",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="days",
        value_fn=lambda data: _calc_freshness(data),
    ),
)


def _calc_freshness(data: CoordinatorData) -> float | None:
    latest = data.get("latest_data_timestamp")
    if latest is None:
        return None

    delta = utcnow() - latest
    return max(0.0, round(delta.total_seconds() / 86400, 1))


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ElectricIrelandConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = config_entry.runtime_data
    account = config_entry.data["account_number"]
    async_add_entities(
        ElectricIrelandDiagnosticSensor(coordinator, description, account) for description in DIAGNOSTIC_SENSORS
    )


class ElectricIrelandDiagnosticSensor(CoordinatorEntity[ElectricIrelandCoordinator], SensorEntity):  # type: ignore[misc]
    entity_description: ElectricIrelandSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ElectricIrelandCoordinator,
        description: ElectricIrelandSensorDescription,
        account_number: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{account_number}_{description.key}"
        self._attr_entity_registry_enabled_default = False
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, account_number)},
            name=f"Electric Ireland Insights ({account_number})",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> datetime | float | int | None:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
