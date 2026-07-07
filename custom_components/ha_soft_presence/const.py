"""Constants for HA Soft Presence."""

DOMAIN = "ha_soft_presence"

# ---------------------------------------------------------------------------
# Config keys — stored in config_entry.data
# ---------------------------------------------------------------------------

# Room basics
CONF_ROOM_NAME = "room_name"
CONF_HAS_DOOR = "has_door"
CONF_IS_TRANSIT = "is_transit"
# Entry gate: require a door-open since the room was last CLEAR before any
# presence signal may mark it occupied. For single-door rooms this rejects
# false PIR/mmWave triggers when physically nobody entered.
# The entry-gate is now ON BY DEFAULT for any room that has a door contact;
# CONF_DISABLE_DOOR_ENTRY is the per-room opt-out (e.g. an unreliable door
# sensor). CONF_REQUIRE_DOOR_ENTRY is the legacy opt-in key, kept only so old
# config entries still load — it no longer influences the gate.
CONF_REQUIRE_DOOR_ENTRY = "require_door_entry"
CONF_DISABLE_DOOR_ENTRY = "disable_door_entry"

# Threshold & timing
CONF_OCCUPIED_THRESHOLD = "occupied_threshold"
CONF_CLEAR_THRESHOLD = "clear_threshold"
CONF_NO_PRESENCE_TIMEOUT = "no_presence_timeout"
CONF_MIN_HOLD_TIME = "min_hold_time"

# Sensor lists — stored nested under a "sensors" dict inside config_entry.data
CONF_MMWAVE_SENSORS = "mmwave_sensors"
CONF_PIR_SENSORS = "pir_sensors"
CONF_ESPRESENSE_SENSORS = "espresense_sensors"
CONF_PERSON_COUNT_SENSORS = "person_count_sensors"
CONF_DOOR_SENSORS = "door_sensors"
CONF_WINDOW_SENSORS = "window_sensors"
CONF_LOCK_ENTITIES = "lock_entities"
CONF_MEDIA_PLAYERS = "media_players"
CONF_LIGHT_ENTITIES = "light_entities"
CONF_SWITCH_ENTITIES = "switch_entities"
CONF_WORKSTATION_SENSORS = "workstation_sensors"

# Legacy sensor keys — kept for backward compatibility with existing config entries
CONF_WORKSTATION_ENTITIES = "workstation_entities"
CONF_WORKSTATION_POWER_SENSORS = "workstation_power_sensors"

# Sleep mode
CONF_SLEEP_MODE_ENTITIES = "sleep_mode_entities"
CONF_SLEEP_CLEAR_THRESHOLD = "sleep_clear_threshold"

# LLM advisory
CONF_LLM_ENABLED = "llm_enabled"
CONF_LLM_PROVIDER = "llm_provider"          # "conversation" | "http"
CONF_CONVERSATION_AGENT = "conversation_agent"
CONF_LLM_UPDATE_INTERVAL = "llm_update_interval"
# Direct HTTP provider (OpenAI-compatible chat-completions, e.g. MiniMax, Groq)
CONF_LLM_BASE_URL = "llm_base_url"
CONF_LLM_API_KEY = "llm_api_key"
CONF_LLM_MODEL = "llm_model"

# Provider choices
LLM_PROVIDER_CONVERSATION = "conversation"  # HA conversation agent (default)
LLM_PROVIDER_HTTP = "http"                  # direct OpenAI-compatible HTTP endpoint


# ---------------------------------------------------------------------------
# State machine states
# ---------------------------------------------------------------------------
# Transition flow:
#   CLEAR → POSSIBLE_ENTRY → OCCUPIED → CLEAR_PENDING → CLEAR
# LIKELY_OCCUPIED and POSSIBLE_EXIT are reserved for future hysteresis use.

SM_CLEAR = "clear"
SM_POSSIBLE_ENTRY = "possible_entry"
SM_OCCUPIED = "occupied"
SM_LIKELY_OCCUPIED = "likely_occupied"
SM_POSSIBLE_EXIT = "possible_exit"
SM_CLEAR_PENDING = "clear_pending"

# States in which the binary sensor reports "occupied"
SM_OCCUPIED_STATES = {SM_OCCUPIED, SM_LIKELY_OCCUPIED, SM_CLEAR_PENDING}


