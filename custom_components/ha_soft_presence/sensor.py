"""Sensors — score, confidence, reason per room."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_ROOM_NAME, CONF_LLM_ENABLED, CONF_CONVERSATION_AGENT
from .coordinator import SoftPresenceCoordinator, slugify


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SoftPresenceCoordinator = hass.data[DOMAIN][entry.entry_id]
    room_slug = slugify(entry.data.get(CONF_ROOM_NAME, "room"))

    entities = [
        PresenceScoreSensor(coordinator, entry, room_slug),
        PresenceConfidenceSensor(coordinator, entry, room_slug),
        PresenceReasonSensor(coordinator, entry, room_slug),
    ]

    if entry.data.get(CONF_LLM_ENABLED) and entry.data.get(CONF_CONVERSATION_AGENT):
        entities += [
            LLMScoreSensor(coordinator, entry, room_slug),
            LLMConfidenceSensor(coordinator, entry, room_slug),
            LLMReasonSensor(coordinator, entry, room_slug),
        ]

    async_add_entities(entities)


class _BaseSensor(CoordinatorEntity[SoftPresenceCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SoftPresenceCoordinator,
        entry: ConfigEntry,
        room_slug: str,
        uid_suffix: str,
        entity_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{uid_suffix}"
        self._attr_translation_key = uid_suffix
        self.entity_id = f"sensor.{room_slug}_{entity_suffix}"

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": f"{self._entry.data.get(CONF_ROOM_NAME, 'Room')} Soft Presence",
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
            "presence_score", "presence_score"
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
            "presence_confidence", "presence_confidence"
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
            "presence_reason", "presence_reason"
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


# ------------------------------------------------------------------
# LLM advisory sensors
# ------------------------------------------------------------------

class LLMScoreSensor(_BaseSensor):
    """LLM estimated presence score 0–100."""

    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:brain"

    def __init__(self, coordinator, entry, room_slug):
        super().__init__(
            coordinator, entry, room_slug,
            "presence_llm_score", "presence_llm_score"
        )

    @property
    def native_value(self) -> int:
        llm = self.coordinator.data.get("llm", {}) if self.coordinator.data else {}
        return llm.get("score", 0)

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        llm = self.coordinator.data.get("llm", {})
        return {"last_updated": llm.get("last_updated")}


class LLMConfidenceSensor(_BaseSensor):
    """LLM confidence: high / medium / low."""

    _attr_icon = "mdi:brain"

    def __init__(self, coordinator, entry, room_slug):
        super().__init__(
            coordinator, entry, room_slug,
            "presence_llm_confidence", "presence_llm_confidence"
        )

    @property
    def native_value(self) -> str:
        llm = self.coordinator.data.get("llm", {}) if self.coordinator.data else {}
        return llm.get("confidence") or "pending"


class LLMReasonSensor(_BaseSensor):
    """LLM explanation for its presence decision."""

    _attr_icon = "mdi:comment-text-outline"

    def __init__(self, coordinator, entry, room_slug):
        super().__init__(
            coordinator, entry, room_slug,
            "presence_llm_reason", "presence_llm_reason"
        )

    @property
    def native_value(self) -> str:
        llm = self.coordinator.data.get("llm", {}) if self.coordinator.data else {}
        return llm.get("reason") or "pending"

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        llm = self.coordinator.data.get("llm", {})
        return {
            "last_updated": llm.get("last_updated"),
            "rule_score": self.coordinator.data.get("score"),
            "rule_state": self.coordinator.data.get("state_machine"),
        }
