"""Coordinator for HA Soft Presence — score engine + state machine + LLM advisory."""
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
    CONF_HAS_DOOR,
    CONF_DISABLE_DOOR_ENTRY,
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
    CONF_WORKSTATION_SENSORS,
    CONF_ESPRESENSE_SENSORS,
    CONF_PERSON_COUNT_SENSORS,
    CONF_WORKSTATION_ENTITIES,
    CONF_WORKSTATION_POWER_SENSORS,
    CONF_SLEEP_MODE_ENTITIES,
    CONF_SLEEP_CLEAR_THRESHOLD,
    CONF_LLM_ENABLED,
    CONF_LLM_PROVIDER,
    CONF_CONVERSATION_AGENT,
    CONF_LLM_UPDATE_INTERVAL,
    CONF_LLM_BASE_URL,
    CONF_LLM_API_KEY,
    CONF_LLM_MODEL,
    LLM_PROVIDER_HTTP,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    SM_CLEAR,
    SM_POSSIBLE_ENTRY,
    SM_OCCUPIED,
    SM_LIKELY_OCCUPIED,
    SM_POSSIBLE_EXIT,
    SM_CLEAR_PENDING,
    SM_OCCUPIED_STATES,
    WEIGHT_MMWAVE,
    WEIGHT_PERSON_COUNT,
    WEIGHT_PIR_ACTIVE,
    WEIGHT_PIR_RECENT,
    WEIGHT_ESPRESENSE,
    WEIGHT_MEDIA_PLAYING,
    WEIGHT_MEDIA_PAUSED,
    WEIGHT_WORKSTATION_ACTIVE,
    WEIGHT_LIGHT_MANUAL,
    WEIGHT_LIGHT_SWITCHED_ON,
    WEIGHT_DOOR_OPENED,
    WEIGHT_LOCK_UNLOCKED,
    DECAY_PIR,
    DECAY_DOOR,
    DECAY_LIGHT,
    DECAY_LOCK,
    WORKSTATION_POWER_THRESHOLD_W,
    DEFAULT_OCCUPIED_THRESHOLD,
    DEFAULT_CLEAR_THRESHOLD,
    DEFAULT_NO_PRESENCE_TIMEOUT,
    DEFAULT_MIN_HOLD_TIME,
    TRANSIT_CLEAR_TIMEOUT,
    DEFAULT_DOOR_LOCKED_IN_TIMEOUT,
    DOOR_LOCK_SOLID_DURATION,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_LLM_UPDATE_INTERVAL,
    DEFAULT_SLEEP_CLEAR_THRESHOLD,
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_LOW,
)

_LOGGER = logging.getLogger(__name__)

_SOURCE_LABELS: dict[str, str] = {
    "mmwave": "mmWave active",
    "pir": "PIR motion",
    "pir_recent": "Recent PIR motion",
    "ble_home": "BLE device in room",
    "person_count": "Person detected (camera)",
    "media_playing": "Media playing",
    "media_paused": "Media paused",
    "workstation": "Workstation active",
    "light_manual": "Light on",
    "light_switched_on": "Light switched on",
    "door_recent": "Door recently opened",
    "lock_recent": "Lock recently used",
}

# Signals that are positive proof of a *specific* person/headcount in the room
# (identity via BLE, or a counted person). Unlike ambiguous motion (PIR/mmWave)
# these never need door corroboration, so the entry-gate must not suppress them.
_STRONG_SOURCES: tuple[str, ...] = ("ble_home", "person_count")

# Weak "ambient" sources that are NOT proof of presence and must never keep a
# room OCCUPIED on their own. A manually-on light stays on in an empty room, and
# the lighting automation re-asserts it while the room reads occupied — a
# feedback loop. WEIGHT_LIGHT_MANUAL is kept below the normal clear threshold,
# but sleep mode lowers the clear threshold (potentially below the light weight),
# so this is enforced explicitly: if the ONLY active source is ambient, the room
# takes the clear path regardless of the (sleep) threshold.
_WEAK_HOLD_SOURCES: tuple[str, ...] = ("light_manual",)


_MAX_EVENT_LOG = 30


