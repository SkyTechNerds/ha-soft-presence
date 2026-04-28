"""Binary sensors — rule-based and LLM-based occupancy."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    entities = [SoftPresenceBinarySensor(coordinator, entry)]
    if entry.data.get(CONF_LLM_ENABLED) and entry.data.get(CONF_CONVERSATION_AGENT):
        entities.append(LLMPresenceBinarySensor(coordinator, entry))
    async_add_entities(entities)


class SoftPresenceBinarySensor(CoordinatorEntity[SoftPresenceCoordinator], BinarySensorEntity):
    """Binary sensor: is the room occupied?"""

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_has_entity_name = True
    _attr_translation_key = "presence_soft"

    def __init__(self, coordinator: SoftPresenceCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        room_slug = slugify(entry.data.get(CONF_ROOM_NAME, "room"))
        self._attr_unique_id = f"{entry.entry_id}_presence_soft"
        self.entity_id = f"binary_sensor.{room_slug}_presence_soft"

    @property
    def is_on(self) -> bool:
        if not self.coordinator.data:
            return False
        return self.coordinator.data.get("occupied", False)

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        d = self.coordinator.data
        return {
            "presence_score": d.get("score"),
            "confidence": d.get("confidence"),
            "reason": d.get("reason"),
            "active_sources": d.get("active_sources"),
            "state_machine": d.get("state_machine"),
            "last_positive_signal": d.get("last_positive"),
            "last_positive_reason": d.get("last_positive_reason"),
            "last_positive_sources": d.get("last_positive_sources"),
            "timeout_remaining": d.get("timeout_remaining"),
            "room_name": d.get("room_name"),
            "manual_override": d.get("manual_override"),
            "sensors": d.get("sensors", {}),
        }

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": f"{self._entry.data.get(CONF_ROOM_NAME, 'Room')} Soft Presence",
            "manufacturer": "HA Soft Presence",
            "model": "Virtual Presence Sensor",
            "entry_type": "service",
        }


class LLMPresenceBinarySensor(CoordinatorEntity[SoftPresenceCoordinator], BinarySensorEntity):
    """LLM advisory binary sensor — AI occupancy estimate."""

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_has_entity_name = True

    def __init__(self, coordinator: SoftPresenceCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        room_slug = slugify(entry.data.get(CONF_ROOM_NAME, "room"))

        self._attr_unique_id = f"{entry.entry_id}_presence_llm"
        self._attr_translation_key = "presence_llm"
        self.entity_id = f"binary_sensor.{room_slug}_presence_llm"

    @property
    def is_on(self) -> bool:
        llm = self.coordinator.data.get("llm", {}) if self.coordinator.data else {}
        return bool(llm.get("occupied", False))

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        llm = self.coordinator.data.get("llm", {})
        return {
            "llm_score": llm.get("score"),
            "llm_confidence": llm.get("confidence"),
            "llm_reason": llm.get("reason"),
            "llm_last_updated": llm.get("last_updated"),
            "rule_score": self.coordinator.data.get("score"),
            "rule_state": self.coordinator.data.get("state_machine"),
        }

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": f"{self._entry.data.get(CONF_ROOM_NAME, 'Room')} Soft Presence",
            "manufacturer": "HA Soft Presence",
            "model": "Virtual Presence Sensor",
            "entry_type": "service",
        }
