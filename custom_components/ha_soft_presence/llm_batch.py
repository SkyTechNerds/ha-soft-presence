"""Batch LLM evaluation — one API call for all rooms."""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from .coordinator import SoftPresenceCoordinator

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_BATCH_PROMPT_HEADER = """\
You are a home presence detection system. Analyze the rooms below and decide \
for each whether it is currently occupied. Be concise and output JSON only.

ROOMS TO ANALYZE:
"""

_BATCH_PROMPT_ROOM = """\
[{idx}] Room: {room_name} | Has door: {has_door} | Transit room: {is_transit}
Recent sensor events (seconds ago):
{events_text}
Rule engine: score={rule_score}/100, state={rule_state}
"""

_BATCH_PROMPT_FOOTER = """\

Respond with ONLY a JSON array — one object per room, in the same order:
[
  {{"room": "Room Name", "occupied": true, "score": 75, "confidence": "high", "reason": "one sentence"}},
  ...
]
"""


async def async_batch_llm_update(hass: "HomeAssistant") -> None:
    """Run one LLM call per conversation agent covering all rooms that need an update."""
    from .coordinator import SoftPresenceCoordinator  # avoid circular at module level

    all_coordinators: list[SoftPresenceCoordinator] = [
        c for c in hass.data.get(DOMAIN, {}).values()
        if isinstance(c, SoftPresenceCoordinator) and c.llm_enabled()
    ]

    if not all_coordinators:
        return

    # Group by conversation agent — one call per agent
    by_agent: dict[str, list[SoftPresenceCoordinator]] = defaultdict(list)
    for coord in all_coordinators:
        agent_id = coord.llm_agent_id()
        if agent_id:
            by_agent[agent_id].append(coord)

    for agent_id, coords in by_agent.items():
        # Only proceed if at least one room in this group needs an update
        needy = [c for c in coords if c.needs_llm_update()]
        if not needy:
            continue

        # Build combined prompt — include ALL rooms for context, mark which need update
        prompt_parts = [_BATCH_PROMPT_HEADER]
        for idx, coord in enumerate(coords, start=1):
            snap = coord.llm_snapshot()
            prompt_parts.append(_BATCH_PROMPT_ROOM.format(idx=idx, **snap))
        prompt_parts.append(_BATCH_PROMPT_FOOTER)
        prompt = "\n".join(prompt_parts)

        try:
            from homeassistant.components.conversation import async_converse
            from homeassistant.core import Context

            result = await async_converse(
                hass=hass,
                text=prompt,
                conversation_id=None,
                context=Context(),
                agent_id=agent_id,
            )
            speech = result.response.speech.get("plain", {}).get("speech", "")
            _parse_and_apply(speech, coords)

        except Exception as err:
            _LOGGER.warning("Batch LLM call failed for agent %s: %s", agent_id, err)
            return

        # Mark all rooms in this group as called (even those that didn't strictly need it,
        # since they were included in the prompt for context)
        for coord in coords:
            coord.mark_llm_called()

        # Trigger a data refresh so entities pick up the new LLM state
        for coord in coords:
            await coord.async_request_refresh()


def _parse_and_apply(text: str, coords: "list[SoftPresenceCoordinator]") -> None:
    """Parse a JSON array response and apply results to coordinators by position."""
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        _LOGGER.warning("Batch LLM: no JSON array found in response: %.300s", text)
        return

    try:
        results = json.loads(match.group())
    except json.JSONDecodeError as err:
        _LOGGER.warning("Batch LLM: JSON parse error: %s — raw: %.300s", err, text)
        return

    if not isinstance(results, list):
        _LOGGER.warning("Batch LLM: expected list, got %s", type(results))
        return

    # Match by position (primary) with room-name fallback
    name_map = {c.config.get("room_name", "").lower(): c for c in coords}

    for idx, item in enumerate(results):
        if not isinstance(item, dict):
            continue

        coord: SoftPresenceCoordinator | None = None

        # Try position first
        if idx < len(coords):
            coord = coords[idx]

        # Fallback: match by room name in response
        if coord is None or item.get("room", "").lower() not in ("", coord.config.get("room_name", "").lower()):
            room_key = item.get("room", "").lower()
            coord = name_map.get(room_key, coord)

        if coord is not None:
            coord.apply_llm_result(item)
