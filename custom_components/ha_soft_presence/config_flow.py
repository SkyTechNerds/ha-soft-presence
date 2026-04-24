"""Config flow for HA Soft Presence."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_ROOM_NAME,
    CONF_ROOM_TYPE,
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
    CONF_WORKSTATION_ENTITIES,
    CONF_WORKSTATION_POWER_SENSORS,
    CONF_LLM_ENABLED,
    CONF_CONVERSATION_AGENT,
    CONF_LLM_UPDATE_INTERVAL,
    DEFAULT_OCCUPIED_THRESHOLD,
    DEFAULT_CLEAR_THRESHOLD,
    DEFAULT_NO_PRESENCE_TIMEOUT,
    DEFAULT_MIN_HOLD_TIME,
    DEFAULT_LLM_UPDATE_INTERVAL,
)

_ROOM_TYPE_OPTIONS = [
    selector.SelectOptionDict(value="office",    label="Büro / Office"),
    selector.SelectOptionDict(value="bedroom",   label="Schlafzimmer / Bedroom"),
    selector.SelectOptionDict(value="living",    label="Wohnzimmer / Living Room"),
    selector.SelectOptionDict(value="bathroom",  label="Bad / Bathroom"),
    selector.SelectOptionDict(value="kitchen",   label="Küche / Kitchen"),
    selector.SelectOptionDict(value="hallway",   label="Flur / Hallway"),
    selector.SelectOptionDict(value="custom",    label="Benutzerdefiniert / Custom"),
]



class SoftPresenceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Multi-step config flow: room → sensors → thresholds → LLM."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict = {}

    # ------------------------------------------------------------------
    # Step 1: Room basics
    # ------------------------------------------------------------------

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_presence_sensors()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ROOM_NAME): str,
                vol.Required(CONF_ROOM_TYPE, default="living"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=_ROOM_TYPE_OPTIONS)
                ),
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
            })
            return await self.async_step_context_sensors()

        return self.async_show_form(
            step_id="presence_sensors",
            data_schema=vol.Schema({
                vol.Optional(CONF_MMWAVE_SENSORS, default=[]): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["binary_sensor"],
                        multiple=True,
                    )
                ),
                vol.Optional(CONF_PIR_SENSORS, default=[]): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["binary_sensor"],
                        device_class=["motion", "occupancy"],
                        multiple=True,
                    )
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
                CONF_WORKSTATION_ENTITIES: user_input.get(CONF_WORKSTATION_ENTITIES, []),
                CONF_WORKSTATION_POWER_SENSORS: user_input.get(CONF_WORKSTATION_POWER_SENSORS, []),
            })
            return await self.async_step_thresholds()

        return self.async_show_form(
            step_id="context_sensors",
            data_schema=vol.Schema({
                vol.Optional(CONF_DOOR_SENSORS, default=[]): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["binary_sensor"],
                        device_class=["door"],
                        multiple=True,
                    )
                ),
                vol.Optional(CONF_WINDOW_SENSORS, default=[]): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["binary_sensor"],
                        device_class=["window"],
                        multiple=True,
                    )
                ),
                vol.Optional(CONF_LOCK_ENTITIES, default=[]): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["lock"],
                        multiple=True,
                    )
                ),
                vol.Optional(CONF_MEDIA_PLAYERS, default=[]): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["media_player"],
                        multiple=True,
                    )
                ),
                vol.Optional(CONF_LIGHT_ENTITIES, default=[]): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["light"],
                        multiple=True,
                    )
                ),
                vol.Optional(CONF_SWITCH_ENTITIES, default=[]): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["switch"],
                        multiple=True,
                    )
                ),
                vol.Optional(CONF_WORKSTATION_ENTITIES, default=[]): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["binary_sensor"],
                        multiple=True,
                    )
                ),
                vol.Optional(CONF_WORKSTATION_POWER_SENSORS, default=[]): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor"],
                        device_class=["power"],
                        multiple=True,
                    )
                ),
            }),
        )

    # ------------------------------------------------------------------
    # Step 4: Thresholds + LLM
    # ------------------------------------------------------------------

    async def async_step_thresholds(self, user_input=None):
        if user_input is not None:
            self._data.update({
                CONF_OCCUPIED_THRESHOLD: int(user_input[CONF_OCCUPIED_THRESHOLD]),
                CONF_CLEAR_THRESHOLD: int(user_input[CONF_CLEAR_THRESHOLD]),
                CONF_NO_PRESENCE_TIMEOUT: int(user_input[CONF_NO_PRESENCE_TIMEOUT]),
                CONF_MIN_HOLD_TIME: int(user_input[CONF_MIN_HOLD_TIME]),
                CONF_LLM_ENABLED: user_input.get(CONF_LLM_ENABLED, False),
                CONF_LLM_PROVIDER: user_input.get(CONF_LLM_PROVIDER, "ha_conversation"),
                CONF_LLM_API_KEY: user_input.get(CONF_LLM_API_KEY, ""),
            })
            return self.async_create_entry(
                title=self._data[CONF_ROOM_NAME],
                data=self._data,
            )

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
                    selector.NumberSelectorConfig(
                        min=30, max=3600, step=30,
                        unit_of_measurement="s", mode="box"
                    )
                ),
                vol.Required(CONF_MIN_HOLD_TIME, default=DEFAULT_MIN_HOLD_TIME): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=600, step=10,
                        unit_of_measurement="s", mode="box"
                    )
                ),
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
    # Options flow (reconfigure existing entry)
    # ------------------------------------------------------------------

    @staticmethod
    def async_get_options_flow(config_entry):
        return SoftPresenceOptionsFlow(config_entry)


class SoftPresenceOptionsFlow(config_entries.OptionsFlow):
    """Allow editing thresholds and LLM settings after setup."""

    def __init__(self, config_entry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        data = self.config_entry.data

        if user_input is not None:
            updated = dict(data)
            updated.update({
                CONF_OCCUPIED_THRESHOLD: int(user_input[CONF_OCCUPIED_THRESHOLD]),
                CONF_CLEAR_THRESHOLD: int(user_input[CONF_CLEAR_THRESHOLD]),
                CONF_NO_PRESENCE_TIMEOUT: int(user_input[CONF_NO_PRESENCE_TIMEOUT]),
                CONF_MIN_HOLD_TIME: int(user_input[CONF_MIN_HOLD_TIME]),
                CONF_LLM_ENABLED: user_input.get(CONF_LLM_ENABLED, False),
                CONF_CONVERSATION_AGENT: user_input.get(CONF_CONVERSATION_AGENT),
                CONF_LLM_UPDATE_INTERVAL: int(user_input.get(CONF_LLM_UPDATE_INTERVAL, DEFAULT_LLM_UPDATE_INTERVAL)),
            })
            self.hass.config_entries.async_update_entry(self.config_entry, data=updated)
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_OCCUPIED_THRESHOLD,
                    default=data.get(CONF_OCCUPIED_THRESHOLD, DEFAULT_OCCUPIED_THRESHOLD)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=100, step=1, mode="slider")
                ),
                vol.Required(
                    CONF_CLEAR_THRESHOLD,
                    default=data.get(CONF_CLEAR_THRESHOLD, DEFAULT_CLEAR_THRESHOLD)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=99, step=1, mode="slider")
                ),
                vol.Required(
                    CONF_NO_PRESENCE_TIMEOUT,
                    default=data.get(CONF_NO_PRESENCE_TIMEOUT, DEFAULT_NO_PRESENCE_TIMEOUT)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=30, max=3600, step=30, unit_of_measurement="s", mode="box")
                ),
                vol.Required(
                    CONF_MIN_HOLD_TIME,
                    default=data.get(CONF_MIN_HOLD_TIME, DEFAULT_MIN_HOLD_TIME)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=600, step=10, unit_of_measurement="s", mode="box")
                ),
                vol.Optional(
                    CONF_LLM_ENABLED,
                    default=data.get(CONF_LLM_ENABLED, False)
                ): selector.BooleanSelector(),
                vol.Optional(CONF_CONVERSATION_AGENT): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["conversation"])
                ),
                vol.Optional(
                    CONF_LLM_UPDATE_INTERVAL,
                    default=data.get(CONF_LLM_UPDATE_INTERVAL, DEFAULT_LLM_UPDATE_INTERVAL)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=60, max=3600, step=60, unit_of_measurement="s", mode="box")
                ),
            }),
        )
