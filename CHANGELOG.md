# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versions follow `YYYY.M.D` (Home Assistant style).

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

[2026.6.17]: https://github.com/SkyTechNerds/ha-soft-presence/compare/2026.5.23...2026.6.17
[2026.5.23]: https://github.com/SkyTechNerds/ha-soft-presence/compare/2026.5.22...2026.5.23
[2026.5.22]: https://github.com/SkyTechNerds/ha-soft-presence/compare/2026.5.21...2026.5.22
[2026.5.21]: https://github.com/SkyTechNerds/ha-soft-presence/compare/2026.4.28...2026.5.21
[2026.4.28]: https://github.com/SkyTechNerds/ha-soft-presence/releases/tag/2026.4.28
