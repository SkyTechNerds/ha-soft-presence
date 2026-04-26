# HA Soft Presence

**Virtual presence sensors for Home Assistant** — inspired by the Aqara Presence Soft Sensor concept, but fully transparent, fully local, and fully configurable.

Instead of relying on a single sensor, HA Soft Presence combines multiple signals (mmWave, PIR, door contacts, media players, workstations, lights, …) using a weighted score engine and a 6-state machine to produce a stable, automation-ready occupancy decision per room.

---

## Features

- **4 entities per room**: binary occupancy + score + confidence + reason
- **Sensor fusion**: mmWave, PIR, PIR decay, media player, workstation, lights, door contacts, locks
- **6-state machine**: `clear → possible_entry → occupied → likely_occupied → possible_exit → clear_pending → clear`
- **Hysteresis**: separate occupied/clear thresholds — no flickering
- **Configurable timeout** per room (no-presence delay before going clear)
- **Reason string**: human-readable explanation — e.g. `"mmWave active + Media playing"`
- **Optional LLM advisory** (via HA AI / Gemini / OpenAI) — off by default, no data sent externally
- **Config UI**: full multi-step setup in Home Assistant UI, no YAML required
- **Options flow**: edit thresholds after setup without reconfiguring sensors

---

## Entities created per room

| Entity | Example | Description |
|--------|---------|-------------|
| `binary_sensor.{room}_presence_soft` | `binary_sensor.wohnzimmer_presence_soft` | on = occupied, off = clear |
| `sensor.{room}_presence_score` | `sensor.wohnzimmer_presence_score` | Score 0–100 |
| `sensor.{room}_presence_confidence` | `sensor.wohnzimmer_presence_confidence` | `high` / `medium` / `low` |
| `sensor.{room}_presence_reason` | `sensor.wohnzimmer_presence_reason` | `"mmWave active + Media playing"` |

### Attributes on `binary_sensor.{room}_presence_soft`

```yaml
presence_score: 78
confidence: high
reason: "mmWave active + Media playing"
active_sources:
  - mmwave
  - media_playing
state_machine: occupied
last_positive_signal: "2026-04-24T22:33:00+00:00"
timeout_remaining: 210
room_name: Wohnzimmer
```

---

## Score weights

| Signal | Weight | Notes |
|--------|-------:|-------|
| mmWave active | +80 | Strongest signal — detects still persons |
| PIR active | +35 | Real-time |
| PIR recent (decay) | up to +15 | Fades over 5 min after PIR goes off |
| Media playing | +30 | Media player in "playing" state |
| Media paused | +15 | |
| Workstation active | +35 | Binary sensor or power > 10 W |
| Light manually on | +20 | Any configured light/switch on |
| Door recently opened | up to +10 | Decays over 5 min |
| Lock recently unlocked | up to +15 | Decays over 10 min |

> Score ≥ `occupied_threshold` (default 50) → OCCUPIED  
> Score ≤ `clear_threshold` (default 20) → start no-presence timeout  
> Between thresholds → hold current state (hysteresis)

---

## State machine

```
CLEAR
  ↓  (score in hysteresis zone)
POSSIBLE_ENTRY
  ↓  (score ≥ occupied_threshold)
OCCUPIED
  ↓  (score ≤ clear_threshold, after min_hold_time)
CLEAR_PENDING  ←→  OCCUPIED (if score recovers)
  ↓  (timeout expires, no contradicting signal)
CLEAR
```

A door closing alone does **not** trigger CLEAR — it is a context signal, not proof.

---

## Installation

### Via HACS (recommended)

1. Open HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/SkyTechNerds/ha-soft-presence` as **Integration**
3. Install **HA Soft Presence**
4. Restart Home Assistant

### Manual

1. Copy `custom_components/ha_soft_presence/` to your HA config directory
2. Restart Home Assistant

---

## Setup

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **HA Soft Presence**
3. Follow the 4-step wizard:
   - **Step 1**: Room name, type, has door, is transit room
   - **Step 2**: Select mmWave and PIR sensors
   - **Step 3**: Select context sensors (doors, locks, media, workstation, lights)
   - **Step 4**: Thresholds and optional LLM

Repeat to add more rooms.

---

## Supported sensor types

| Category | What to select |
|----------|---------------|
| mmWave | DFRobot SEN0395, FP2, LD2410, EP1, Everything Presence One, ESPresense zones |
| PIR | Any `binary_sensor` with device class `motion` or `occupancy` |
| Door contacts | `binary_sensor` with device class `door` |
| Window contacts | `binary_sensor` with device class `window` |
| Locks | Any `lock` entity |
| Media players | Any `media_player` entity |
| Lights | Any `light` entity |
| Switches | Any `switch` entity |
| Workstation (binary) | `binary_sensor` for PC online (e.g. ping, NetDaemon) |
| Workstation (power) | `sensor` with device class `power` (W) — active when > 10 W |

---

## Room type presets

| Type | Typical sensors | Notes |
|------|----------------|-------|
| Office / Büro | mmWave + workstation | PC activity is strong indicator |
| Bedroom / Schlafzimmer | PIR × 2 + bed sensors + door | No mmWave needed; bed pressure sensors map to PIR slots |
| Living room | mmWave + PIR + media | TV/speaker strong context |
| Hallway | PIR only | Short timeout, transit = true |
| Bathroom | PIR + door | No media/workstation |

---

## LLM Advisory (optional, off by default)

When enabled, the LLM is **not** used for real-time decisions. It is available for:

- Explaining why a room was marked occupied/clear at a specific time
- Suggesting threshold tuning based on logs
- Identifying false-positive patterns

Privacy defaults:
- LLM off by default
- No camera data sent
- Only aggregated events sent (type + age in seconds, no names)
- Opt-in per room

Supported providers: **HA AI (Gemini, Ollama, …)**, OpenAI, Google Gemini direct

---

## Design rules

1. Door closing ≠ vacant — door is context only
2. mmWave is highest-weight and overrides PIR
3. `occupied` is set fast; `clear` is set slowly (timeout + hysteresis)
4. Bed sensors → use the PIR sensor slots (they are binary on/off)
5. Separate thresholds for different room types (bedroom needs lower clear threshold)
6. All processing is local — nothing leaves HA unless LLM is explicitly enabled

---

## Roadmap

| Feature | Status | Notes |
|---------|--------|-------|
| Camera / Frigate support | planned | Dedicated sensor slot for Frigate person-detection binary sensors; own score weight (~65) distinct from PIR |
| Camera snapshot + Vision LLM | planned | Send camera snapshot to vision-capable LLM for room analysis; opt-in, privacy-first |
| Area auto-fill (UI) | ✅ done | Entity selectors pre-filled from matching HA area on setup |
| LLM initial evaluation | ✅ done | LLM runs once on startup, not only on new sensor events |
| Multi-language (DE/EN) | ✅ done | Full translation of UI steps and entity names |
| Options flow | ✅ done | Full reconfiguration without deleting the integration |

---

## License

MIT — private use, no warranty.