# ---------------------------------------------------------------------------
# Score weights
# ---------------------------------------------------------------------------
# Scores are additive and capped at 100.  The defaults are:
#   occupied_threshold = 50  →  score ≥ 50 triggers OCCUPIED
#   clear_threshold    = 20  →  score ≤ 20 starts the clear timeout
#
# Weight rationale:
#   mmWave / person-count  (80): Hardware that reliably detects still persons.
#   ESPresense BLE         (50): BLE triangulation — room-level accuracy.
#   PIR active             (35): Motion sensor, misses stationary persons.
#   Workstation            (35): PC/monitor power draw implies desk presence.
#   Media playing          (30): Active media strongly correlates with presence.
#   Media paused           (15): Weaker — player may be idle.
#   PIR recent decay      (≤15): Residual confidence after PIR turns off.
#   Light manual on        (20): Supporting context — not proof of presence.
#   Lock recently used    (≤15): Decays over 10 min after unlock event.
#   Door recently opened  (≤10): Weakest context signal, decays over 5 min.

WEIGHT_MMWAVE = 80
WEIGHT_PERSON_COUNT = 80
WEIGHT_ESPRESENSE = 50
WEIGHT_PIR_ACTIVE = 35
WEIGHT_WORKSTATION_ACTIVE = 35
WEIGHT_MEDIA_PLAYING = 30
WEIGHT_MEDIA_PAUSED = 15
WEIGHT_PIR_RECENT = 15
# A manually-on light is weak evidence, not proof of presence. Kept strictly
# below DEFAULT_CLEAR_THRESHOLD (20) so a light left on cannot on its own hold a
# room OCCUPIED — otherwise an empty room with the light on never clears and the
# lighting automation re-asserts the light (feedback loop). Was 20 (== clear
# threshold) which caused exactly that.
WEIGHT_LIGHT_MANUAL = 10
# The EVENT of a human switching a light/switch ON (off→on with no automation
# context) is positive proof someone is in the room — unlike the light *state*
# above. Weight ≥ occupied threshold so it promotes the room immediately (e.g.
# entering a room where the mmWave zone starts a few meters past the door),
# decaying over DECAY_LIGHT. Automation-caused turn-ons carry a context
# parent_id and do NOT count, so this cannot re-create the feedback loop.
WEIGHT_LIGHT_SWITCHED_ON = 60
WEIGHT_LOCK_UNLOCKED = 15
WEIGHT_DOOR_OPENED = 10


# ---------------------------------------------------------------------------
# Decay durations (seconds)
# ---------------------------------------------------------------------------
# How long a one-shot event (e.g. door open) contributes a decaying score.

DECAY_PIR = 300     # 5 min — residual confidence after PIR goes off
DECAY_DOOR = 300    # 5 min — door-opened context window
DECAY_LOCK = 600    # 10 min — lock-used context window
DECAY_LIGHT = 900   # 15 min — manual light-switched-on entry evidence window

# A workstation sensor with power domain is considered active above this value
WORKSTATION_POWER_THRESHOLD_W = 10.0


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_OCCUPIED_THRESHOLD = 50
DEFAULT_CLEAR_THRESHOLD = 20
DEFAULT_NO_PRESENCE_TIMEOUT = 300       # 5 min before transitioning to CLEAR
DEFAULT_MIN_HOLD_TIME = 60              # 1 min minimum in OCCUPIED before clearing
DEFAULT_DOOR_LOCKED_IN_TIMEOUT = 14400  # 4 h cap when door has been closed since OCCUPIED (locked-in)
# Need this many seconds of (score>=occupied AND all doors closed) to trust
# lock-in. Must exceed the trailing "on" hold time of mmWave sensors (~2-3 min):
# a quick visit (walk in, grab something, walk out, close the door) leaves the
# mmWave on for minutes after the room is empty — at 120 s that residual armed
# the lock-in and held the empty room for the 4 h cap. A real occupant behind a
# closed door easily exceeds 5 min, so lock-in still engages when it should.
DOOR_LOCK_SOLID_DURATION = 300
DEFAULT_POLL_INTERVAL = 5               # coordinator polling interval in seconds
DEFAULT_SLEEP_CLEAR_THRESHOLD = 5       # very hard to go clear while sleep mode is active


# ---------------------------------------------------------------------------
# Confidence levels (output values for the confidence sensor)
# ---------------------------------------------------------------------------

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"


# ---------------------------------------------------------------------------
# LLM advisory
# ---------------------------------------------------------------------------

DEFAULT_REQUIRE_DOOR_ENTRY = False  # legacy opt-in key, no longer used by the gate
DEFAULT_DISABLE_DOOR_ENTRY = False  # entry-gate opt-out, off by default (gate on)
DEFAULT_LLM_UPDATE_INTERVAL = 300   # minimum seconds between LLM batch calls
DEFAULT_LLM_PROVIDER = LLM_PROVIDER_CONVERSATION
# Sensible default for the direct HTTP provider — MiniMax global, OpenAI-compatible
DEFAULT_LLM_BASE_URL = "https://api.minimax.io/v1"
DEFAULT_LLM_MODEL = "MiniMax-M3"
LLM_HTTP_TIMEOUT = 60               # seconds; reasoning models can be slow
