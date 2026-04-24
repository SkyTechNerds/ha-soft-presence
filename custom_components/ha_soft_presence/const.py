"""Constants for HA Soft Presence."""

DOMAIN = "ha_soft_presence"

# Config keys — room basics
CONF_ROOM_NAME = "room_name"
CONF_ROOM_TYPE = "room_type"
CONF_HAS_DOOR = "has_door"
CONF_IS_TRANSIT = "is_transit"

# Config keys — thresholds
CONF_OCCUPIED_THRESHOLD = "occupied_threshold"
CONF_CLEAR_THRESHOLD = "clear_threshold"
CONF_NO_PRESENCE_TIMEOUT = "no_presence_timeout"
CONF_MIN_HOLD_TIME = "min_hold_time"

# Config keys — sensor lists (stored under "sensors" dict)
CONF_MMWAVE_SENSORS = "mmwave_sensors"
CONF_PIR_SENSORS = "pir_sensors"
CONF_DOOR_SENSORS = "door_sensors"
CONF_WINDOW_SENSORS = "window_sensors"
CONF_LOCK_ENTITIES = "lock_entities"
CONF_MEDIA_PLAYERS = "media_players"
CONF_LIGHT_ENTITIES = "light_entities"
CONF_SWITCH_ENTITIES = "switch_entities"
CONF_WORKSTATION_ENTITIES = "workstation_entities"
CONF_WORKSTATION_POWER_SENSORS = "workstation_power_sensors"
CONF_CAMERA_ENTITIES = "camera_entities"

# Config keys — LLM
CONF_LLM_ENABLED = "llm_enabled"
CONF_LLM_PROVIDER = "llm_provider"
CONF_LLM_API_KEY = "llm_api_key"
CONF_LLM_MODEL = "llm_model"

# Room types
ROOM_TYPE_OFFICE = "office"
ROOM_TYPE_BEDROOM = "bedroom"
ROOM_TYPE_LIVING = "living"
ROOM_TYPE_BATHROOM = "bathroom"
ROOM_TYPE_KITCHEN = "kitchen"
ROOM_TYPE_HALLWAY = "hallway"
ROOM_TYPE_CUSTOM = "custom"

ROOM_TYPES = [
    ROOM_TYPE_OFFICE,
    ROOM_TYPE_BEDROOM,
    ROOM_TYPE_LIVING,
    ROOM_TYPE_BATHROOM,
    ROOM_TYPE_KITCHEN,
    ROOM_TYPE_HALLWAY,
    ROOM_TYPE_CUSTOM,
]

# State machine states
SM_CLEAR = "clear"
SM_POSSIBLE_ENTRY = "possible_entry"
SM_OCCUPIED = "occupied"
SM_LIKELY_OCCUPIED = "likely_occupied"
SM_POSSIBLE_EXIT = "possible_exit"
SM_CLEAR_PENDING = "clear_pending"

SM_OCCUPIED_STATES = {SM_OCCUPIED, SM_LIKELY_OCCUPIED, SM_CLEAR_PENDING}

# Score weights
WEIGHT_MMWAVE = 80
WEIGHT_PIR_ACTIVE = 35
WEIGHT_PIR_RECENT = 15      # PIR fired recently but now off
WEIGHT_MEDIA_PLAYING = 30
WEIGHT_MEDIA_PAUSED = 15
WEIGHT_WORKSTATION_ACTIVE = 35
WEIGHT_LIGHT_MANUAL = 20
WEIGHT_DOOR_OPENED = 10
WEIGHT_LOCK_UNLOCKED = 15

# Decay durations (seconds)
DECAY_PIR = 300         # 5 min residual after PIR off
DECAY_DOOR = 300        # 5 min door-opened context
DECAY_LOCK = 600        # 10 min lock context
DECAY_LIGHT = 900       # 15 min light-on hint

# Workstation power threshold
WORKSTATION_POWER_THRESHOLD_W = 10.0

# Defaults
DEFAULT_OCCUPIED_THRESHOLD = 50
DEFAULT_CLEAR_THRESHOLD = 20
DEFAULT_NO_PRESENCE_TIMEOUT = 300   # 5 min
DEFAULT_MIN_HOLD_TIME = 60          # 1 min
DEFAULT_POLL_INTERVAL = 5           # seconds

# Confidence levels
CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

# LLM providers
LLM_PROVIDER_HA = "ha_conversation"
LLM_PROVIDER_OPENAI = "openai"
LLM_PROVIDER_GEMINI = "gemini"

LLM_PROVIDERS = [
    LLM_PROVIDER_HA,
    LLM_PROVIDER_OPENAI,
    LLM_PROVIDER_GEMINI,
]
