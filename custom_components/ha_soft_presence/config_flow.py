"""Config flow for HA Soft Presence."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er, selector

from .const import (
    DOMAIN,
    CONF_ROOM_NAME,
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
    CONF_WORKSTATION_SENSORS,
    CONF_ESPRESENSE_SENSORS,
    CONF_PERSON_COUNT_SENSORS,
    CONF_WORKSTATION_ENTITIES,
    CONF_WORKSTATION_POWER_SENSORS,
    CONF_SLEEP_MODE_ENTITIES,
    CONF_SLEEP_CLEAR_THRESHOLD,
    CONF_LLM_ENABLED,
    CONF_CONVERSATION_AGENT,
    CONF_LLM_UPDATE_INTERVAL,
    DEFAULT_OCCUPIED_THRESHOLD,
    DEFAULT_CLEAR_THRESHOLD,
    DEFAULT_NO_PRESENCE_TIMEOUT,
    DEFAULT_MIN_HOLD_TIME,
    DEFAULT_SLEEP_CLEAR_THRESHOLD,
    DEFAULT_LLM_UPDATE_INTERVAL,
)


# ------------------------------------------------------------------
# Area helpers
# ------------------------------------------------------------------

def _find_area_id(hass: HomeAssistant, room_name: str) -> str | None:
    """Return the first area whose name matches room_name (case-insensitive, partial ok)."""
    area_reg = ar.async_get(hass)
    name = room_name.lower().strip()
    # Exact match wins
    for area in area_reg.async_list_areas():
        if area.name.lower().strip() == name:
            return area.id
    # Substring match as fallback
    for area in area_reg.async_list_areas():
        area_lower = area.name.lower().strip()
        if name in area_lower or area_lower in name:
            return area.id
    return None


def _area_entities(
    hass: HomeAssistant,
    area_id: str,
    domains: list[str],
    device_classes: list[str] | None = None,
) -> list[str]:
    """Return enabled, non-hidden entity IDs in area matching domain and optional device classes.

    Checks both entity-level area assignment and device-level area assignment,
    since most users assign devices (not individual entities) to areas.
    """
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    result: list[str] = []
    for entry in ent_reg.entities.values():
        if entry.disabled_by is not None or entry.hidden_by is not None:
            continue
        if entry.entity_id.split(".")[0] not in domains:
            continue

        # Resolve area: entity-level takes precedence, fall back to device-level
        effective_area = entry.area_id
        if effective_area is None and entry.device_id:
            device = dev_reg.async_get(entry.device_id)
            if device:
                effective_area = device.area_id

        if effective_area != area_id:
            continue

        if device_classes is not None:
            dc = entry.device_class or entry.original_device_class
            if dc not in device_classes:
                continue
        result.append(entry.entity_id)
    return sorted(result)


class SoftPresenceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Multi-step config flow: room → sensors → thresholds → LLM."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict = {}
        self._area_id: str | None = None

    # ------------------------------------------------------------------
    # Step 1: Room basics
    # ------------------------------------------------------------------

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            self._area_id = _find_area_id(self.hass, user_input[CONF_ROOM_NAME])
            return await self.async_step_presence_sensors()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ROOM_NAME): str,
                vol.Required(CONF_HAS_DOOR, default=True): selector.BooleanSelector(),
                vol.Required(CONF_IS_TRANSIT, default=False): selector.BooleanSelector(),
            }),
        )

    # ------------------------------------------------------------------
    # Step 2: Presence sensors (mmWave, PIR)
    # ------------------------------------------------------------------

    async def async_step_presence_sensors(self, user_input=None):
        if user_input is not None:
            self._data.setdefault("sensors", {})
            self._data["sensors"].update({
                CONF_MMWAVE_SENSORS: user_input.get(CONF_MMWAVE_SENSORS, []),
                CONF_PIR_SENSORS: user_input.get(CONF_PIR_SENSORS, []),
                CONF_ESPRESENSE_SENSORS: user_input.get(CONF_ESPRESENSE_SENSORS, []),
                CONF_PERSON_COUNT_SENSORS: user_input.get(CONF_PERSON_COUNT_SENSORS, []),
            })
            return await self.async_step_context_sensors()

        mmwave_default: list[str] = []
        pir_default: list[str] = []
        if self._area_id:
            mmwave_default = _area_entities(
                self.hass, self._area_id, ["binary_sensor"], ["occupancy"]
            )
            pir_default = _area_entities(
                self.hass, self._area_id, ["binary_sensor"], ["motion", "occupancy"]
            )

        return self.async_show_form(
            step_id="presence_sensors",
            data_schema=vol.Schema({
                vol.Optional(CONF_MMWAVE_SENSORS, default=mmwave_default): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor"], multiple=True)
                ),
                vol.Optional(CONF_PIR_SENSORS, default=pir_default): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["binary_sensor"],
                        device_class=["motion", "occupancy"],
                        multiple=True,
                    )
                ),
                vol.Optional(CONF_ESPRESENSE_SENSORS, default=[]): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor"], multiple=True)
                ),
                vol.Optional(CONF_PERSON_COUNT_SENSORS, default=[]): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor"], multiple=True)
                ),
            }),
        )

    # ------------------------------------------------------------------
    # Step 3: Context sensors
    # ------------------------------------------------------------------

    async def async_step_context_sensors(self, user_input=None):
        if user_input is not None:
            self._data["sensors"].update({
                CONF_DOOR_SENSORS: user_input.get(CONF_DOOR_SENSORS, []),
                CONF_WINDOW_SENSORS: user_input.get(CONF_WINDOW_SENSORS, []),
                CONF_LOCK_ENTITIES: user_input.get(CONF_LOCK_ENTITIES, []),
                CONF_MEDIA_PLAYERS: user_input.get(CONF_MEDIA_PLAYERS, []),
                CONF_LIGHT_ENTITIES: user_input.get(CONF_LIGHT_ENTITIES, []),
                CONF_SWITCH_ENTITIES: user_input.get(CONF_SWITCH_ENTITIES, []),
                CONF_WORKSTATION_SENSORS: user_input.get(CONF_WORKSTATION_SENSORS, []),
            })
            return await self.async_step_thresholds()

        doors: list[str] = []
        windows: list[str] = []
        locks: list[str] = []
        media: list[str] = []
        lights: list[str] = []
        switches: list[str] = []
        workstation: list[str] = []

        if self._area_id:
            doors = _area_entities(self.hass, self._area_id, ["binary_sensor"], ["door"])
            windows = _area_entities(self.hass, self._area_id, ["binary_sensor"], ["window"])
            locks = _area_entities(self.hass, self._area_id, ["lock"])
            media = _area_entities(self.hass, self._area_id, ["media_player"])
            lights = _area_entities(self.hass, self._area_id, ["light"])
            switches = _area_entities(self.hass, self._area_id, ["switch"])
            workstation = _area_entities(self.hass, self._area_id, ["sensor"], ["power"])

        return self.async_show_form(
            step_id="context_sensors",
            data_schema=vol.Schema({
                vol.Optional(CONF_DOOR_SENSORS, default=doors): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["binary_sensor"], device_class=["door"], multiple=True
                    )
                ),
                vol.Optional(CONF_WINDOW_SENSORS, default=windows): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["binary_sensor"], device_class=["window"], multiple=True
                    )
                ),
                vol.Optional(CONF_LOCK_ENTITIES, default=locks): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["lock"], multiple=True)
                ),
                vol.Optional(CONF_MEDIA_PLAYERS, default=media): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["media_player"], multiple=True)
                ),
                vol.Optional(CONF_LIGHT_ENTITIES, default=lights): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["light"], multiple=True)
                ),
                vol.Optional(CONF_SWITCH_ENTITIES, default=switches): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["switch"], multiple=True)
                ),
                vol.Optional(CONF_WORKSTATION_SENSORS, default=workstation): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["binary_sensor", "sensor"], multiple=True
                    )
                ),
            }),
        )

    # ------------------------------------------------------------------
    # Step 4: Thresholds
    # ------------------------------------------------------------------

    async def async_step_thresholds(self, user_input=None):
        if user_input is not None:
            self._data.update({
                CONF_OCCUPIED_THRESHOLD: int(user_input[CONF_OCCUPIED_THRESHOLD]),
                CONF_CLEAR_THRESHOLD: int(user_input[CONF_CLEAR_THRESHOLD]),
                CONF_NO_PRESENCE_TIMEOUT: int(user_input[CONF_NO_PRESENCE_TIMEOUT]),
                CONF_MIN_HOLD_TIME: int(user_input[CONF_MIN_HOLD_TIME]),
                CONF_SLEEP_MODE_ENTITIES: user_input.get(CONF_SLEEP_MODE_ENTITIES, []),
                CONF_SLEEP_CLEAR_THRESHOLD: int(user_input[CONF_SLEEP_CLEAR_THRESHOLD]),
            })
            return await self.async_step_llm()

        return self.async_show_form(
            step_id="thresholds",
            data_schema=vol.Schema({
                vol.Required(CONF_OCCUPIED_THRESHOLD, default=DEFAULT_OCCUPIED_THRESHOLD): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=100, step=1, mode="slider")
                ),
                vol.Required(CONF_CLEAR_THRESHOLD, default=DEFAULT_CLEAR_THRESHOLD): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=99, step=1, mode="slider")
                ),
                vol.Required(CONF_NO_PRESENCE_TIMEOUT, default=DEFAULT_NO_PRESENCE_TIMEOUT): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=30, max=3600, step=30, unit_of_measurement="s", mode="box")
                ),
                vol.Required(CONF_MIN_HOLD_TIME, default=DEFAULT_MIN_HOLD_TIME): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=600, step=10, unit_of_measurement="s", mode="box")
                ),
                vol.Optional(CONF_SLEEP_MODE_ENTITIES, default=[]): selector.EntitySelector(
                    selector.EntitySelectorConfig(multiple=True)
                ),
                vol.Required(CONF_SLEEP_CLEAR_THRESHOLD, default=DEFAULT_SLEEP_CLEAR_THRESHOLD): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=99, step=1, mode="slider")
                ),
            }),
        )

    # ------------------------------------------------------------------
    # Step 5: LLM
    # ------------------------------------------------------------------

    async def async_step_llm(self, user_input=None):
        if user_input is not None:
            self._data.update({
                CONF_LLM_ENABLED: user_input.get(CONF_LLM_ENABLED, False),
                CONF_CONVERSATION_AGENT: user_input.get(CONF_CONVERSATION_AGENT),
                CONF_LLM_UPDATE_INTERVAL: int(user_input.get(CONF_LLM_UPDATE_INTERVAL, DEFAULT_LLM_UPDATE_INTERVAL)),
            })
            return self.async_create_entry(title=self._data[CONF_ROOM_NAME], data=self._data)

        return self.async_show_form(
            step_id="llm",
            data_schema=vol.Schema({
                vol.Optional(CONF_LLM_ENABLED, default=False): selector.BooleanSelector(),
                vol.Optional(CONF_CONVERSATION_AGENT): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["conversation"])
                ),
                vol.Optional(CONF_LLM_UPDATE_INTERVAL, default=DEFAULT_LLM_UPDATE_INTERVAL): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=60, max=3600, step=60, unit_of_measurement="s", mode="box")
                ),
            }),
        )

    # ------------------------------------------------------------------
    # Options flow
    # ------------------------------------------------------------------

    @staticmethod
    def async_get_options_flow(config_entry):
        return SoftPresenceOptionsFlow()


class SoftPresenceOptionsFlow(config_entries.OptionsFlow):
    """Full reconfiguration after setup — sensors, thresholds, LLM."""

    def __init__(self) -> None:
        self._data: dict = {}
        self._area_id: str | None = None

    # ------------------------------------------------------------------
    # Step 1: Room basics
    # ------------------------------------------------------------------

    async def async_step_init(self, user_input=None):
        data = self.config_entry.data
        if user_input is not None:
            self._data.update(user_input)
            # Re-resolve area whenever room name is changed
            self._area_id = _find_area_id(self.hass, user_input[CONF_ROOM_NAME])
            return await self.async_step_edit_presence_sensors()

        # Pre-resolve area for the current room name so subsequent steps can use it
        self._area_id = _find_area_id(self.hass, data.get(CONF_ROOM_NAME, ""))

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_ROOM_NAME, default=data.get(CONF_ROOM_NAME, "")): str,
                vol.Required(CONF_HAS_DOOR, default=data.get(CONF_HAS_DOOR, True)): selector.BooleanSelector(),
                vol.Required(CONF_IS_TRANSIT, default=data.get(CONF_IS_TRANSIT, False)): selector.BooleanSelector(),
            }),
        )

    # ------------------------------------------------------------------
    # Step 2: Presence sensors
    # ------------------------------------------------------------------

    async def async_step_edit_presence_sensors(self, user_input=None):
        sensors = self.config_entry.data.get("sensors", {})
        if user_input is not None:
            self._data.setdefault("sensors", {})
            self._data["sensors"].update({
                CONF_MMWAVE_SENSORS: user_input.get(CONF_MMWAVE_SENSORS, []),
                CONF_PIR_SENSORS: user_input.get(CONF_PIR_SENSORS, []),
                CONF_ESPRESENSE_SENSORS: user_input.get(CONF_ESPRESENSE_SENSORS, []),
                CONF_PERSON_COUNT_SENSORS: user_input.get(CONF_PERSON_COUNT_SENSORS, []),
            })
            return await self.async_step_edit_context_sensors()

        # Use saved values only — no area auto-fill when editing an existing room
        return self.async_show_form(
            step_id="edit_presence_sensors",
            data_schema=vol.Schema({
                vol.Optional(CONF_MMWAVE_SENSORS, default=sensors.get(CONF_MMWAVE_SENSORS, [])): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor"], multiple=True)
                ),
                vol.Optional(CONF_PIR_SENSORS, default=sensors.get(CONF_PIR_SENSORS, [])): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["binary_sensor"],
                        device_class=["motion", "occupancy"],
                        multiple=True,
                    )
                ),
                vol.Optional(CONF_ESPRESENSE_SENSORS, default=sensors.get(CONF_ESPRESENSE_SENSORS, [])): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor"], multiple=True)
                ),
                vol.Optional(CONF_PERSON_COUNT_SENSORS, default=sensors.get(CONF_PERSON_COUNT_SENSORS, [])): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor"], multiple=True)
                ),
            }),
        )

    # ------------------------------------------------------------------
    # Step 3: Context sensors
    # ------------------------------------------------------------------

    async def async_step_edit_context_sensors(self, user_input=None):
        sensors = self.config_entry.data.get("sensors", {})
        if user_input is not None:
            self._data["sensors"].update({
                CONF_DOOR_SENSORS: user_input.get(CONF_DOOR_SENSORS, []),
                CONF_WINDOW_SENSORS: user_input.get(CONF_WINDOW_SENSORS, []),
                CONF_LOCK_ENTITIES: user_input.get(CONF_LOCK_ENTITIES, []),
                CONF_MEDIA_PLAYERS: user_input.get(CONF_MEDIA_PLAYERS, []),
                CONF_LIGHT_ENTITIES: user_input.get(CONF_LIGHT_ENTITIES, []),
                CONF_SWITCH_ENTITIES: user_input.get(CONF_SWITCH_ENTITIES, []),
                CONF_WORKSTATION_SENSORS: user_input.get(CONF_WORKSTATION_SENSORS, []),
            })
            return await self.async_step_edit_thresholds()

        # Legacy workstation migration: merge old separate fields into new combined field
        legacy_ws = sensors.get(CONF_WORKSTATION_ENTITIES, []) + sensors.get(CONF_WORKSTATION_POWER_SENSORS, [])
        ws_default = sensors.get(CONF_WORKSTATION_SENSORS, legacy_ws)

        return self.async_show_form(
            step_id="edit_context_sensors",
            data_schema=vol.Schema({
                vol.Optional(CONF_DOOR_SENSORS, default=sensors.get(CONF_DOOR_SENSORS, [])): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor"], device_class=["door"], multiple=True)
                ),
                vol.Optional(CONF_WINDOW_SENSORS, default=sensors.get(CONF_WINDOW_SENSORS, [])): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor"], device_class=["window"], multiple=True)
                ),
                vol.Optional(CONF_LOCK_ENTITIES, default=sensors.get(CONF_LOCK_ENTITIES, [])): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["lock"], multiple=True)
                ),
                vol.Optional(CONF_MEDIA_PLAYERS, default=sensors.get(CONF_MEDIA_PLAYERS, [])): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["media_player"], multiple=True)
                ),
                vol.Optional(CONF_LIGHT_ENTITIES, default=sensors.get(CONF_LIGHT_ENTITIES, [])): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["light"], multiple=True)
                ),
                vol.Optional(CONF_SWITCH_ENTITIES, default=sensors.get(CONF_SWITCH_ENTITIES, [])): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["switch"], multiple=True)
                ),
                vol.Optional(CONF_WORKSTATION_SENSORS, default=ws_default): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor", "sensor"], multiple=True)
                ),
            }),
        )

    # ------------------------------------------------------------------
    # Step 4: Thresholds
    # ------------------------------------------------------------------

    async def async_step_edit_thresholds(self, user_input=None):
        data = self.config_entry.data
        if user_input is not None:
            self._data.update({
                CONF_OCCUPIED_THRESHOLD: int(user_input[CONF_OCCUPIED_THRESHOLD]),
                CONF_CLEAR_THRESHOLD: int(user_input[CONF_CLEAR_THRESHOLD]),
                CONF_NO_PRESENCE_TIMEOUT: int(user_input[CONF_NO_PRESENCE_TIMEOUT]),
                CONF_MIN_HOLD_TIME: int(user_input[CONF_MIN_HOLD_TIME]),
                CONF_SLEEP_MODE_ENTITIES: user_input.get(CONF_SLEEP_MODE_ENTITIES, []),
                CONF_SLEEP_CLEAR_THRESHOLD: int(user_input[CONF_SLEEP_CLEAR_THRESHOLD]),
            })
            return await self.async_step_edit_llm()

        return self.async_show_form(
            step_id="edit_thresholds",
            data_schema=vol.Schema({
                vol.Required(CONF_OCCUPIED_THRESHOLD, default=data.get(CONF_OCCUPIED_THRESHOLD, DEFAULT_OCCUPIED_THRESHOLD)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=100, step=1, mode="slider")
                ),
                vol.Required(CONF_CLEAR_THRESHOLD, default=data.get(CONF_CLEAR_THRESHOLD, DEFAULT_CLEAR_THRESHOLD)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=99, step=1, mode="slider")
                ),
                vol.Required(CONF_NO_PRESENCE_TIMEOUT, default=data.get(CONF_NO_PRESENCE_TIMEOUT, DEFAULT_NO_PRESENCE_TIMEOUT)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=30, max=3600, step=30, unit_of_measurement="s", mode="box")
                ),
                vol.Required(CONF_MIN_HOLD_TIME, default=data.get(CONF_MIN_HOLD_TIME, DEFAULT_MIN_HOLD_TIME)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=600, step=10, unit_of_measurement="s", mode="box")
                ),
                vol.Optional(CONF_SLEEP_MODE_ENTITIES, default=data.get(CONF_SLEEP_MODE_ENTITIES, [])): selector.EntitySelector(
                    selector.EntitySelectorConfig(multiple=True)
                ),
                vol.Required(CONF_SLEEP_CLEAR_THRESHOLD, default=data.get(CONF_SLEEP_CLEAR_THRESHOLD, DEFAULT_SLEEP_CLEAR_THRESHOLD)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=99, step=1, mode="slider")
                ),
            }),
        )

    # ------------------------------------------------------------------
    # Step 5: LLM
    # ------------------------------------------------------------------

    async def async_step_edit_llm(self, user_input=None):
        data = self.config_entry.data
        if user_input is not None:
            # If user didn't pick a new agent, keep the previously saved one
            agent = user_input.get(CONF_CONVERSATION_AGENT) or data.get(CONF_CONVERSATION_AGENT)
            updated = dict(data)
            updated.update(self._data)
            updated.update({
                CONF_LLM_ENABLED: user_input.get(CONF_LLM_ENABLED, False),
                CONF_CONVERSATION_AGENT: agent,
                CONF_LLM_UPDATE_INTERVAL: int(user_input.get(CONF_LLM_UPDATE_INTERVAL, DEFAULT_LLM_UPDATE_INTERVAL)),
            })
            self.hass.config_entries.async_update_entry(self.config_entry, data=updated)
            return self.async_create_entry(title="", data={})

        saved_agent = data.get(CONF_CONVERSATION_AGENT)
        schema: dict = {
            vol.Optional(CONF_LLM_ENABLED, default=data.get(CONF_LLM_ENABLED, False)): selector.BooleanSelector(),
        }
        # Pre-fill conversation agent only when a value is already saved
        if saved_agent:
            schema[vol.Optional(CONF_CONVERSATION_AGENT, default=saved_agent)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["conversation"])
            )
        else:
            schema[vol.Optional(CONF_CONVERSATION_AGENT)] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["conversation"])
            )
        schema[vol.Optional(CONF_LLM_UPDATE_INTERVAL, default=data.get(CONF_LLM_UPDATE_INTERVAL, DEFAULT_LLM_UPDATE_INTERVAL))] = selector.NumberSelector(
            selector.NumberSelectorConfig(min=60, max=3600, step=60, unit_of_measurement="s", mode="box")
        )

        return self.async_show_form(
            step_id="edit_llm",
            data_schema=vol.Schema(schema),
        )
