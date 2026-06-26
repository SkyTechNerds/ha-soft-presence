"""HA Soft Presence — virtual presence sensor with sensor fusion."""
from __future__ import annotations

import logging
from datetime import timedelta

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN
from .coordinator import SoftPresenceCoordinator
from .llm_batch import async_batch_llm_update
from .repairs import check_and_raise_issues, clear_all_issues

_BATCH_LLM_INTERVAL = timedelta(seconds=60)  # check every 60 s; each room's own interval still applies

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["binary_sensor", "sensor"]

SERVICE_FORCE_OCCUPIED = "force_occupied"
SERVICE_FORCE_CLEAR = "force_clear"
SERVICE_TOGGLE_OVERRIDE = "toggle_override"
SERVICE_RESET_OVERRIDE = "reset_override"
SERVICE_RELOAD_ALL = "reload_all"

_SERVICE_SCHEMA = vol.Schema({
    vol.Required("entity_id"): cv.entity_id,
})


def _coordinator_for_entity(hass: HomeAssistant, entity_id: str) -> SoftPresenceCoordinator | None:
    """Look up coordinator by binary sensor entity_id."""
    for coordinator in hass.data.get(DOMAIN, {}).values():
        if not isinstance(coordinator, SoftPresenceCoordinator):
            continue
        if entity_id == f"binary_sensor.{coordinator.room_slug}_presence_soft":
            return coordinator
    return None


def _register_services(hass: HomeAssistant) -> None:
    async def _handle_force_occupied(call: ServiceCall) -> None:
        coordinator = _coordinator_for_entity(hass, call.data["entity_id"])
        if coordinator:
            coordinator.set_override("occupied")
            await coordinator.async_request_refresh()

    async def _handle_force_clear(call: ServiceCall) -> None:
        coordinator = _coordinator_for_entity(hass, call.data["entity_id"])
        if coordinator:
            coordinator.set_override("clear")
            await coordinator.async_request_refresh()

    async def _handle_toggle_override(call: ServiceCall) -> None:
        coordinator = _coordinator_for_entity(hass, call.data["entity_id"])
        if coordinator:
            # Flip the *effective* presence: occupied → clear, otherwise → occupied.
            # Sticky like the other overrides — reset_override returns to auto.
            occupied_now = bool(coordinator.data and coordinator.data.get("occupied"))
            coordinator.set_override("clear" if occupied_now else "occupied")
            await coordinator.async_request_refresh()

    async def _handle_reset_override(call: ServiceCall) -> None:
        coordinator = _coordinator_for_entity(hass, call.data["entity_id"])
        if coordinator:
            coordinator.set_override(None)
            await coordinator.async_request_refresh()

    async def _handle_reload_all(call: ServiceCall) -> None:
        entries = hass.config_entries.async_entries(DOMAIN)
        for e in entries:
            await hass.config_entries.async_reload(e.entry_id)

    hass.services.async_register(DOMAIN, SERVICE_FORCE_OCCUPIED, _handle_force_occupied, schema=_SERVICE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_FORCE_CLEAR, _handle_force_clear, schema=_SERVICE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_TOGGLE_OVERRIDE, _handle_toggle_override, schema=_SERVICE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_RESET_OVERRIDE, _handle_reset_override, schema=_SERVICE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_RELOAD_ALL, _handle_reload_all)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its config changes.

    The options flow edits ``entry.data`` (sensor lists, thresholds, LLM, …) via
    ``async_update_entry``. Without this listener the running coordinator keeps the
    old config until a manual reload — e.g. a media player removed from a room
    still counted toward presence. Reloading rebuilds the coordinator with the new
    config so edits take effect immediately.
    """
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one room from a config entry."""
    coordinator = SoftPresenceCoordinator(hass, entry)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Apply config-entry (options-flow) edits live — reload on update.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Surface any config problems as HA repair issues
    check_and_raise_issues(hass, entry)

    # Register services once (idempotent)
    if not hass.services.has_service(DOMAIN, SERVICE_FORCE_OCCUPIED):
        _register_services(hass)

    # Register batch LLM timer once (shared across all rooms)
    if f"{DOMAIN}_llm_unsub" not in hass.data:
        async def _llm_tick(_now=None) -> None:
            await async_batch_llm_update(hass)

        unsub = async_track_time_interval(hass, _llm_tick, _BATCH_LLM_INTERVAL)
        hass.data[f"{DOMAIN}_llm_unsub"] = unsub

    # Always trigger an immediate LLM update after (re)loading an entry so
    # LLM entities don't stay grey until the next 60 s tick.
    hass.async_create_task(async_batch_llm_update(hass))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator: SoftPresenceCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator.async_teardown()
        clear_all_issues(hass, entry)
    return unload_ok