def slugify(text: str) -> str:
    text = text.lower().strip()
    # German umlauts / eszett → ASCII digraphs (ä→ae, ö→oe, ü→ue, ß→ss)
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(a, b)
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

        # Frozen snapshot of the last moment the score crossed occupied_threshold
        self._last_positive_reason: str = ""
        self._last_positive_sources: list[str] = []

        # Event log for LLM (anonymised). The list is capped at _MAX_EVENT_LOG,
        # so its length saturates — never use len() to detect "new events".
        self._event_log: list[dict[str, Any]] = []
        # Monotonic total of events ever recorded (never reset, never capped).
        # This is what needs_llm_update() compares against so the "new events"
        # check keeps working after the capped log fills up.
        self._event_total: int = 0

        # LLM state
        self._llm_last_called: float = 0.0
        self._llm_last_event_count: int = 0
        self._llm_data: dict[str, Any] = {}

        # Event firing — track previous occupied state
        self._was_occupied: bool | None = None

        # Door lock-in tracking: True once we have observed score>=occupied
        # AND all doors closed continuously for DOOR_LOCK_SOLID_DURATION seconds.
        # Reset on any door-open event and on transition to CLEAR.
        self._has_been_solid: bool = False
        self._solid_candidate_since: float | None = None

        # Entry-gate tracking: has a door opened since the room was last CLEAR?
        # Starts True (fail-open) so occupancy is allowed before the first clear
        # observation — we can't know the pre-startup history. Set True on any
        # door-open, reset to False on the transition to CLEAR. While False the
        # gate blocks promotion to OCCUPIED (only when the option is enabled).
        self._door_opened_since_clear: bool = True

        # Manual override: "occupied" | "clear" | None
        self._manual_override: str | None = None

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
            CONF_MMWAVE_SENSORS, CONF_PIR_SENSORS, CONF_ESPRESENSE_SENSORS,
            CONF_PERSON_COUNT_SENSORS,
            CONF_DOOR_SENSORS, CONF_WINDOW_SENSORS, CONF_LOCK_ENTITIES,
            CONF_MEDIA_PLAYERS, CONF_LIGHT_ENTITIES, CONF_SWITCH_ENTITIES,
            CONF_WORKSTATION_SENSORS, CONF_WORKSTATION_ENTITIES, CONF_WORKSTATION_POWER_SENSORS,
        ):
            ids.extend(sensors.get(key, []))
        # Sleep mode entities live at config top level, not in sensors dict
        ids.extend(self.config.get(CONF_SLEEP_MODE_ENTITIES, []))
        return ids

    @callback
    def _on_entity_changed(self, event: Event) -> None:
        entity_id: str = event.data["entity_id"]
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        # A transition OUT OF None/unknown/unavailable is the entity coming back
        # online (HA restart, device reconnect) — not a real-world event. Recording
        # it would fake a "door opened" / "pir on", reset the lock-in, or lift the
        # entry-gate (a restored door reporting "on" is NOT someone entering).
        # Skip event recording but still refresh so the live score reflects the
        # now-current state.
        old_state = event.data.get("old_state")
        old_val = old_state.state if old_state is not None else None
        if old_val in (None, "unavailable", "unknown"):
            self.hass.async_create_task(self.async_request_refresh())
            return

        sensors = self.config.get("sensors", {})
        now = time.time()
        state = new_state.state

        if entity_id in sensors.get(CONF_MMWAVE_SENSORS, []):
            if state == "on":
                self._release_clear_override("mmWave motion")
            self._record_event(f"mmwave_{'on' if state == 'on' else 'off'}", now)
        elif entity_id in sensors.get(CONF_PIR_SENSORS, []):
            if state == "on":
                self._last_event["pir"] = now
                self._release_clear_override("PIR motion")
            self._record_event(f"pir_{'on' if state == 'on' else 'off'}", now)
        elif entity_id in sensors.get(CONF_DOOR_SENSORS, []):
            if state == "on":
                self._last_event["door"] = now
                # Door opened — someone could have entered or left during this interval.
                # Drop the lock-in trust and restart the solid-streak timer from scratch
                # once the door closes again and score stays high.
                self._has_been_solid = False
                self._solid_candidate_since = None
                # Entry-gate: a door-open means someone could have entered, so
                # presence signals are now trusted again until the next clear.
                self._door_opened_since_clear = True
                self._release_clear_override("door opened")
            self._record_event(f"door_{'opened' if state == 'on' else 'closed'}", now)
        elif entity_id in sensors.get(CONF_LOCK_ENTITIES, []):
            if state in ("unlocked", "unlocking"):
                self._last_event["lock"] = now
            self._record_event(f"lock_{state}", now)
        elif entity_id in sensors.get(CONF_MEDIA_PLAYERS, []):
            self._record_event(f"media_{state}", now)
        elif entity_id in sensors.get(CONF_LIGHT_ENTITIES, []) + sensors.get(CONF_SWITCH_ENTITIES, []):
            if state == "on" and old_val == "off" and event.context.parent_id is None:
                # A human flipped a light/switch on (no automation context —
                # automations/scripts always carry a parent_id). That is positive
                # proof someone is in the room: decaying entry evidence that
                # promotes immediately (see WEIGHT_LIGHT_SWITCHED_ON) and opens
                # the entry-gate. Automation-caused turn-ons never land here.
                self._last_event["light_manual_on"] = now
                self._door_opened_since_clear = True
                self._release_clear_override("light switched on manually")
            self._record_event(f"light_{'on' if state == 'on' else 'off'}", now)
        elif entity_id in sensors.get(CONF_ESPRESENSE_SENSORS, []):
            in_room = state.lower() not in ("away", "unavailable", "unknown", "none", "")
            if in_room:
                self._release_clear_override("BLE device arrived")
            self._record_event(f"ble_{'home' if in_room else 'away'}", now)
        elif entity_id in sensors.get(CONF_PERSON_COUNT_SENSORS, []):
            try:
                count = int(float(state))
            except (ValueError, TypeError):
                count = 0
            if count > 0:
                self._release_clear_override("person counted")
            self._record_event(f"person_count_{count}", now)
        elif entity_id in (
            sensors.get(CONF_WORKSTATION_SENSORS, [])
            + sensors.get(CONF_WORKSTATION_ENTITIES, [])
        ):
            self._record_event(f"workstation_{'on' if state == 'on' else 'off'}", now)

        self.hass.async_create_task(self.async_request_refresh())

    def _record_event(self, event_type: str, timestamp: float) -> None:
        self._event_log.append({"type": event_type, "ts": timestamp})
        self._event_total += 1
        if len(self._event_log) > _MAX_EVENT_LOG:
            self._event_log = self._event_log[-_MAX_EVENT_LOG:]

    # ------------------------------------------------------------------
    # Core update
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            self._recalculate_score()
            self._update_solid_tracking(time.time())
            self._run_state_machine()
        except Exception as err:
            _LOGGER.error("[%s] Score/state error: %s", self.config.get(CONF_ROOM_NAME), err)

        return self._build_data()

    def _update_solid_tracking(self, now: float) -> None:
        """Track whether we have observed a continuous \"solid\" presence streak.

        A streak counts while: score is at or above the occupied threshold AND
        every configured door contact is currently closed. Once such a streak
        has lasted DOOR_LOCK_SOLID_DURATION seconds, ``_has_been_solid`` flips
        to True and stays True for the rest of the OCCUPIED session — even if
        the score later drops because the occupant sits still. The flag is
        only cleared by a door-open event (handled in ``_on_entity_changed``)
        or by the OCCUPIED → CLEAR transition.
        """
        if not self.config.get(CONF_HAS_DOOR, False):
            return
        sensors = self.config.get("sensors", {})
        door_ids = sensors.get(CONF_DOOR_SENSORS, [])
        if not door_ids:
            return
        occupied_threshold = int(
            self.config.get(CONF_OCCUPIED_THRESHOLD, DEFAULT_OCCUPIED_THRESHOLD)
        )

        all_closed = True
        for eid in door_ids:
            st = self.hass.states.get(eid)
            if st is None or st.state != "off":
                all_closed = False
                break

        if self._score >= occupied_threshold and all_closed:
            if self._solid_candidate_since is None:
                self._solid_candidate_since = now
            elif (
                not self._has_been_solid
                and (now - self._solid_candidate_since) >= DOOR_LOCK_SOLID_DURATION
            ):
                self._has_been_solid = True
                _LOGGER.debug(
                    "[%s] Door lock-in armed (solid streak %ds)",
                    self.config.get(CONF_ROOM_NAME), DOOR_LOCK_SOLID_DURATION,
                )
        else:
            # Streak broken — either score dropped or a door is open/unavailable.
            # _has_been_solid is intentionally NOT cleared here: a score dip is
            # exactly the situation lock-in is meant to bridge. It only clears
            # on door-open or on the CLEAR transition.
            self._solid_candidate_since = None

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

        # Person-count sensors: numeric sensor (e.g. camera people counter)
        # Any sensor with value > 0 counts as a strong presence signal (+80)
        for eid in sensors.get(CONF_PERSON_COUNT_SENSORS, []):
            st = self.hass.states.get(eid)
            if st and st.state not in ("unavailable", "unknown", "none", ""):
                try:
                    if int(float(st.state)) > 0:
                        score += WEIGHT_PERSON_COUNT
                        sources.append("person_count")
                        break
                except (ValueError, TypeError):
                    pass

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

        # ESPresense: sensor state = room name where device is detected
        # Compare slugified state against this room's slug
        for eid in sensors.get(CONF_ESPRESENSE_SENSORS, []):
            st = self.hass.states.get(eid)
            if st and st.state.lower() not in ("away", "unavailable", "unknown", "none", ""):
                if slugify(st.state) == self.room_slug:
                    score += WEIGHT_ESPRESENSE
                    sources.append("ble_home")
                    break

        for eid in sensors.get(CONF_MEDIA_PLAYERS, []):
            st = self.hass.states.get(eid)
            if st:
                if st.state == "playing":
                    score += WEIGHT_MEDIA_PLAYING
                    sources.append("media_playing")
                    break
                if st.state == "paused":
                    # A "speaker" (e.g. a voice-assistant satellite) sits in
                    # "paused" as its idle state — that is not a presence signal.
                    # Count "paused" only for video devices (TV/receiver/…).
                    # device_class is often None (e.g. Apple TV via pyatv), so we
                    # blacklist speakers rather than whitelist tv/receiver — a
                    # paused movie on a device_class-less player must still count.
                    if st.attributes.get("device_class") == "speaker":
                        continue
                    score += WEIGHT_MEDIA_PAUSED
                    sources.append("media_paused")
                    break

        ws_active = False
        # Combined field (new) + legacy separate fields (backward compat)
        ws_entities = (
            sensors.get(CONF_WORKSTATION_SENSORS, [])
            + sensors.get(CONF_WORKSTATION_ENTITIES, [])
            + sensors.get(CONF_WORKSTATION_POWER_SENSORS, [])
        )
        for eid in ws_entities:
            st = self.hass.states.get(eid)
            if not st:
                continue
            domain = eid.split(".")[0]
            if domain == "binary_sensor" and st.state == "on":
                ws_active = True
                break
            elif domain == "sensor":
                try:
                    if float(st.state) > WORKSTATION_POWER_THRESHOLD_W:
                        ws_active = True
                        break
                except (ValueError, TypeError):
                    pass
        if ws_active:
            score += WEIGHT_WORKSTATION_ACTIVE
            sources.append("workstation")

        lights = sensors.get(CONF_LIGHT_ENTITIES, []) + sensors.get(CONF_SWITCH_ENTITIES, [])
        for eid in lights:
            st = self.hass.states.get(eid)
            if st and st.state == "on":
                score += WEIGHT_LIGHT_MANUAL
                sources.append("light_manual")
                break

        # Manual light-switch-on event (human action, automation turn-ons are
        # filtered at recording time) — strong decaying entry evidence.
        light_on_age = now - self._last_event.get("light_manual_on", 0)
        if light_on_age < DECAY_LIGHT:
            c = int(WEIGHT_LIGHT_SWITCHED_ON * (1.0 - light_on_age / DECAY_LIGHT))
            if c > 0:
                score += c
                sources.append("light_switched_on")

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

    def _sleep_mode_active(self) -> bool:
        """Return True if any configured sleep mode entity is on."""
        for eid in self.config.get(CONF_SLEEP_MODE_ENTITIES, []):
            st = self.hass.states.get(eid)
            if st and st.state == "on":
                return True
        return False

    def _run_state_machine(self) -> None:
        occupied_threshold = int(self.config.get(CONF_OCCUPIED_THRESHOLD, DEFAULT_OCCUPIED_THRESHOLD))
        clear_threshold = int(self.config.get(CONF_CLEAR_THRESHOLD, DEFAULT_CLEAR_THRESHOLD))
        is_transit = self.config.get(CONF_IS_TRANSIT, False)
        # Sleep mode keeps a stationary-occupancy room (bedroom) occupied longer
        # by lowering the clear threshold. A transit room (hallway) is the
        # opposite — at night it should clear FASTER — so it keeps the normal
        # threshold and relies on the short transit timeout below.
        if self._sleep_mode_active() and not is_transit:
            clear_threshold = int(self.config.get(CONF_SLEEP_CLEAR_THRESHOLD, DEFAULT_SLEEP_CLEAR_THRESHOLD))
        timeout = float(self.config.get(CONF_NO_PRESENCE_TIMEOUT, DEFAULT_NO_PRESENCE_TIMEOUT))
        min_hold = float(self.config.get(CONF_MIN_HOLD_TIME, DEFAULT_MIN_HOLD_TIME))
        now = time.time()

        # Entry-gate: while it blocks, presence signals cannot promote the room
        # to OCCUPIED — force the clear path instead. Only ever True when the
        # room is currently clear and no door has opened since (see helper).
        gate_blocks = self._entry_gate_blocks()

        # A weak ambient-only source (a manually-on light) must not keep the room
        # OCCUPIED by itself — force the clear path even if its score sits above
        # the (sleep) clear threshold. See _WEAK_HOLD_SOURCES.
        only_ambient = bool(self._active_sources) and all(
            s in _WEAK_HOLD_SOURCES for s in self._active_sources
        )

        if self._score >= occupied_threshold and not gate_blocks:
            if self._sm_state != SM_OCCUPIED:
                _LOGGER.debug("[%s] → OCCUPIED (score=%d)", self.config.get(CONF_ROOM_NAME), self._score)
                self._sm_state = SM_OCCUPIED
                self._occupied_since = now
                self._cancel_clear_pending()
            # Always freeze the reason at the moment score crosses the threshold
            self._last_positive_reason = self._reason
            self._last_positive_sources = list(self._active_sources)

        elif self._score <= clear_threshold or gate_blocks or only_ambient:
            if gate_blocks and self._score >= occupied_threshold:
                self._reason = f"{self._reason} (suppressed: no door entry)"
            effective_timeout = self._effective_clear_timeout(timeout, now)
            if self._sm_state == SM_OCCUPIED:
                # _occupied_since can be None if we entered OCCUPIED via the
                # hysteresis recovery path (CLEAR_PENDING → OCCUPIED) without
                # a fresh signal — treat as min_hold already satisfied to avoid
                # getting stuck forever.
                held = (now - self._occupied_since) if self._occupied_since else min_hold
                if held >= min_hold:
                    self._sm_state = SM_CLEAR_PENDING
                    self._schedule_clear(effective_timeout)
            elif self._sm_state in (SM_POSSIBLE_ENTRY, SM_LIKELY_OCCUPIED, SM_POSSIBLE_EXIT):
                self._sm_state = SM_CLEAR_PENDING
                self._schedule_clear(effective_timeout)

        else:
            if self._sm_state == SM_CLEAR_PENDING:
                self._cancel_clear_pending()
                self._sm_state = SM_OCCUPIED
                # Ensure _occupied_since is set so the next drop can compute held time
                if self._occupied_since is None:
                    self._occupied_since = now
            elif self._sm_state == SM_CLEAR:
                self._sm_state = SM_POSSIBLE_ENTRY

    def _entry_gate_blocks(self) -> bool:
        """Return True if the entry-gate currently blocks promotion to OCCUPIED.

        **On by default** for any room that has a door contact: a closed door
        that has not opened since the room was last CLEAR proves nobody entered,
        so an ambiguous PIR/mmWave signal is a likely false trigger and must not
        mark the room occupied (e.g. a normally-empty guest room where the mmWave
        false-fires all night). Per-room opt-out via CONF_DISABLE_DOOR_ENTRY for
        an unreliable door sensor. (The legacy opt-in CONF_REQUIRE_DOOR_ENTRY no
        longer influences this — the door contact itself arms the gate.)
        ``_door_opened_since_clear`` starts True (fail-open at startup) and is
        only False after a clean CLEAR with no subsequent door-open, so this
        never blocks an already-occupied room — a room the lock-in holds through
        a closed door (someone still inside) is never suppressed.

        Three exemptions keep the gate from suppressing *real* presence:
          1. Entry was captured — a door opened since the last CLEAR.
          2. A door is currently OPEN — free access, presence is plausible even
             without a captured open-transition (e.g. the door is left open to
             air the room, the occupant walks in and closes it behind them, so
             no open-event ever fires; or a door sensor simply missed the open).
          3. A STRONG presence signal is active — a BLE device located in this
             room, or a person-count sensor > 0. These are positive proof of a
             specific person/headcount and never need door corroboration; only
             ambiguous motion (PIR/mmWave) is gated. (A human switching a light
             on also opens the gate — see the light-switched-on event handler.)
        """
        if self.config.get(CONF_DISABLE_DOOR_ENTRY, False):
            return False
        if not self.config.get(CONF_HAS_DOOR, False):
            return False
        door_ids = self.config.get("sensors", {}).get(CONF_DOOR_SENSORS, [])
        if not door_ids:
            return False
        # 1) Entry captured since the last clear → trust presence
        if self._door_opened_since_clear:
            return False
        # 2) A door is currently open → free access, don't gate
        for eid in door_ids:
            st = self.hass.states.get(eid)
            if st is not None and st.state == "on":
                return False
        # 3) A strong identity/headcount signal is positive proof of presence
        if any(src in self._active_sources for src in _STRONG_SOURCES):
            return False
        return True

    def _effective_clear_timeout(self, default_timeout: float, now: float) -> float:
        """Return a longer timeout when the room is in a locked-in state.

        Lock-in trust (``_has_been_solid``) is earned by a continuous
        DOOR_LOCK_SOLID_DURATION window of score>=occupied AND all doors
        closed (see ``_update_solid_tracking``). It is dropped whenever a
        door opens (someone could have left) or when the OCCUPIED session
        ends. When trust is held AND every configured door is currently
        closed, we extend the no-presence timeout to a 4 h sanity cap so
        sitting still doesn't clear the room. Otherwise the default applies.

        This handles e.g. a brief visit from another person: door opens →
        trust dropped → default 5 min timeout. After they leave and the
        door closes, the solid streak rebuilds from zero, re-arming the
        lock-in once the room has been quiet-with-occupant for the
        configured duration.

        Transit rooms (hallways/corridors) are the exception: they are
        pass-through, so the timeout is capped to TRANSIT_CLEAR_TIMEOUT and the
        lock-in never applies — a hallway should clear quickly once motion
        stops, day or night (nobody "sits still" in a corridor).
        """
        if self.config.get(CONF_IS_TRANSIT, False):
            return min(default_timeout, TRANSIT_CLEAR_TIMEOUT)
        if not self.config.get(CONF_HAS_DOOR, False):
            return default_timeout
        sensors = self.config.get("sensors", {})
        door_ids = sensors.get(CONF_DOOR_SENSORS, [])
        if not door_ids:
            return default_timeout
        if not self._has_been_solid:
            return default_timeout
        # Lock-in is armed — confirm doors are still all closed right now.
        for eid in door_ids:
            st = self.hass.states.get(eid)
            if st is None or st.state != "off":
                return default_timeout
        _LOGGER.debug(
            "[%s] Door locked-in: timeout %ds → %ds (solid streak armed, all doors closed)",
            self.config.get(CONF_ROOM_NAME), int(default_timeout), DEFAULT_DOOR_LOCKED_IN_TIMEOUT,
        )
        return DEFAULT_DOOR_LOCKED_IN_TIMEOUT

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
                # End of OCCUPIED session — drop lock-in trust so it has to be
                # re-earned on the next entry.
                self._has_been_solid = False
                self._solid_candidate_since = None
                # Entry-gate: room is now empty — require a fresh door-open before
                # presence signals may mark it occupied again.
                self._door_opened_since_clear = False
                # End of the occupancy cycle — any manual override has served its
                # purpose (a forced-occupied room held through the session; a
                # forced-clear room is now genuinely clear). Return to automatic
                # so a stale override can never strand the room permanently.
                if self._manual_override is not None:
                    _LOGGER.info(
                        "[%s] Manual override '%s' released (room cycled to CLEAR)",
                        self.config.get(CONF_ROOM_NAME), self._manual_override,
                    )
                    self._manual_override = None
                _LOGGER.debug("[%s] → CLEAR (timeout expired)", self.config.get(CONF_ROOM_NAME))
                await self.async_request_refresh()

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_diagnostic_data(self) -> dict[str, Any]:
        """Return internal coordinator state for the diagnostics endpoint.

        Exposes private fields that are not visible in the public entity
        attributes but are essential for debugging presence issues (e.g.
        why lock-in did not arm, how long a clear-pending has been running).
        """
        now = time.time()
        return {
            "sm_state": self._sm_state,
            "score": self._score,
            "active_sources": self._active_sources,
            "occupied_since": self._occupied_since,
            "occupied_since_age_s": round(now - self._occupied_since, 1) if self._occupied_since else None,
            # Lock-in state
            "has_been_solid": self._has_been_solid,
            "solid_candidate_since": self._solid_candidate_since,
            "solid_candidate_age_s": round(now - self._solid_candidate_since, 1) if self._solid_candidate_since else None,
            # Entry-gate state
            "disable_door_entry": self.config.get(CONF_DISABLE_DOOR_ENTRY, False),
            "entry_gate_default_on": self.config.get(CONF_HAS_DOOR, False),
            "door_opened_since_clear": self._door_opened_since_clear,
            "entry_gate_blocks": self._entry_gate_blocks(),
            # Clear-pending state
            "clear_pending_start": self._clear_pending_start,
            "clear_pending_timeout": self._clear_pending_timeout,
            "clear_pending_elapsed_s": round(now - self._clear_pending_start, 1) if self._clear_pending_start else None,
            # Overrides / mode
            "manual_override": self._manual_override,
            "sleep_mode_active": self._sleep_mode_active(),
            "was_occupied": self._was_occupied,
            # Recent event timestamps (epoch)
            "last_events": dict(self._last_event),
            # Last 10 events for the LLM / debug log
            "event_log_last_10": list(self._event_log[-10:]),
            # LLM gating — total events vs. last count seen by an LLM call.
            # If these are equal and llm_last_called is old, the room is simply
            # idle; if event_total keeps growing without llm_last_called moving,
            # the LLM batch is not running.
            "event_total": self._event_total,
            "llm_last_event_count": self._llm_last_event_count,
            "llm_last_called": self._llm_last_called,
            "llm_last_called_age_s": round(now - self._llm_last_called, 1) if self._llm_last_called else None,
            "llm_provider": self.llm_provider(),
            "llm_backend_key": self.llm_backend_key(),
            "uptime_now": now,
        }

    # ------------------------------------------------------------------
    # LLM advisory — called by llm_batch.py, not directly
    # ------------------------------------------------------------------

    def llm_provider(self) -> str:
        """Return the configured LLM backend: 'conversation' or 'http'."""
        return self.config.get(CONF_LLM_PROVIDER, DEFAULT_LLM_PROVIDER)

    def llm_enabled(self) -> bool:
        """Return True if a usable LLM backend is configured for this room."""
        if not self.config.get(CONF_LLM_ENABLED):
            return False
        if self.llm_provider() == LLM_PROVIDER_HTTP:
            # Direct HTTP needs at least a base URL and a model
            return bool(self.llm_base_url() and self.llm_model())
        return bool(self.config.get(CONF_CONVERSATION_AGENT))

    def llm_agent_id(self) -> str | None:
        return self.config.get(CONF_CONVERSATION_AGENT)

    def llm_base_url(self) -> str:
        return (self.config.get(CONF_LLM_BASE_URL) or DEFAULT_LLM_BASE_URL).rstrip("/")

    def llm_api_key(self) -> str:
        return self.config.get(CONF_LLM_API_KEY) or ""

    def llm_model(self) -> str:
        return self.config.get(CONF_LLM_MODEL) or DEFAULT_LLM_MODEL

    def llm_backend_key(self) -> str:
        """Stable key identifying the backend, so rooms sharing it batch together.

        Rooms with the same backend are sent in a single LLM call. For HTTP the
        key includes endpoint + model (not the api key) so distinct endpoints
        don't get merged into one request.
        """
        if self.llm_provider() == LLM_PROVIDER_HTTP:
            return f"http|{self.llm_base_url()}|{self.llm_model()}"
        return f"conversation|{self.llm_agent_id()}"

    def llm_update_interval(self) -> int:
        return int(self.config.get(CONF_LLM_UPDATE_INTERVAL, DEFAULT_LLM_UPDATE_INTERVAL))

    def needs_llm_update(self) -> bool:
        """True if this room should be included in the next batch LLM call."""
        if not self.llm_enabled():
            return False
        never_called = self._llm_last_called == 0.0
        new_events = self._event_total > self._llm_last_event_count
        time_elapsed = (time.time() - self._llm_last_called) >= self.llm_update_interval()
        return (never_called or new_events) and time_elapsed

    def llm_snapshot(self) -> dict:
        """Return anonymised room data for inclusion in a batch LLM prompt."""
        now = time.time()
        events_text = "\n".join(
            f"  - {e['type']}: {int(now - e['ts'])}s ago"
            for e in self._event_log[-20:]
        ) or "  (no events recorded)"
        return {
            "room_name": self.config.get(CONF_ROOM_NAME, "room"),
            "has_door": self.config.get(CONF_HAS_DOOR, True),
            "is_transit": self.config.get(CONF_IS_TRANSIT, False),
            "events_text": events_text,
            "rule_score": self._score,
            "rule_state": self._sm_state,
            # Current active signals — sensors that are on RIGHT NOW (not just historically)
            "active_sources": ", ".join(self._active_sources) if self._active_sources else "none",
            "rule_reason": self._reason or "No active signals",
        }

    def mark_llm_called(self) -> None:
        """Record that this room was included in a batch LLM call."""
        self._llm_last_called = time.time()
        self._llm_last_event_count = self._event_total

    def apply_llm_result(self, data: dict) -> None:
        """Apply a parsed LLM result dict to this room's LLM state."""
        try:
            self._llm_data = {
                "occupied": bool(data.get("occupied", False)),
                "score": max(0, min(100, int(data.get("score", 0)))),
                "confidence": str(data.get("confidence", "low")),
                "reason": str(data.get("reason", "")),
                "last_updated": datetime.now(tz=timezone.utc).isoformat(),
            }
            _LOGGER.debug("[%s] LLM result applied: %s", self.config.get(CONF_ROOM_NAME), self._llm_data)
        except (ValueError, TypeError) as err:
            _LOGGER.warning("[%s] LLM result parse error: %s", self.config.get(CONF_ROOM_NAME), err)

    # ------------------------------------------------------------------
    # Data output
    # ------------------------------------------------------------------

    def set_override(self, state: str | None) -> None:
        """Set manual override: 'occupied', 'clear', or None to reset."""
        self._manual_override = state
        _LOGGER.info("[%s] Manual override set to: %s", self.config.get(CONF_ROOM_NAME), state)

    def _release_clear_override(self, evidence: str) -> None:
        """Auto-release a manual 'clear' override on fresh entry evidence.

        A clear-override says "treat this room as empty" — but a door opening,
        new motion, a BLE arrival, a counted person, or a human flipping a light
        on is positive proof someone (re-)entered, so the override is stale and
        must not suppress real presence (observed: a stray dashboard tap forced
        a room clear and the lights kept switching off on the actual occupant).
        Overrides in either direction are additionally released when the room
        cycles back to CLEAR (see _async_clear_after_timeout).
        """
        if self._manual_override == "clear":
            self._manual_override = None
            _LOGGER.info(
                "[%s] Manual clear-override released (%s)",
                self.config.get(CONF_ROOM_NAME), evidence,
            )

    def _build_data(self) -> dict[str, Any]:
        occupied = self._sm_state in SM_OCCUPIED_STATES

        # Apply manual override
        if self._manual_override == "occupied":
            occupied = True
        elif self._manual_override == "clear":
            occupied = False

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

        # Fire HA event when occupied state changes
        if self._was_occupied is not None and occupied != self._was_occupied:
            self.hass.bus.async_fire(f"{DOMAIN}_state_changed", {
                "room_name": self.config.get(CONF_ROOM_NAME, ""),
                "room_slug": self.room_slug,
                "entry_id": self.entry.entry_id,
                "occupied": occupied,
                "score": self._score,
                "confidence": confidence,
                "reason": self._reason,
                "state_machine": self._sm_state,
                "manual_override": self._manual_override,
            })
        self._was_occupied = occupied

        return {
            # Rule engine
            "occupied": occupied,
            "score": self._score,
            "confidence": confidence,
            "reason": self._reason,
            "active_sources": self._active_sources,
            "state_machine": self._sm_state,
            "last_positive": last_positive,
            "last_positive_reason": self._last_positive_reason,
            "last_positive_sources": self._last_positive_sources,
            "timeout_remaining": timeout_remaining,
            "room_name": self.config.get(CONF_ROOM_NAME, ""),
            "manual_override": self._manual_override,
            "sleep_mode_active": self._sleep_mode_active(),
            # Sensor diagnostics — all configured sensors with current state
            "sensors": self._build_sensor_diagnostics(),
            # LLM advisory
            "llm_enabled": bool(self.config.get(CONF_LLM_ENABLED)),
            "llm": self._llm_data,
        }

    def _build_sensor_diagnostics(self) -> dict:
        """Return all configured sensors grouped by category with their current HA state."""
        cfg_sensors = self.config.get("sensors", {})

        def _states(entity_ids: list[str]) -> dict[str, str]:
            result = {}
            for eid in entity_ids:
                st = self.hass.states.get(eid)
                result[eid] = st.state if st else "unavailable"
            return result

        # Merge legacy workstation keys
        ws_ids = (
            cfg_sensors.get(CONF_WORKSTATION_SENSORS, [])
            + cfg_sensors.get(CONF_WORKSTATION_ENTITIES, [])
            + cfg_sensors.get(CONF_WORKSTATION_POWER_SENSORS, [])
        )

        categories = {
            "mmwave":        cfg_sensors.get(CONF_MMWAVE_SENSORS, []),
            "pir":           cfg_sensors.get(CONF_PIR_SENSORS, []),
            "espresense":    cfg_sensors.get(CONF_ESPRESENSE_SENSORS, []),
            "person_count":  cfg_sensors.get(CONF_PERSON_COUNT_SENSORS, []),
            "door":          cfg_sensors.get(CONF_DOOR_SENSORS, []),
            "window":        cfg_sensors.get(CONF_WINDOW_SENSORS, []),
            "lock":          cfg_sensors.get(CONF_LOCK_ENTITIES, []),
            "media":         cfg_sensors.get(CONF_MEDIA_PLAYERS, []),
            "lights":        cfg_sensors.get(CONF_LIGHT_ENTITIES, []),
            "switches":      cfg_sensors.get(CONF_SWITCH_ENTITIES, []),
            "workstation":   list(dict.fromkeys(ws_ids)),  # deduplicate
            "sleep_mode":    self.config.get(CONF_SLEEP_MODE_ENTITIES, []),
        }

        return {
            cat: _states(ids)
            for cat, ids in categories.items()
            if ids  # omit empty categories
        }
