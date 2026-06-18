"""Diagnostics support for HA Soft Presence.

Accessible via: Developer Tools → Download Diagnostics on the integration's
device page, or via the HA diagnostics endpoint.
"""
from __future__ import annotations

import time
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

# Redact keys that could contain sensitive credentials.
_REDACT_KEYS: frozenset[str] = frozenset({"api_key", "llm_api_key", "token", "password"})


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a HA Soft Presence config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    return {
        # Config entry data (sensitive keys redacted)
        "config": async_redact_data(dict(entry.data), _REDACT_KEYS),

        # Public coordinator output — same data that drives the HA entities
        "state": coordinator.data or {},

        # Internal state — useful for debugging lock-in, clear-pending, etc.
        "internal": coordinator.get_diagnostic_data(),
    }
