"""Budgeted context assembly for long-running story agents."""

from __future__ import annotations

import json
import os
from typing import Any

import config
from canon_context import build_canon_packet
from memory_manager import get_memory_context, sync_all_characters
from state import get_player_character, get_player_memory_id, read_json
from story_ledger import StoryLedger


def _clip(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text[:limit]


def _read_chat_history() -> dict[str, Any]:
    try:
        path = os.path.join(config.world_dir(), "chat_history.json")
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _event_text(event: dict[str, Any]) -> str:
    if not isinstance(event, dict):
        return ""
    if event.get("text"):
        return str(event["text"])
    data = event.get("data", {})
    if not isinstance(data, dict):
        return str(data)[:160]
    event_type = event.get("type", "")
    if event_type == "player-action-recorded":
        return f"玩家行动：{data.get('action', '')}"
    if event_type == "narration":
        return f"世界变化：{data.get('text', '')}"
    if event_type == "npc-message":
        return f"{data.get('npc_name', 'NPC')}：{data.get('dialogue') or data.get('action_desc', '')}"
    if event_type == "system-message":
        return f"系统：{data.get('dialogue', '')}"
    if event_type == "agent-output" and data.get("agent") == "chronicler":
        return f"正文：{data.get('summary', '')}"
    return _clip(data, 160)


def build_agent_context(agent_name: str = "", *, event_limit: int = 16) -> dict[str, Any]:
    """Build a compact, priority-ordered context packet for every story agent.

    Priority is intentionally stable:
    Canon hard constraints -> executable outline beat -> current main arc -> player recent actions ->
    world state -> unresolved foreshadows/canon facts -> important memory ->
    chat summary -> recent visible chat events.
    """
    try:
        world = read_json(config.STATE_DIR, "world.json")
    except Exception:
        world = {}
    player = get_player_character() or {}
    player_id = get_player_memory_id()
    action_log = player.get("action_log", [])
    if not isinstance(action_log, list):
        action_log = []

    chat = _read_chat_history()
    chat_events = chat.get("events", [])
    if not isinstance(chat_events, list):
        chat_events = []
    recent_chat = []
    for event in chat_events[-event_limit:]:
        if isinstance(event, dict):
            recent_chat.append({
                "type": event.get("type", ""),
                "round": event.get("round") or (event.get("data", {}) if isinstance(event.get("data"), dict) else {}).get("round", 0),
                "text": _event_text(event)[:220],
            })

    ledger_context = {"recent_events": [], "facts": [], "open_foreshadows": []}
    try:
        current_round = world.get("meta", {}).get("current_round", 0) if isinstance(world, dict) else 0
        ledger_context = StoryLedger(config.world_dir()).context_for(
            player_id=player_id,
            chapter_no=max(1, int(current_round or 0)),
            event_limit=event_limit,
        )
    except Exception:
        pass

    try:
        sync_all_characters()
    except Exception:
        pass

    memory_context = get_memory_context(
        player_id,
        max_items=12,
        context="；".join(item.get("text", "") for item in recent_chat[-5:]),
    )

    world_time = world.get("time", {}) if isinstance(world, dict) else {}
    geography = world.get("geography", {}) if isinstance(world, dict) else {}
    canon_packet = build_canon_packet(agent_name)
    return {
        "agent": agent_name,
        "priority_order": [
            "canon_packet.hard_facts",
            "canon_packet.round_contract",
            "canon_packet.active_beat",
            "canon_packet.current_arc",
            "canon_packet.active_milestones",
            "canon_packet.stage_gates",
            "player_recent_actions",
            "current_world_state",
            "open_foreshadows",
            "canon_facts",
            "character_memory",
            "chat_summary",
            "recent_chat_events",
        ],
        "canon_packet": canon_packet,
        "player": {
            "id": player.get("id", player_id),
            "name": player.get("name", "主角"),
            "realm": player.get("realm", "凡人"),
            "recent_actions": action_log[-8:],
        },
        "current_world_state": {
            "round": world.get("meta", {}).get("current_round", 0) if isinstance(world, dict) else 0,
            "time": world_time,
            "current_region": geography.get("current_region", "") if isinstance(geography, dict) else "",
        },
        "story_ledger": {
            "recent_events": ledger_context.get("recent_events", [])[-event_limit:],
            "facts": ledger_context.get("facts", [])[:30],
            "open_foreshadows": ledger_context.get("open_foreshadows", [])[:20],
        },
        "character_memory": memory_context[:2400],
        "chat_summary": str(chat.get("summary", ""))[-3000:],
        "recent_chat_events": recent_chat,
    }
