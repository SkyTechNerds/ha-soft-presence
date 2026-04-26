# HA Soft Presence

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=flat-square)](https://github.com/hacs/integration)
![GitHub release (latest by date)](https://img.shields.io/github/v/release/SkyTechNerds/ha-soft-presence?style=flat-square)
![GitHub commit activity](https://img.shields.io/github/commit-activity/m/SkyTechNerds/ha-soft-presence?style=flat-square&color=brightgreen)
![License](https://img.shields.io/github/license/SkyTechNerds/ha-soft-presence?style=flat-square)

**Virtual presence sensors for Home Assistant** — inspired by the Aqara Presence Soft Sensor concept, but fully transparent, fully local, and fully configurable.

Instead of relying on a single sensor, HA Soft Presence combines multiple signals (mmWave, PIR, door contacts, media players, workstations, lights, …) using a weighted score engine and a 6-state machine to produce a stable, automation-ready occupancy decision per room.

---

## ✨ Features

- 🏠 **8 entities per room** — binary occupancy, score, confidence, reason, plus 4 optional AI advisory entities
- 🔀 **Sensor fusion** — mmWave, PIR, media player, workstation, lights, door contacts, locks
- 🔄 **6-state machine** — `clear → possible_entry → occupied → clear_pending → clear`
- 📊 **Hysteresis** — separate occupied/clear thresholds, no flickering
- 🌙 **Sleep mode** — configurable entities raise the clear threshold at night
- ⏱️ **Configurable timeout** per room before going clear
- 💬 **Reason string** — human-readable explanation, e.g. `"mmWave active + Media playing"`
- 📡 **HA Events** — fires `ha_soft_presence_state_changed` on every transition
- 🛠️ **Service calls** — `force_occupied`, `force_clear`, `reset_override` per room
- 🤖 **Optional AI advisory** — via Gemini, Ollama, OpenAI — off by default, fully local
- 📍 **Area auto-fill** — entity selectors pre-filled from matching HA area on setup
- 🖥️ **Config UI** — full multi-step setup, no YAML required
- 🌍 **11 languages** — EN, DE, FR, ES, IT, NL, PL, PT, SV, RU, BG

---

## 🚀 Installation

### Via HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=SkyTechNerds&repository=ha-soft-presence&category=integration)

1. Click the button above **or** open HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/SkyTechNerds/ha-soft-presence` as **Integration**
3. Install **HA Soft Presence**
4. Restart Home Assistant

### Manual

1. Copy `custom_components/ha_soft_presence/` to your HA config directory
2. Restart Home Assistant

---

## ⚙️ Setup

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=ha_soft_presence)

1. Click the button above **or** go to **Settings → Devices & Services → Add Integration**
2. Search for **HA Soft Presence**
3. Follow the 5-step wizard:
   - **Step 1** — Room name, has door, is transit room
   - **Step 2** — mmWave & PIR sensors *(pre-filled from matching HA area)*
   - **Step 3** — Context sensors: doors, windows, locks, media, lights, switches, workstation *(pre-filled)*
   - **Step 4** — Thresholds, timeout, sleep mode entities
   - **Step 5** — Optional AI advisory

Repeat to add more rooms.

---

## 🏷️ Entities created per room

### Rule engine (always)

| Entity | Example | Description |
|--------|---------|-------------|
| `binary_sensor.{room}_presence_soft` | `binary_sensor.wohnzimmer_presence_soft` | `on` = occupied, `off` = clear |
| `sensor.{room}_presence_score` | `sensor.wohnzimmer_presence_score` | Score 0–100 |
| `sensor.{room}_presence_confidence` | `sensor.wohnzimmer_presence_confidence` | `high` / `medium` / `low` |
| `sensor.{room}_presence_reason` | `sensor.wohnzimmer_presence_reason` | `"mmWave active + Media playing"` |

### AI advisory (optional)

| Entity | Example | Description |
|--------|---------|-------------|
| `binary_sensor.{room}_presence_llm` | `binary_sensor.wohnzimmer_presence_llm` | AI occupancy estimate |
| `sensor.{room}_presence_llm_score` | `sensor.wohnzimmer_presence_llm_score` | AI score 0–100 |
| `sensor.{room}_presence_llm_confidence` | `sensor.wohnzimmer_presence_llm_confidence` | AI confidence |
| `sensor.{room}_presence_llm_reason` | `sensor.wohnzimmer_presence_llm_reason` | AI explanation |

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
manual_override: null        # "occupied" | "clear" | null
sleep_mode_active: false
```

---

## ⚖️ Score weights

| Signal | Weight | Notes |
|--------|-------:|-------|
| mmWave active | +80 | Strongest signal — detects still persons |
| PIR active | +35 | Real-time motion |
| PIR recent (decay) | up to +15 | Fades over 5 min after PIR goes off |
| Workstation active | +35 | Binary sensor or power > 10 W |
| Media playing | +30 | Media player in "playing" state |
| Media paused | +15 | |
| Light manually on | +20 | Any configured light/switch on |
| Lock recently unlocked | up to +15 | Decays over 10 min |
| Door recently opened | up to +10 | Decays over 5 min |

> Score ≥ `occupied_threshold` (default 50) → **OCCUPIED**
> Score ≤ `clear_threshold` (default 20) → start no-presence timeout
> Between thresholds → hold current state (hysteresis)
> Sleep mode active → `clear_threshold` replaced by `sleep_clear_threshold` (default 5)

---

## 🔁 State machine

```
CLEAR
  ↓  (score enters hysteresis zone)
POSSIBLE_ENTRY
  ↓  (score ≥ occupied_threshold)
OCCUPIED
  ↓  (score ≤ clear_threshold, after min_hold_time)
CLEAR_PENDING  ←→  OCCUPIED (if score recovers)
  ↓  (timeout expires, no contradicting signal)
CLEAR
```

> [!NOTE]
> A door closing alone does **not** trigger CLEAR — it is a context signal, not proof of absence.

---

## 🔌 Supported sensor types

| Category | What to select |
|----------|---------------|
| mmWave | DFRobot SEN0395, FP2, LD2410, EP1, Everything Presence One |
| PIR | Any `binary_sensor` with device class `motion` or `occupancy` |
| Door contacts | `binary_sensor` with device class `door` |
| Window contacts | `binary_sensor` with device class `window` |
| Locks | Any `lock` entity |
| Media players | Any `media_player` entity |
| Lights | Any `light` entity |
| Switches | Any `switch` entity |
| Workstation | `binary_sensor` (on/off) or `sensor` with device class `power` (W, active when > 10 W) |

---

## 🌙 Sleep mode

Configure one or more entities (e.g. `input_boolean.sleepmode_bedroom`, `group.sleepmode_all`) as sleep mode indicators. When any of them is `on`, the **clear threshold** is replaced by the much lower **sleep mode clear threshold** (default: 5).

This means the room stays occupied as long as bed sensors, PIR, or any other signal is above 5 — preventing false "clear" states while sleeping.

The `sleep_mode_active` attribute on the binary sensor reflects the current state.

---

## 📡 HA Events

On every occupied ↔ clear transition, HA Soft Presence fires:

```yaml
event_type: ha_soft_presence_state_changed
event_data:
  room_name: Wohnzimmer
  room_slug: wohnzimmer
  entry_id: abc123
  occupied: true
  score: 78
  confidence: high
  reason: "mmWave active"
  state_machine: occupied
  manual_override: null
```

Use in automations:

```yaml
triggers:
  - trigger: event
    event_type: ha_soft_presence_state_changed
    event_data:
      room_slug: wohnzimmer
      occupied: true
```

---

## 🛠️ Service calls

| Service | Description |
|---------|-------------|
| `ha_soft_presence.force_occupied` | Override room to occupied, ignore sensor signals |
| `ha_soft_presence.force_clear` | Override room to clear, ignore sensor signals |
| `ha_soft_presence.reset_override` | Remove override, return to automatic detection |

All services take the `entity_id` of the room's `binary_sensor.*_presence_soft` entity.

```yaml
actions:
  - action: ha_soft_presence.force_occupied
    data:
      entity_id: binary_sensor.arbeitszimmer_presence_soft
```

---

## 🤖 AI Advisory (optional, off by default)

When enabled, an AI analysis runs once on startup and then whenever new sensor events are recorded (respecting the configured minimum interval, default 5 min).

> [!NOTE]
> The AI receives only anonymised data: event type + age in seconds. No names, no images, no raw sensor values are sent externally.

Supported providers: any **HA conversation agent** (Gemini, Ollama, OpenAI, …)

AI entities show **"Waiting for evaluation"** until the first response arrives.

---

## 💡 Design principles

1. 🚪 Door closing ≠ vacant — door is context only, not proof of absence
2. 📡 mmWave is highest-weight and overrides PIR
3. ⚡ `occupied` is set fast; `clear` is set slowly (timeout + hysteresis)
4. 🛏️ Bed sensors → use the PIR sensor slots (binary on/off)
5. 🌙 Sleep mode keeps the room occupied longer with minimal configuration
6. 🔒 All processing is local — nothing leaves HA unless AI is explicitly enabled

---

## 🗺️ Roadmap

| Feature | Status | Notes |
|---------|--------|-------|
| 📶 ESPresense / BLE | planned | One sensor per tracked device (phone/watch); state = current room name string |
| 📷 Camera / Frigate support | planned | Frigate person-detection binary sensors; own score weight distinct from PIR |
| 🧠 Camera snapshot + Vision AI | planned | Send camera snapshot to vision-capable AI; opt-in, privacy-first |
| 🏘️ Room-level aggregation | planned | "Anyone home on floor 1?" aggregating multiple rooms |
| 🔧 HA Quality Scale — `iot_class` | planned | Set `local_polling` correctly in manifest |
| 🔧 HA Quality Scale — `diagnostics.py` | planned | Coordinator data dump for easier debugging in HA |
| 🔧 HA Quality Scale — Tests | planned | `pytest-homeassistant-custom-component` test suite |
| 🔧 HA Quality Scale — Repairs / Issues | planned | Surface config errors as actionable HA repair issues |
| 🔧 HA Quality Scale — Entity unique_id | planned | Stricter unique_id naming per HA guidelines |
| 🌙 Sleep mode | ✅ done | Configurable entities raise clear threshold when active |
| 📡 HA Events | ✅ done | `ha_soft_presence_state_changed` on every transition |
| 🛠️ Service calls | ✅ done | `force_occupied`, `force_clear`, `reset_override` |
| 📍 Area auto-fill | ✅ done | Entity selectors pre-filled from matching HA area |
| 🤖 AI initial evaluation | ✅ done | AI runs once on startup |
| 🌍 Multi-language (11 languages) | ✅ done | EN, DE, FR, ES, IT, NL, PL, PT, SV, RU, BG |
| ⚙️ Options flow | ✅ done | Full reconfiguration without deleting the integration |

---

## 📄 License

MIT — free to use, no warranty.
