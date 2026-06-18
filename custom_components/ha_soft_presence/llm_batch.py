"""Batch LLM evaluation — one API call per backend for all its rooms.

Two backends are supported, selected per room via CONF_LLM_PROVIDER:
  - "conversation": a Home Assistant conversation agent (Gemini, OpenAI, …)
  - "http": a direct OpenAI-compatible chat-completions endpoint
    (e.g. MiniMax, Groq, any /v1/chat/completions API)
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from .coordinator import SoftPresenceCoordinator

from .const import DOMAIN, LLM_PROVIDER_HTTP, LLM_HTTP_TIMEOUT

_LOGGER = logging.getLogger(__name__)

_BATCH_PROMPT_HEADER = """\
You are a home presence detection system. For each room below, decide whether \
it is currently occupied based on the sensor data provided.

IMPORTANT: The rule engine score is computed from real hardware sensors \
(mmWave radar, PIR motion, lights, media players, etc.) and is highly reliable. \
Weight it heavily. "Currently active signals" shows sensors that are ON RIGHT NOW — \
if any are listed, the room almost certainly has presence.

ROOMS TO ANALYZE:
"""

_BATCH_PROMPT_ROOM = """\
[{idx}] Room: {room_name} | Has door: {has_door} | Transit room: {is_transit}
Currently active signals: {active_sources}
Rule engine: score={rule_score}/100, state={rule_state}, reason="{rule_reason}"
Recent sensor events (for context):
{events_text}
"""

_BATCH_PROMPT_FOOTER = """\

Respond with ONLY a JSON array — one object per room, in the same order, \
with no prose, no explanation, and no markdown code fences:
[
  {{"room": "Room Name", "occupied": true, "score": 75, "confidence": "high", "reason": "one sentence"}},
  ...
]
"""


async def async_batch_llm_update(hass: "HomeAssistant") -> None:
    """Run one LLM call per backend covering all of its rooms that need an update."""
    from .coordinator import SoftPresenceCoordinator  # avoid circular at module level

    all_coordinators: list[SoftPresenceCoordinator] = [
        c for c in hass.data.get(DOMAIN, {}).values()
        if isinstance(c, SoftPresenceCoordinator) and c.llm_enabled()
    ]

    if not all_coordinators:
        return

    # Group by backend key — rooms sharing a backend go in one call
    by_backend: dict[str, list[SoftPresenceCoordinator]] = defaultdict(list)
    for coord in all_coordinators:
        by_backend[coord.llm_backend_key()].append(coord)

    for coords in by_backend.values():
        # Only proceed if at least one room in this group needs an update
        if not any(c.needs_llm_update() for c in coords):
            continue

        # Build combined prompt — include ALL rooms in the group for context
        prompt_parts = [_BATCH_PROMPT_HEADER]
        for idx, coord in enumerate(coords, start=1):
            snap = coord.llm_snapshot()
            prompt_parts.append(_BATCH_PROMPT_ROOM.format(idx=idx, **snap))
        prompt_parts.append(_BATCH_PROMPT_FOOTER)
        prompt = "\n".join(prompt_parts)

        lead = coords[0]
        try:
            if lead.llm_provider() == LLM_PROVIDER_HTTP:
                text = await _call_http(hass, lead, prompt)
            else:
                text = await _call_conversation(hass, lead.llm_agent_id(), prompt)
        except Exception as err:
            _LOGGER.warning(
                "Batch LLM call failed for backend %s: %s", lead.llm_backend_key(), err
            )
            continue

        if text:
            _parse_and_apply(text, coords)

        # Mark all rooms in this group as called (they were in the prompt for context)
        for coord in coords:
            coord.mark_llm_called()
        for coord in coords:
            await coord.async_request_refresh()


async def _call_conversation(hass: "HomeAssistant", agent_id: str | None, prompt: str) -> str:
    """Call a Home Assistant conversation agent and return its plain-text reply."""
    from homeassistant.components.conversation import async_converse
    from homeassistant.core import Context

    result = await async_converse(
        hass=hass,
        text=prompt,
        conversation_id=None,
        context=Context(),
        agent_id=agent_id,
    )
    return result.response.speech.get("plain", {}).get("speech", "")


async def _call_http(hass: "HomeAssistant", coord: "SoftPresenceCoordinator", prompt: str) -> str:
    """Call an OpenAI-compatible /chat/completions endpoint and return the content."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    session = async_get_clientsession(hass)
    url = f"{coord.llm_base_url()}/chat/completions"
    headers = {"Content-Type": "application/json"}
    api_key = coord.llm_api_key()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": coord.llm_model(),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 1024,
    }

    async with session.post(url, json=payload, headers=headers, timeout=LLM_HTTP_TIMEOUT) as resp:
        if resp.status != 200:
            body = (await resp.text())[:300]
            raise RuntimeError(f"HTTP {resp.status}: {body}")
        data = await resp.json()

    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as err:
        raise RuntimeError(f"unexpected response shape: {str(data)[:300]}") from err


# Matches a ```json … ``` (or plain ```) fenced block
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
# Matches a <think> … </think> reasoning block (reasoning models like MiniMax-M3)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _extract_json_array(text: str) -> str | None:
    """Pull the JSON array out of a model reply that may wrap it in reasoning/fences."""
    if not text:
        return None
    # 1) Drop any <think>…</think> reasoning the model emitted
    cleaned = _THINK_RE.sub("", text)
    # 2) If the answer is fenced, prefer the fence contents
    fence = _FENCE_RE.search(cleaned)
    if fence:
        cleaned = fence.group(1)
    # 3) Grab the outermost [ … ] array
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    return match.group() if match else None


def _parse_and_apply(text: str, coords: "list[SoftPresenceCoordinator]") -> None:
    """Parse a JSON array response and apply results to coordinators by position."""
    array_text = _extract_json_array(text)
    if not array_text:
        _LOGGER.warning("Batch LLM: no JSON array found in response: %.300s", text)
        return

    try:
        results = json.loads(array_text)
    except json.JSONDecodeError as err:
        _LOGGER.warning("Batch LLM: JSON parse error: %s — raw: %.300s", err, array_text)
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
