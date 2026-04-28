"""Constants for HA Soft Presence."""

DOMAIN = "ha_soft_presence"

# ---------------------------------------------------------------------------
# Config keys — stored in config_entry.data
# ---------------------------------------------------------------------------

# Room basics
CONF_ROOM_NAME = "room_name"
CONF_HAS_DOOR = "has_door"
CONF_IS_TRANSIT = "is_transit"

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
CONF_CONVERSATION_AGENT = "conversation_agent"
CONF_LLM_UPDATE_INTERVAL = "llm_update_interval"


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
WEIGHT_LIGHT_MANUAL = 20
WEIGHT_LOCK_UNLOCKED = 15
WEIGHT_DOOR_OPENED = 10


# ---------------------------------------------------------------------------
# Decay durations (seconds)
# ---------------------------------------------------------------------------
# How long a one-shot event (e.g. door open) contributes a decaying score.

DECAY_PIR = 300     # 5 min — residual confidence after PIR goes off
DECAY_DOOR = 300    # 5 min — door-opened context window
DECAY_LOCK = 600    # 10 min — lock-used context window
DECAY_LIGHT = 900   # 15 min — (reserved, not yet used in scoring)

# A workstation sensor with power domain is considered active above this value
WORKSTATION_POWER_THRESHOLD_W = 10.0


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_OCCUPIED_THRESHOLD = 50
DEFAULT_CLEAR_THRESHOLD = 20
DEFAULT_NO_PRESENCE_TIMEOUT = 300       # 5 min before transitioning to CLEAR
DEFAULT_MIN_HOLD_TIME = 60              # 1 min minimum in OCCUPIED before clearing
DEFAULT_DOOR_VALIDATED_TIMEOUT = 30     # 30 s fast-clear when door proves no entry/exit
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

DEFAULT_LLM_UPDATE_INTERVAL = 300   # minimum seconds between LLM batch calls
