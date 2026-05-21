# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versions follow `YYYY.M.D` (Home Assistant style).

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

[2026.5.21]: https://github.com/SkyTechNerds/ha-soft-presence/compare/2026.4.28...2026.5.21
[2026.4.28]: https://github.com/SkyTechNerds/ha-soft-presence/releases/tag/2026.4.28
