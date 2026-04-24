"""Coordinator for HA Soft Presence — score engine + state machine."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, Event, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    DOMAIN,
    CONF_ROOM_NAME,
    CONF_OCCUPIED_THRESHOLD,
    CONF_CLEAR_THRESHOLD,
    CONF_NO_PRESENCE_TIMEOUT,
    CONF_MIN_HOLD_TIME,
    CONF_MMWAVE_SENSORS,
    CONF_PIR_SENSORS,
    CONF_DOOR_SENSORS,
    CONF_WINDOW_SENSORS,
    CONF_LOCK_ENTITIES,
    CONF_MEDIA_PLAYERS,
    CONF_LIGHT_ENTITIES,
    CONF_SWITCH_ENTITIES,
    CONF_WORKSTATION_ENTITIES,
    CONF_WORKSTATION_POWER_SENSORS,
    SM_CLEAR,
    SM_POSSIBLE_ENTRY,
    SM_OCCUPIED,
    SM_LIKELY_OCCUPIED,
    SM_POSSIBLE_EXIT,
    SM_CLEAR_PENDING,
    SM_OCCUPIED_STATES,
    WEIGHT_MMWAVE,
    WEIGHT_PIR_ACTIVE,
    WEIGHT_PIR_RECENT,
    WEIGHT_MEDIA_PLAYING,
    WEIGHT_MEDIA_PAUSED,
    WEIGHT_WORKSTATION_ACTIVE,
    WEIGHT_LIGHT_MANUAL,
    WEIGHT_DOOR_OPENED,
    WEIGHT_LOCK_UNLOCKED,
    DECAY_PIR,
    DECAY_DOOR,
    DECAY_LOCK,
    DECAY_LIGHT,
    WORKSTATION_POWER_THRESHOLD_W,
    DEFAULT_OCCUPIED_THRESHOLD,
    DEFAULT_CLEAR_THRESHOLD,
    DEFAULT_NO_PRESENCE_TIMEOUT,
    DEFAULT_MIN_HOLD_TIME,
    DEFAULT_POLL_INTERVAL,
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_LOW,
)

_LOGGER = logging.getLogger(__name__)

_SOURCE_LABELS: dict[str, str] = {
    "mmwave": "mmWave active",
    "pir": "PIR motion",
    "pir_recent": "Recent PIR motion",
    "media_playing": "Media playing",
    "media_paused": "Media paused",
    "workstation": "Workstation active",
    "workstation_power": "Workstation power draw",
    "light_manual": "Light on",
    "door_recent": "Door recently opened",
    "lock_recent": "Lock recently used",
}


def slugify(text: str) -> str:
    """Convert a room name to a safe entity slug."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


class SoftPresenceCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Manages presence detection for one room."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.config = entry.data
        self.room_slug = slugify(entry.data.get(CONF_ROOM_NAME, "room"))

        # Timestamps for decaying events
        self._last_event: dict[str, float] = {}

        # State machine
        self._sm_state: str = SM_CLEAR
        self._occupied_since: float | None = None
        self._clear_pending_task: asyncio.Task | None = None
        self._clear_pending_start: float | None = None
        self._clear_pending_timeout: float = 0.0

        # Current computed values
        self._score: int = 0
        self._active_sources: list[str] = []
        self._reason: str = ""

        self._unsubs: list = []

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=DEFAULT_POLL_INTERVAL),
        )

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Subscribe to all configured entity state changes."""
        entities = self._all_entity_ids()
        if entities:
            unsub = async_track_state_change_event(
                self.hass, entities, self._on_entity_changed
            )
            self._unsubs.append(unsub)
        _LOGGER.debug(
            "Soft Presence [%s]: watching %d entities",
            self.config.get(CONF_ROOM_NAME),
            len(entities),
        )

    def async_teardown(self) -> None:
        """Remove listeners and cancel pending tasks."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._cancel_clear_pending()

    # ------------------------------------------------------------------
    # Entity listeners
    # ------------------------------------------------------------------

    def _all_entity_ids(self) -> list[str]:
        sensors = self.config.get("sensors", {})
        ids: list[str] = []
        for key in (
            CONF_MMWAVE_SENSORS,
            CONF_PIR_SENSORS,
            CONF_DOOR_SENSORS,
            CONF_WINDOW_SENSORS,
            CONF_LOCK_ENTITIES,
            CONF_MEDIA_PLAYERS,
            CONF_LIGHT_ENTITIES,
            CONF_SWITCH_ENTITIES,
            CONF_WORKSTATION_ENTITIES,
            CONF_WORKSTATION_POWER_SENSORS,
        ):
            ids.extend(sensors.get(key, []))
        return ids

    @callback
    def _on_entity_changed(self, event: Event) -> None:
        """Record event timestamps and trigger a refresh."""
        entity_id: str = event.data["entity_id"]
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        sensors = self.config.get("sensors", {})
        now = time.time()

        if entity_id in sensors.get(CONF_DOOR_SENSORS, []):
            if new_state.state == "on":
                self._last_event["door"] = now
                _LOGGER.debug("Door opened: %s", entity_id)

        if entity_id in sensors.get(CONF_LOCK_ENTITIES, []):
            if new_state.state in ("unlocked", "unlocking"):
                self._last_event["lock"] = now

        if entity_id in sensors.get(CONF_PIR_SENSORS, []):
            if new_state.state == "on":
                self._last_event["pir"] = now

        self.hass.async_create_task(self.async_request_refresh())

    # ------------------------------------------------------------------
    # Core update
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        self._recalculate_score()
        self._run_state_machine()
        return self._build_data()

    # ------------------------------------------------------------------
    # Score engine
    # ------------------------------------------------------------------

    def _recalculate_score(self) -> None:
        score = 0
        sources: list[str] = []
        now = time.time()
        sensors = self.config.get("sensors", {})

        # mmWave — highest weight, real-time
        for eid in sensors.get(CONF_MMWAVE_SENSORS, []):
            st = self.hass.states.get(eid)
            if st and st.state == "on":
                score += WEIGHT_MMWAVE
                sources.append("mmwave")
                break

        # PIR — real-time + decaying residual
        pir_active = False
        for eid in sensors.get(CONF_PIR_SENSORS, []):
            st = self.hass.states.get(eid)
            if st and st.state == "on":
                score += WEIGHT_PIR_ACTIVE
                sources.append("pir")
                pir_active = True
                break
        if not pir_active:
            last_pir = self._last_event.get("pir", 0)
            age = now - last_pir
            if age < DECAY_PIR:
                contribution = int(WEIGHT_PIR_RECENT * (1.0 - age / DECAY_PIR))
                if contribution > 0:
                    score += contribution
                    sources.append("pir_recent")

        # Media player
        for eid in sensors.get(CONF_MEDIA_PLAYERS, []):
            st = self.hass.states.get(eid)
            if st:
                if st.state == "playing":
                    score += WEIGHT_MEDIA_PLAYING
                    sources.append("media_playing")
                    break
                if st.state == "paused":
                    score += WEIGHT_MEDIA_PAUSED
                    sources.append("media_paused")
                    break

        # Workstation — binary sensor (e.g., PC online)
        for eid in sensors.get(CONF_WORKSTATION_ENTITIES, []):
            st = self.hass.states.get(eid)
            if st and st.state == "on":
                score += WEIGHT_WORKSTATION_ACTIVE
                sources.append("workstation")
                break

        # Workstation — power sensor
        for eid in sensors.get(CONF_WORKSTATION_POWER_SENSORS, []):
            st = self.hass.states.get(eid)
            if st:
                try:
                    if float(st.state) > WORKSTATION_POWER_THRESHOLD_W:
                        score += WEIGHT_WORKSTATION_ACTIVE
                        sources.append("workstation_power")
                        break
                except (ValueError, TypeError):
                    pass

        # Lights / switches on
        light_sources = sensors.get(CONF_LIGHT_ENTITIES, []) + sensors.get(CONF_SWITCH_ENTITIES, [])
        for eid in light_sources:
            st = self.hass.states.get(eid)
            if st and st.state == "on":
                score += WEIGHT_LIGHT_MANUAL
                sources.append("light_manual")
                break

        # Door recently opened (decaying)
        door_age = now - self._last_event.get("door", 0)
        if door_age < DECAY_DOOR:
            c = int(WEIGHT_DOOR_OPENED * (1.0 - door_age / DECAY_DOOR))
            if c > 0:
                score += c
                sources.append("door_recent")

        # Lock recently used (decaying)
        lock_age = now - self._last_event.get("lock", 0)
        if lock_age < DECAY_LOCK:
            c = int(WEIGHT_LOCK_UNLOCKED * (1.0 - lock_age / DECAY_LOCK))
            if c > 0:
                score += c
                sources.append("lock_recent")

        self._score = min(100, max(0, score))
        self._active_sources = list(dict.fromkeys(sources))
        self._reason = self._build_reason()

    def _build_reason(self) -> str:
        if not self._active_sources:
            return "No active signals"
        return " + ".join(_SOURCE_LABELS.get(s, s) for s in self._active_sources)

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def _run_state_machine(self) -> None:
        occupied_threshold = int(
            self.config.get(CONF_OCCUPIED_THRESHOLD, DEFAULT_OCCUPIED_THRESHOLD)
        )
        clear_threshold = int(
            self.config.get(CONF_CLEAR_THRESHOLD, DEFAULT_CLEAR_THRESHOLD)
        )
        timeout = float(
            self.config.get(CONF_NO_PRESENCE_TIMEOUT, DEFAULT_NO_PRESENCE_TIMEOUT)
        )
        min_hold = float(self.config.get(CONF_MIN_HOLD_TIME, DEFAULT_MIN_HOLD_TIME))
        now = time.time()

        if self._score >= occupied_threshold:
            # Strong signal → immediately OCCUPIED
            if self._sm_state != SM_OCCUPIED:
                _LOGGER.debug(
                    "[%s] → OCCUPIED (score=%d)",
                    self.config.get(CONF_ROOM_NAME),
                    self._score,
                )
                self._sm_state = SM_OCCUPIED
                self._occupied_since = now
                self._cancel_clear_pending()

        elif self._score <= clear_threshold:
            if self._sm_state == SM_OCCUPIED:
                held = (now - self._occupied_since) if self._occupied_since else 0
                if held >= min_hold:
                    self._sm_state = SM_CLEAR_PENDING
                    self._schedule_clear(timeout)
                    _LOGGER.debug(
                        "[%s] → CLEAR_PENDING (score=%d, timeout=%.0fs)",
                        self.config.get(CONF_ROOM_NAME),
                        self._score,
                        timeout,
                    )

            elif self._sm_state in (SM_POSSIBLE_ENTRY, SM_LIKELY_OCCUPIED, SM_POSSIBLE_EXIT):
                self._sm_state = SM_CLEAR_PENDING
                self._schedule_clear(timeout)

            # SM_CLEAR and SM_CLEAR_PENDING: no change, timer handles transition

        else:
            # Hysteresis zone (between thresholds)
            if self._sm_state == SM_CLEAR_PENDING:
                # Score rose back — cancel pending clear, stay occupied
                self._cancel_clear_pending()
                self._sm_state = SM_OCCUPIED
                _LOGGER.debug(
                    "[%s] CLEAR_PENDING → OCCUPIED (score recovered to %d)",
                    self.config.get(CONF_ROOM_NAME),
                    self._score,
                )
            elif self._sm_state == SM_CLEAR:
                # Score crept up but not past threshold — possible entry
                self._sm_state = SM_POSSIBLE_ENTRY

    def _schedule_clear(self, timeout: float) -> None:
        self._cancel_clear_pending()
        self._clear_pending_start = time.time()
        self._clear_pending_timeout = timeout
        self._clear_pending_task = self.hass.async_create_task(
            self._async_clear_after_timeout(timeout)
        )

    def _cancel_clear_pending(self) -> None:
        if self._clear_pending_task:
            self._clear_pending_task.cancel()
            self._clear_pending_task = None
        self._clear_pending_start = None

    async def _async_clear_after_timeout(self, timeout: float) -> None:
        await asyncio.sleep(timeout)
        if self._sm_state == SM_CLEAR_PENDING:
            occupied_threshold = int(
                self.config.get(CONF_OCCUPIED_THRESHOLD, DEFAULT_OCCUPIED_THRESHOLD)
            )
            if self._score < occupied_threshold:
                self._sm_state = SM_CLEAR
                self._occupied_since = None
                _LOGGER.debug(
                    "[%s] → CLEAR (timeout expired)",
                    self.config.get(CONF_ROOM_NAME),
                )
                await self.async_request_refresh()

    # ------------------------------------------------------------------
    # Data output
    # ------------------------------------------------------------------

    def _build_data(self) -> dict[str, Any]:
        occupied = self._sm_state in SM_OCCUPIED_STATES

        if self._score >= 70 and len(self._active_sources) >= 2:
            confidence = CONFIDENCE_HIGH
        elif self._score >= 35:
            confidence = CONFIDENCE_MEDIUM
        else:
            confidence = CONFIDENCE_LOW

        last_positive = None
        if self._occupied_since:
            last_positive = datetime.fromtimestamp(
                self._occupied_since, tz=timezone.utc
            ).isoformat()

        timeout_remaining = None
        if self._sm_state == SM_CLEAR_PENDING and self._clear_pending_start:
            elapsed = time.time() - self._clear_pending_start
            timeout_remaining = max(0, int(self._clear_pending_timeout - elapsed))

        return {
            "occupied": occupied,
            "score": self._score,
            "confidence": confidence,
            "reason": self._reason,
            "active_sources": self._active_sources,
            "state_machine": self._sm_state,
            "last_positive": last_positive,
            "timeout_remaining": timeout_remaining,
            "room_name": self.config.get(CONF_ROOM_NAME, ""),
        }
