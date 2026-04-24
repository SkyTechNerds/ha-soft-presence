"""Coordinator for HA Soft Presence — score engine + state machine + LLM advisory."""
from __future__ import annotations

import asyncio
import json
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
    CONF_ROOM_TYPE,
    CONF_HAS_DOOR,
    CONF_IS_TRANSIT,
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
    CONF_LLM_ENABLED,
    CONF_CONVERSATION_AGENT,
    CONF_LLM_UPDATE_INTERVAL,
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
    WORKSTATION_POWER_THRESHOLD_W,
    DEFAULT_OCCUPIED_THRESHOLD,
    DEFAULT_CLEAR_THRESHOLD,
    DEFAULT_NO_PRESENCE_TIMEOUT,
    DEFAULT_MIN_HOLD_TIME,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_LLM_UPDATE_INTERVAL,
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

_LLM_PROMPT = """\
You are a home presence detection system. Based on the sensor events below, \
decide if the room is currently occupied. Be concise and output JSON only.

Room: {room_name}
Type: {room_type}
Has door: {has_door}
Is transit room: {is_transit}

Recent sensor events (age_sec = seconds ago, 0 = just now):
{events}

Rule engine result: score={rule_score}/100, state={rule_state}

Respond with this exact JSON and nothing else:
{{"occupied": true, "score": 75, "confidence": "high", "reason": "brief explanation"}}
"""

_MAX_EVENT_LOG = 30


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


class SoftPresenceCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Manages presence detection for one room."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.config = entry.data
        self.room_slug = slugify(entry.data.get(CONF_ROOM_NAME, "room"))

        # Decaying event timestamps
        self._last_event: dict[str, float] = {}

        # State machine
        self._sm_state: str = SM_CLEAR
        self._occupied_since: float | None = None
        self._clear_pending_task: asyncio.Task | None = None
        self._clear_pending_start: float | None = None
        self._clear_pending_timeout: float = 0.0

        # Rule engine output
        self._score: int = 0
        self._active_sources: list[str] = []
        self._reason: str = ""

        # Event log for LLM (anonymised)
        self._event_log: list[dict[str, Any]] = []

        # LLM state
        self._llm_last_called: float = 0.0
        self._llm_last_event_count: int = 0  # track new events since last LLM call
        self._llm_data: dict[str, Any] = {}

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
        entities = self._all_entity_ids()
        if entities:
            unsub = async_track_state_change_event(
                self.hass, entities, self._on_entity_changed
            )
            self._unsubs.append(unsub)
        _LOGGER.debug(
            "Soft Presence [%s]: watching %d entities, LLM=%s",
            self.config.get(CONF_ROOM_NAME),
            len(entities),
            self.config.get(CONF_LLM_ENABLED, False),
        )

    def async_teardown(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._cancel_clear_pending()

    # ------------------------------------------------------------------
    # Entity helpers
    # ------------------------------------------------------------------

    def _all_entity_ids(self) -> list[str]:
        sensors = self.config.get("sensors", {})
        ids: list[str] = []
        for key in (
            CONF_MMWAVE_SENSORS, CONF_PIR_SENSORS, CONF_DOOR_SENSORS,
            CONF_WINDOW_SENSORS, CONF_LOCK_ENTITIES, CONF_MEDIA_PLAYERS,
            CONF_LIGHT_ENTITIES, CONF_SWITCH_ENTITIES,
            CONF_WORKSTATION_ENTITIES, CONF_WORKSTATION_POWER_SENSORS,
        ):
            ids.extend(sensors.get(key, []))
        return ids

    @callback
    def _on_entity_changed(self, event: Event) -> None:
        entity_id: str = event.data["entity_id"]
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        sensors = self.config.get("sensors", {})
        now = time.time()
        state = new_state.state

        if entity_id in sensors.get(CONF_MMWAVE_SENSORS, []):
            self._record_event(f"mmwave_{'on' if state == 'on' else 'off'}", now)
        elif entity_id in sensors.get(CONF_PIR_SENSORS, []):
            if state == "on":
                self._last_event["pir"] = now
            self._record_event(f"pir_{'on' if state == 'on' else 'off'}", now)
        elif entity_id in sensors.get(CONF_DOOR_SENSORS, []):
            if state == "on":
                self._last_event["door"] = now
            self._record_event(f"door_{'opened' if state == 'on' else 'closed'}", now)
        elif entity_id in sensors.get(CONF_LOCK_ENTITIES, []):
            if state in ("unlocked", "unlocking"):
                self._last_event["lock"] = now
            self._record_event(f"lock_{state}", now)
        elif entity_id in sensors.get(CONF_MEDIA_PLAYERS, []):
            self._record_event(f"media_{state}", now)
        elif entity_id in sensors.get(CONF_LIGHT_ENTITIES, []) + sensors.get(CONF_SWITCH_ENTITIES, []):
            self._record_event(f"light_{'on' if state == 'on' else 'off'}", now)
        elif entity_id in sensors.get(CONF_WORKSTATION_ENTITIES, []):
            self._record_event(f"workstation_{'on' if state == 'on' else 'off'}", now)

        self.hass.async_create_task(self.async_request_refresh())

    def _record_event(self, event_type: str, timestamp: float) -> None:
        self._event_log.append({"type": event_type, "ts": timestamp})
        if len(self._event_log) > _MAX_EVENT_LOG:
            self._event_log = self._event_log[-_MAX_EVENT_LOG:]

    # ------------------------------------------------------------------
    # Core update
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        self._recalculate_score()
        self._run_state_machine()

        if self.config.get(CONF_LLM_ENABLED) and self.config.get(CONF_CONVERSATION_AGENT):
            interval = int(self.config.get(CONF_LLM_UPDATE_INTERVAL, DEFAULT_LLM_UPDATE_INTERVAL))
            new_events = len(self._event_log) > self._llm_last_event_count
            time_elapsed = (time.time() - self._llm_last_called) >= interval
            if new_events and time_elapsed:
                await self._async_call_llm()

        return self._build_data()

    # ------------------------------------------------------------------
    # Score engine
    # ------------------------------------------------------------------

    def _recalculate_score(self) -> None:
        score = 0
        sources: list[str] = []
        now = time.time()
        sensors = self.config.get("sensors", {})

        for eid in sensors.get(CONF_MMWAVE_SENSORS, []):
            st = self.hass.states.get(eid)
            if st and st.state == "on":
                score += WEIGHT_MMWAVE
                sources.append("mmwave")
                break

        pir_active = False
        for eid in sensors.get(CONF_PIR_SENSORS, []):
            st = self.hass.states.get(eid)
            if st and st.state == "on":
                score += WEIGHT_PIR_ACTIVE
                sources.append("pir")
                pir_active = True
                break
        if not pir_active:
            age = now - self._last_event.get("pir", 0)
            if age < DECAY_PIR:
                c = int(WEIGHT_PIR_RECENT * (1.0 - age / DECAY_PIR))
                if c > 0:
                    score += c
                    sources.append("pir_recent")

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

        for eid in sensors.get(CONF_WORKSTATION_ENTITIES, []):
            st = self.hass.states.get(eid)
            if st and st.state == "on":
                score += WEIGHT_WORKSTATION_ACTIVE
                sources.append("workstation")
                break

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

        lights = sensors.get(CONF_LIGHT_ENTITIES, []) + sensors.get(CONF_SWITCH_ENTITIES, [])
        for eid in lights:
            st = self.hass.states.get(eid)
            if st and st.state == "on":
                score += WEIGHT_LIGHT_MANUAL
                sources.append("light_manual")
                break

        door_age = now - self._last_event.get("door", 0)
        if door_age < DECAY_DOOR:
            c = int(WEIGHT_DOOR_OPENED * (1.0 - door_age / DECAY_DOOR))
            if c > 0:
                score += c
                sources.append("door_recent")

        lock_age = now - self._last_event.get("lock", 0)
        if lock_age < DECAY_LOCK:
            c = int(WEIGHT_LOCK_UNLOCKED * (1.0 - lock_age / DECAY_LOCK))
            if c > 0:
                score += c
                sources.append("lock_recent")

        self._score = min(100, max(0, score))
        self._active_sources = list(dict.fromkeys(sources))
        self._reason = " + ".join(_SOURCE_LABELS.get(s, s) for s in self._active_sources) or "No active signals"

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def _run_state_machine(self) -> None:
        occupied_threshold = int(self.config.get(CONF_OCCUPIED_THRESHOLD, DEFAULT_OCCUPIED_THRESHOLD))
        clear_threshold = int(self.config.get(CONF_CLEAR_THRESHOLD, DEFAULT_CLEAR_THRESHOLD))
        timeout = float(self.config.get(CONF_NO_PRESENCE_TIMEOUT, DEFAULT_NO_PRESENCE_TIMEOUT))
        min_hold = float(self.config.get(CONF_MIN_HOLD_TIME, DEFAULT_MIN_HOLD_TIME))
        now = time.time()

        if self._score >= occupied_threshold:
            if self._sm_state != SM_OCCUPIED:
                _LOGGER.debug("[%s] → OCCUPIED (score=%d)", self.config.get(CONF_ROOM_NAME), self._score)
                self._sm_state = SM_OCCUPIED
                self._occupied_since = now
                self._cancel_clear_pending()

        elif self._score <= clear_threshold:
            if self._sm_state == SM_OCCUPIED:
                held = (now - self._occupied_since) if self._occupied_since else 0
                if held >= min_hold:
                    self._sm_state = SM_CLEAR_PENDING
                    self._schedule_clear(timeout)
            elif self._sm_state in (SM_POSSIBLE_ENTRY, SM_LIKELY_OCCUPIED, SM_POSSIBLE_EXIT):
                self._sm_state = SM_CLEAR_PENDING
                self._schedule_clear(timeout)

        else:
            if self._sm_state == SM_CLEAR_PENDING:
                self._cancel_clear_pending()
                self._sm_state = SM_OCCUPIED
            elif self._sm_state == SM_CLEAR:
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
            occupied_threshold = int(self.config.get(CONF_OCCUPIED_THRESHOLD, DEFAULT_OCCUPIED_THRESHOLD))
            if self._score < occupied_threshold:
                self._sm_state = SM_CLEAR
                self._occupied_since = None
                _LOGGER.debug("[%s] → CLEAR (timeout expired)", self.config.get(CONF_ROOM_NAME))
                await self.async_request_refresh()

    # ------------------------------------------------------------------
    # LLM advisory
    # ------------------------------------------------------------------

    async def _async_call_llm(self) -> None:
        agent_id = self.config.get(CONF_CONVERSATION_AGENT)
        if not agent_id:
            return

        self._llm_last_called = time.time()
        self._llm_last_event_count = len(self._event_log)
        now = self._llm_last_called

        events_text = "\n".join(
            f"  - {e['type']}: {int(now - e['ts'])}s ago"
            for e in self._event_log[-20:]
        ) or "  (no events recorded)"

        prompt = _LLM_PROMPT.format(
            room_name=self.config.get(CONF_ROOM_NAME, "room"),
            room_type=self.config.get(CONF_ROOM_TYPE, "unknown"),
            has_door=self.config.get(CONF_HAS_DOOR, True),
            is_transit=self.config.get(CONF_IS_TRANSIT, False),
            events=events_text,
            rule_score=self._score,
            rule_state=self._sm_state,
        )

        try:
            from homeassistant.components.conversation import async_converse
            from homeassistant.core import Context

            result = await async_converse(
                hass=self.hass,
                text=prompt,
                conversation_id=None,
                context=Context(),
                agent_id=agent_id,
            )
            speech = result.response.speech.get("plain", {}).get("speech", "")
            self._parse_llm_response(speech)
        except Exception as err:
            _LOGGER.warning("[%s] LLM call failed: %s", self.config.get(CONF_ROOM_NAME), err)

    def _parse_llm_response(self, text: str) -> None:
        match = re.search(r"\{[^{}]+\}", text, re.DOTALL)
        if not match:
            _LOGGER.debug("No JSON found in LLM response: %.200s", text)
            return
        try:
            data = json.loads(match.group())
            self._llm_data = {
                "occupied": bool(data.get("occupied", False)),
                "score": max(0, min(100, int(data.get("score", 0)))),
                "confidence": str(data.get("confidence", "low")),
                "reason": str(data.get("reason", "")),
                "last_updated": datetime.now(tz=timezone.utc).isoformat(),
            }
            _LOGGER.debug("[%s] LLM: %s", self.config.get(CONF_ROOM_NAME), self._llm_data)
        except (json.JSONDecodeError, ValueError, TypeError) as err:
            _LOGGER.warning("[%s] LLM parse error: %s — raw: %.200s", self.config.get(CONF_ROOM_NAME), err, text)

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
            last_positive = datetime.fromtimestamp(self._occupied_since, tz=timezone.utc).isoformat()

        timeout_remaining = None
        if self._sm_state == SM_CLEAR_PENDING and self._clear_pending_start:
            elapsed = time.time() - self._clear_pending_start
            timeout_remaining = max(0, int(self._clear_pending_timeout - elapsed))

        return {
            # Rule engine
            "occupied": occupied,
            "score": self._score,
            "confidence": confidence,
            "reason": self._reason,
            "active_sources": self._active_sources,
            "state_machine": self._sm_state,
            "last_positive": last_positive,
            "timeout_remaining": timeout_remaining,
            "room_name": self.config.get(CONF_ROOM_NAME, ""),
            # LLM advisory
            "llm_enabled": bool(self.config.get(CONF_LLM_ENABLED)),
            "llm": self._llm_data,
        }
