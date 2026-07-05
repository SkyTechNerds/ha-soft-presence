"""Config validation and HA repair issues for HA Soft Presence.

Checks run once on integration load. Issues surface in
Settings → System → Repairs so users see actionable warnings instead
of silent misbehaviour.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from .const import (
    DOMAIN,
    CONF_ROOM_NAME,
    CONF_HAS_DOOR,
    CONF_DOOR_SENSORS,
    CONF_MMWAVE_SENSORS,
    CONF_PIR_SENSORS,
    CONF_ESPRESENSE_SENSORS,
    CONF_PERSON_COUNT_SENSORS,
)

# Keys that contribute to the presence score — absence is a warning
_PRESENCE_KEYS: tuple[str, ...] = (
    CONF_MMWAVE_SENSORS,
    CONF_PIR_SENSORS,
    CONF_ESPRESENSE_SENSORS,
    CONF_PERSON_COUNT_SENSORS,
)

# All sensor keys whose entities are checked for existence in HA
_ALL_SENSOR_KEYS: tuple[str, ...] = (
    CONF_MMWAVE_SENSORS,
    CONF_PIR_SENSORS,
    CONF_ESPRESENSE_SENSORS,
    CONF_PERSON_COUNT_SENSORS,
    CONF_DOOR_SENSORS,
    "window_sensors",
    "lock_entities",
    "media_players",
    "light_entities",
    "switch_entities",
    "workstation_sensors",
)


def check_and_raise_issues(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Check integration config and surface problems as HA repair issues."""
    room = entry.data.get(CONF_ROOM_NAME, "Unknown")
    sensors = entry.data.get("sensors", {})

    # ── Issue 1: No presence sensors configured ──────────────────────────
    # Without at least one presence sensor (mmWave / PIR / BLE / camera)
    # the score never crosses the occupied threshold on its own — the room
    # will always stay CLEAR regardless of activity.
    presence_entities: list[str] = []
    for key in _PRESENCE_KEYS:
        presence_entities.extend(sensors.get(key, []))

    issue_id = f"no_presence_sensors_{entry.entry_id}"
    if not presence_entities:
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="no_presence_sensors",
            translation_placeholders={"room_name": room},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, issue_id)

    # ── Issue 2: has_door=True but no door contacts configured ───────────
    # The door-closed lock-in feature (keeps the room OCCUPIED when the
    # door has been closed) requires a door contact. Without one, lock-in
    # is silently disabled even though the room is marked as having a door.
    issue_id = f"has_door_no_sensor_{entry.entry_id}"
    if entry.data.get(CONF_HAS_DOOR) and not sensors.get(CONF_DOOR_SENSORS):
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="has_door_no_sensor",
            translation_placeholders={"room_name": room},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, issue_id)

    # ── Issue 3: Configured entities missing from HA state machine ───────
    # A configured entity that HA doesn't know about contributes nothing
    # to the score — it has been removed, renamed, or not yet loaded.
    all_configured: list[str] = []
    for key in _ALL_SENSOR_KEYS:
        all_configured.extend(sensors.get(key, []))
    # Sleep-mode entities live at top-level config, not inside "sensors"
    all_configured.extend(entry.data.get("sleep_mode_entities", []))

    # An entity counts as missing only if BOTH the state machine and the
    # entity registry don't know it. The registry knows registered entities
    # even before their platform has loaded (or while a device is offline),
    # so this only flags entities that were genuinely removed or renamed —
    # not ones that merely haven't produced a state yet.
    registry = er.async_get(hass)
    missing = [
        eid
        for eid in all_configured
        if hass.states.get(eid) is None and registry.async_get(eid) is None
    ]
    issue_id = f"missing_entities_{entry.entry_id}"
    if missing:
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="missing_entities",
            translation_placeholders={
                "room_name": room,
                # Show at most 5 entity IDs so the message stays readable
                "entities": ", ".join(missing[:5]) + (" …" if len(missing) > 5 else ""),
                "count": str(len(missing)),
            },
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, issue_id)


def clear_all_issues(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove all repair issues raised for this config entry."""
    for suffix in ("no_presence_sensors", "has_door_no_sensor", "missing_entities"):
        ir.async_delete_issue(hass, DOMAIN, f"{suffix}_{entry.entry_id}")
