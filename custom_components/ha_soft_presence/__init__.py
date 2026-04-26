"""HA Soft Presence — virtual presence sensor with sensor fusion."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import SoftPresenceCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["binary_sensor", "sensor"]

SERVICE_FORCE_OCCUPIED = "force_occupied"
SERVICE_FORCE_CLEAR = "force_clear"
SERVICE_RESET_OVERRIDE = "reset_override"

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

    async def _handle_reset_override(call: ServiceCall) -> None:
        coordinator = _coordinator_for_entity(hass, call.data["entity_id"])
        if coordinator:
            coordinator.set_override(None)
            await coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, SERVICE_FORCE_OCCUPIED, _handle_force_occupied, schema=_SERVICE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_FORCE_CLEAR, _handle_force_clear, schema=_SERVICE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_RESET_OVERRIDE, _handle_reset_override, schema=_SERVICE_SCHEMA)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one room from a config entry."""
    coordinator = SoftPresenceCoordinator(hass, entry)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    # Register services once (idempotent)
    if not hass.services.has_service(DOMAIN, SERVICE_FORCE_OCCUPIED):
        _register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator: SoftPresenceCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator.async_teardown()
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
