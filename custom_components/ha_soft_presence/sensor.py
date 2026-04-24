"""Sensors — score, confidence, reason per room."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_ROOM_NAME
from .coordinator import SoftPresenceCoordinator, slugify


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SoftPresenceCoordinator = hass.data[DOMAIN][entry.entry_id]
    room_slug = slugify(entry.data.get(CONF_ROOM_NAME, "room"))
    async_add_entities([
        PresenceScoreSensor(coordinator, entry, room_slug),
        PresenceConfidenceSensor(coordinator, entry, room_slug),
        PresenceReasonSensor(coordinator, entry, room_slug),
    ])


class _BaseSensor(CoordinatorEntity[SoftPresenceCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SoftPresenceCoordinator,
        entry: ConfigEntry,
        room_slug: str,
        name: str,
        uid_suffix: str,
        entity_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{uid_suffix}"
        self.entity_id = f"sensor.{room_slug}_{entity_suffix}"

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": self._entry.data.get(CONF_ROOM_NAME, "Soft Presence Room"),
            "manufacturer": "HA Soft Presence",
            "model": "Virtual Presence Sensor",
            "entry_type": "service",
        }


class PresenceScoreSensor(_BaseSensor):
    """Score 0–100 representing how likely the room is occupied."""

    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:gauge"

    def __init__(self, coordinator, entry, room_slug):
        super().__init__(
            coordinator, entry, room_slug,
            "Presence Score", "presence_score", "presence_score"
        )

    @property
    def native_value(self) -> int:
        if not self.coordinator.data:
            return 0
        return self.coordinator.data.get("score", 0)

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        d = self.coordinator.data
        return {
            "state_machine": d.get("state_machine"),
            "active_sources": d.get("active_sources"),
            "timeout_remaining": d.get("timeout_remaining"),
        }


class PresenceConfidenceSensor(_BaseSensor):
    """Confidence level: high / medium / low."""

    _attr_icon = "mdi:signal"

    def __init__(self, coordinator, entry, room_slug):
        super().__init__(
            coordinator, entry, room_slug,
            "Presence Confidence", "presence_confidence", "presence_confidence"
        )

    @property
    def native_value(self) -> str:
        if not self.coordinator.data:
            return "low"
        return self.coordinator.data.get("confidence", "low")


class PresenceReasonSensor(_BaseSensor):
    """Human-readable explanation why the room is (or isn't) occupied."""

    _attr_icon = "mdi:text-box-outline"

    def __init__(self, coordinator, entry, room_slug):
        super().__init__(
            coordinator, entry, room_slug,
            "Presence Reason", "presence_reason", "presence_reason"
        )

    @property
    def native_value(self) -> str:
        if not self.coordinator.data:
            return "No active signals"
        return self.coordinator.data.get("reason", "No active signals")

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        d = self.coordinator.data
        return {
            "last_positive_signal": d.get("last_positive"),
            "active_sources": d.get("active_sources"),
        }
