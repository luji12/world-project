"""Runtime Canon packet construction for all story agents."""

from __future__ import annotations

from typing import Any

import config
from canon_engine import canon_exists, load_canon


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _current_arc(story_arcs: dict[str, Any]) -> dict[str, Any]:
    arcs = story_arcs.get("arcs", [])
    if not isinstance(arcs, list) or not arcs:
        return {}
    current_id = story_arcs.get("current_arc_id")
    if current_id:
        for arc in arcs:
            if isinstance(arc, dict) and arc.get("id") == current_id:
                return arc
    return next((arc for arc in arcs if isinstance(arc, dict) and arc.get("status") == "active"), {}) or arcs[0]


def build_canon_packet(agent_name: str = "", *, source_excerpt_limit: int = 1200) -> dict[str, Any]:
    """Return the highest-priority context all agents should obey."""
    world_path = config.world_dir()
    if not canon_exists(world_path):
        return {
            "exists": False,
            "agent": agent_name,
            "hard_facts": [],
            "current_arc": {},
            "active_milestones": [],
            "stage_gates": [],
            "forbidden_events": [],
            "current_location_rules": {},
            "character_constraints": {},
            "power_system_rules": {},
            "source_excerpt": "",
        }

    canon = load_canon(world_path)
    bible = canon.get("world_bible", {}) if isinstance(canon.get("world_bible"), dict) else {}
    arcs = canon.get("story_arcs", {}) if isinstance(canon.get("story_arcs"), dict) else {}
    constraints = canon.get("constraints", {}) if isinstance(canon.get("constraints"), dict) else {}
    arc = _current_arc(arcs)
    milestones = []
    for item in _as_list(arc.get("required_milestones")) + _as_list(arc.get("optional_milestones")):
        if isinstance(item, dict):
            if item.get("status", "open") not in {"done", "completed", "closed"}:
                milestones.append(item)
        elif item:
            milestones.append({"name": str(item), "status": "open"})

    geography = bible.get("geography", {}) if isinstance(bible.get("geography"), dict) else {}
    current_region = geography.get("current_region") or bible.get("starting_region", "")
    regions = geography.get("regions", {}) if isinstance(geography.get("regions"), dict) else {}
    current_location_rules = {}
    if current_region in regions and isinstance(regions[current_region], dict):
        current_location_rules = regions[current_region]

    return {
        "exists": True,
        "agent": agent_name,
        "hard_facts": _as_list(constraints.get("hard_facts"))[:60],
        "current_arc": arc,
        "active_milestones": milestones[:20],
        "stage_gates": _as_list(constraints.get("stage_gates"))[:30],
        "forbidden_events": _as_list(constraints.get("forbidden_events"))[:30],
        "current_location_rules": current_location_rules,
        "character_constraints": {
            "characters": _as_list(bible.get("characters"))[:40],
            "factions": _as_list(bible.get("factions"))[:30],
        },
        "power_system_rules": bible.get("power_system") or {},
        "world_laws": _as_list(bible.get("world_laws"))[:30],
        "source_excerpt": (canon.get("source_text") or "")[:source_excerpt_limit],
    }
