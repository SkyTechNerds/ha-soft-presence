# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versions follow `YYYY.M.D` (Home Assistant style).

## [2026.6.26.1] — 2026-06-26

### Added

- **`ha_soft_presence.toggle_override` service.** Flips a room's manual override
  based on its current effective state — occupied → clear, otherwise → occupied
  — in a single call. Sticky like the other overrides (`reset_override` returns
  to automatic detection). Intended for a one-tap dashboard tile that manually
  marks a room free/occupied, replacing the old `input_boolean.toggle` pattern
  that no longer works now that presence is a read-only `binary_sensor`.

## [2026.6.26] — 2026-06-26

### Changed

- **A `paused` media player with `device_class: speaker` no longer counts as
  presence.** Voice-assistant satellites (e.g. Home Assistant Voice) sit in
  `paused` as their permanent idle state, which kept a room occupied forever.
  `paused` is now ignored for `speaker` devices; `playing` still counts (active
  music is a real, transient signal), and TVs/receivers are unaffected. A
  blacklist (skip `speaker`) is used rather than a whitelist (`tv`/`receiver`)
  because many video players report no `device_class` at all (e.g. Apple TV via
  pyatv) and must keep counting.

### Fixed

- **Translation parity across all locales.** Added the `issues.*` repair
  strings (3 messages) to all 11 locales and the missing `espresense_sensors`
  label to the non-German ones, so every locale now matches `en.json` (no more
  English fallback in the Repairs dialog / BLE-sensor field).
- **Config-entry edits now apply live (no manual reload).** The options flow
  writes changes (sensor lists, thresholds, LLM settings, …) to `entry.data`,
  but no update listener was registered — so the running coordinator kept the
  old config until the entry was reloaded by hand. Example: a media player
  removed from a room still counted toward presence (a permanently "paused"
  voice satellite kept the room occupied). Added
  `entry.add_update_listener` → the entry reloads on any config change and the
  coordinator rebuilds with the new config immediately.

## [2026.6.22.3] — 2026-06-24

### Fixed

- **A light left on no longer keeps an empty room OCCUPIED (feedback loop).**
  `WEIGHT_LIGHT_MANUAL` was `20`, exactly equal to `DEFAULT_CLEAR_THRESHOLD`
  (20), so a manually-on light pinned the score at the clear threshold and the
  room never cleared (`reason: "Light on"`). With lighting automations now
  driven by `*_presence_soft`, that meant: light on → room "occupied" →
  automation keeps the light on → score stays 20 → never clears; and turning
  the light off by hand let the still-"occupied" room switch it back on shortly
  after. Lowered `WEIGHT_LIGHT_MANUAL` to `10` (strictly below the clear
  threshold), so a lit light is still a weak hint but can no longer hold a room
  on its own. Real presence (mmWave/PIR/BLE) is unaffected. Observed in
  Badezimmer (held at score 20, "Light on") and Wohnzimmer.

## [2026.6.22.2] — 2026-06-22

### Fixed

- **Translations for the new config options (all languages).** The entry-gate
  field (`require_door_entry`) and the Direct-HTTP provider fields
  (`llm_provider`, `llm_base_url`, `llm_api_key`, `llm_model`) were English-only
  (the locale files predated those features). German got full labels +
  descriptions; the other 11 locales (bg/es/fr/it/nl/pl/pt/ru/sv) got the new
  field labels in config and options flow.

## [2026.6.22.1] — 2026-06-22

### Fixed

- **`slugify` transliterates German umlauts** instead of replacing them with
  `_`. Room names with ä/ö/ü/ß now produce readable entity IDs:
  „Küche" → `kueche` (was `k_che`), „Gästezimmer" → `gaestezimmer`
  (was `g_stezimmer`). ä→ae, ö→oe, ü→ue, ß→ss. Rooms without umlauts are
  unchanged. Existing entities keep their old IDs until renamed in the entity
  registry (the per-entity `unique_id` is `entry_id`-based and unaffected).

## [2026.6.22] — 2026-06-22

### Fixed

- **Entry-gate no longer suppresses real, proven presence.** The gate trusted
  that *every* door-open is captured. In practice a door sensor can miss an
  open (Zigbee glitch), or the door is left open to air the room and the
  occupant walks in and closes it behind them — in both cases no open-event
  fires, so the gate wrongly suppressed the occupant. Observed: an office
  showed CLEAR for ~83 min while BLE placed the phone in the room and mmWave
  fired continuously, reason logged `(suppressed: no door entry)` the whole
  time, until the door finally registered an open. `_entry_gate_blocks()` now
  has two additional exemptions:
  - **Door currently open** → free access, presence is plausible without a
    captured open-transition; the gate stands down.
  - **Strong presence signal active** → a BLE device located in the room or a
    person-count sensor > 0 is positive proof of a specific person/headcount
    and is never suppressed. Only ambiguous motion (PIR/mmWave) is still gated,
    preserving the anti-false-positive value for noisy motion sensors.

## [2026.6.19] — 2026-06-18

### Fixed

- **Entity restore after an HA restart no longer fakes events.** When HA
  restarts (or a device reconnects), tracked entities come back online via a
  `unavailable`/`unknown` → state transition. The coordinator treated such a
  transition like a real-world event — e.g. a door sensor restoring to `on`
  was logged as "door opened", which reset the lock-in, started the
  "door recently opened" score decay, and (with the new entry-gate) would
  spuriously lift the gate. `_on_entity_changed` now ignores transitions out
  of `None`/`unavailable`/`unknown` (it still refreshes so the live score is
  current). Observed: four door rooms all showing `score=6, "Door recently
  opened"` simultaneously right after a restart although no door had moved.

### Added

- **Door entry-gate** (opt-in per room, `require_door_entry`, default off). For a
  room with door contacts, presence signals (PIR/mmWave/…) may only mark the room
  OCCUPIED if a door has opened since the room was last CLEAR. A closed door that
  never opened proves nobody entered, so the signal is treated as a false trigger
  and the room stays CLEAR. This is the mirror image of the existing door-closed
  lock-in (which keeps a room occupied while the door stays closed):
  - **Lock-in:** door closed + was occupied → stays occupied.
  - **Entry-gate:** door closed + nobody entered → cannot become occupied.
  - **Fail-open at startup** — occupancy is allowed until the room has been
    observed CLEAR once (pre-startup history is unknown).
  - The gate only blocks *promotion* from clear; it never releases an
    already-occupied room (that remains the lock-in's job).
  - When a signal is suppressed, the reason string shows
    `… (suppressed: no door entry)`.
  - Intended for single-door rooms with a reliable door contact. Diagnostics
    expose `require_door_entry`, `door_opened_since_clear`, and
    `entry_gate_blocks`.

## [2026.6.18] — 2026-06-18

### Added

- **Direct HTTP AI provider** (roadmap item). The LLM advisory can now call any
  OpenAI-compatible `/chat/completions` endpoint directly — no Home Assistant
  conversation agent required. New per-room config options under LLM Advisory:
  - **Provider** — `HA conversation agent` (default, unchanged) or `Direct HTTP`.
  - **API Base URL** / **API Key** / **Model** for the HTTP provider
    (defaults: `https://api.minimax.io/v1`, model `MiniMax-M3`).
  This enables flat-rate / prompt-quota backends like **MiniMax** as a drop-in
  replacement when a per-token agent (e.g. Gemini) hits a spending cap.
- The batch builder now groups rooms by **backend** (conversation agent *or*
  HTTP endpoint+model) instead of conversation agent only — rooms sharing a
  backend are still sent in a single call, preserving the one-call-for-all-rooms
  efficiency that matters for prompt-quota billing.
- Response parsing is hardened for reasoning models: `<think>…</think>` blocks
  and ```` ```json ```` code fences are stripped before extracting the JSON
  array (MiniMax-M3 emits both).
- Diagnostics now report `llm_provider` and `llm_backend_key`. The HTTP
  `api_key` is redacted in the diagnostics dump.

## [2026.6.17] — 2026-06-17

### Fixed

- **LLM advisory silently stopped updating after ~30 sensor events.**
  `needs_llm_update()` detected new activity by comparing
  `len(self._event_log)` against the count recorded at the last LLM call.
  But `_event_log` is capped at `_MAX_EVENT_LOG` (30), so once a room had
  logged 30 events its length saturated at 30. After the next
  `mark_llm_called()` stored `30`, the check became `30 > 30 == False`
  permanently — the room was never again included in a batch LLM call, and
  its four AI entities froze at their last value. Because no call was made,
  nothing appeared in the log; the failure was invisible. In a 4-room test
  setup all rooms froze within a day of setup.
- Introduced a monotonic `_event_total` counter (incremented on every
  recorded event, never reset, never capped). `needs_llm_update()` and
  `mark_llm_called()` now compare/store `_event_total` instead of the
  capped list length, so the "new events" check keeps working for the life
  of the integration.

### Added

- Diagnostics now expose `event_total`, `llm_last_event_count`,
  `llm_last_called`, and `llm_last_called_age_s` so a stalled LLM advisory
  is diagnosable from the Download Diagnostics dump.

## [2026.5.23] — 2026-05-22

### Added

- **`diagnostics.py`** — Download Diagnostics button now appears on the
  integration's device page. The dump includes the (redacted) config
  entry, the current coordinator output, and internal debug state
  (`_has_been_solid`, `_in_clear_pending`, event log, etc.).
- **Repair Issues** (`repairs.py`) — three actionable warnings now surface
  in Settings → System → Repairs:
  1. *No presence sensors* — room can never reach the occupied threshold.
  2. *has_door without door contact* — door-closed lock-in silently
     disabled because no door contact is configured.
  3. *Missing entities* — lists up to five entity IDs that are configured
     but not found in HA's state machine (removed, renamed, or not yet
     loaded).
  Issues are re-evaluated on every integration load and cleared on unload.
- **Config-entry `unique_id`** — set to the room slug (e.g. `wohnzimmer`)
  on first setup. Prevents creating a duplicate room entry with the same
  name.
- **README roadmap** — marked Diagnostics, Repairs / Issues, and Entity
  unique_id as ✅ done; clarified `iot_class = local_push`.

## [2026.5.22] — 2026-05-22

### Fixed

- **Icon now displayed in HACS overview and HA update view.** The `brand/`
  folder already contained `icon.png` but was missing `icon@2x.png`
  (512×512). Since HA 2026.3 custom integrations serve their own brand
  images directly from `brand/` — no external brands-repo PR needed.
  Added `icon@2x.png` (LANCZOS upscale). Logo files were intentionally
  omitted due to gradient artefacts; `icon.png` + `icon@2x.png` are
  sufficient for all HA and HACS display contexts.

## [2026.5.21] — 2026-05-21

### Fixed

- **Door-closed lock-in no longer fast-clears the room.**
  `_effective_clear_timeout` had inverted semantics: if the door had not
  opened since the room became OCCUPIED, the no-presence timeout was
  shortened to 30 s (`DEFAULT_DOOR_VALIDATED_TIMEOUT`). Logically, a
  closed door that never opened proves the occupant is still inside, so
  the timeout should be longer. Sitting still at a desk with the door
  closed would clear the room after 30 s.

### Changed

- Replaced the brittle "door never opened since OCCUPIED" check with a
  **solid-streak flag** (`_has_been_solid`). The flag is armed once the
  room has been continuously above the occupied threshold AND all doors
  closed for `DOOR_LOCK_SOLID_DURATION` seconds (default 120 s). A score
  dip with doors still closed no longer drops the flag — that is exactly
  the situation lock-in is meant to bridge. A door-open event or the
  OCCUPIED → CLEAR transition resets it.
- A brief visit by another person (door opens, visitor talks, leaves,
  door closes) now correctly re-engages lock-in once the streak rebuilds
  (≈ 2 min after the door closes again), instead of permanently disabling
  it for the rest of the session.
- When lock-in is armed AND every configured door is currently closed,
  the no-presence timeout is extended to 4 h
  (`DEFAULT_DOOR_LOCKED_IN_TIMEOUT`) as a sanity cap against a stuck
  door sensor.
- Renamed constant `DEFAULT_DOOR_VALIDATED_TIMEOUT` →
  `DEFAULT_DOOR_LOCKED_IN_TIMEOUT`. New constant
  `DOOR_LOCK_SOLID_DURATION`.

### Added

- `.gitignore` covering `__pycache__/`.

## [2026.4.28] — 2026-04-28

### Added

- Initial release: sensor fusion, state machine, batch LLM advisory,
  door-validated fast clear, 11 languages, HACS support.

[2026.6.26.1]: https://github.com/SkyTechNerds/ha-soft-presence/compare/2026.6.26...2026.6.26.1
[2026.6.26]: https://github.com/SkyTechNerds/ha-soft-presence/compare/2026.6.22.3...2026.6.26
[2026.6.22.3]: https://github.com/SkyTechNerds/ha-soft-presence/compare/2026.6.22.2...2026.6.22.3
[2026.6.22.2]: https://github.com/SkyTechNerds/ha-soft-presence/compare/2026.6.22.1...2026.6.22.2
[2026.6.22.1]: https://github.com/SkyTechNerds/ha-soft-presence/compare/2026.6.22...2026.6.22.1
[2026.6.22]: https://github.com/SkyTechNerds/ha-soft-presence/compare/2026.6.19...2026.6.22
[2026.6.19]: https://github.com/SkyTechNerds/ha-soft-presence/compare/2026.6.18...2026.6.19
[2026.6.18]: https://github.com/SkyTechNerds/ha-soft-presence/compare/2026.6.17...2026.6.18
[2026.6.17]: https://github.com/SkyTechNerds/ha-soft-presence/compare/2026.5.23...2026.6.17
[2026.5.23]: https://github.com/SkyTechNerds/ha-soft-presence/compare/2026.5.22...2026.5.23
[2026.5.22]: https://github.com/SkyTechNerds/ha-soft-presence/compare/2026.5.21...2026.5.22
[2026.5.21]: https://github.com/SkyTechNerds/ha-soft-presence/compare/2026.4.28...2026.5.21
[2026.4.28]: https://github.com/SkyTechNerds/ha-soft-presence/releases/tag/2026.4.28
