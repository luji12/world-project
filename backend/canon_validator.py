"""Canon validation and light repair for player actions and agent outputs."""

from __future__ import annotations

import copy
import re
from typing import Any

import config
from canon_engine import record_conflict


LATE_STAGE_HINTS = [
    "飞升", "渡劫", "成仙", "灭世", "统一天下", "终局", "最终boss", "最终 Boss",
    "天基武器", "星际舰队", "星空远征", "归元", "天道联盟", "大道本源",
]


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _current_arc_order(packet: dict[str, Any]) -> int:
    arc = packet.get("current_arc", {}) if isinstance(packet, dict) else {}
    try:
        return int(arc.get("order") or 1)
    except Exception:
        return 1


def validate_player_action(action: str, canon_packet: dict[str, Any]) -> dict[str, Any]:
    """Gate impossible stage jumps without deleting player agency."""
    if not canon_packet.get("exists"):
        return {"allowed": True, "violations": []}

    order = _current_arc_order(canon_packet)
    violations = []
    if order <= 1:
        for hint in LATE_STAGE_HINTS:
            if hint and hint in action:
                violations.append({
                    "type": "stage_gate",
                    "hint": hint,
                    "message": f"当前仍在「{canon_packet.get('current_arc', {}).get('name', '开篇阶段')}」，行动包含后期剧情关键词「{hint}」。",
                })
                break

    if not violations:
        return {"allowed": True, "violations": []}

    return {
        "allowed": False,
        "violations": violations,
        "reason": "这个行动越过了当前主线阶段门槛，Canon 会把它转化为失败、延迟或需要先完成前置里程碑。",
        "suggested_action": "先围绕当前地点、当前人物和当前里程碑采取可执行行动。",
    }


def _allowed_location_names(packet: dict[str, Any]) -> set[str]:
    allowed = set()
    current = packet.get("current_location_rules", {})
    if isinstance(current, dict):
        for key in ["id", "name"]:
            if current.get(key):
                allowed.add(str(current[key]))
    for fact in packet.get("hard_facts", []):
        if isinstance(fact, dict) and fact.get("key") in {"region", "starting_region"} and fact.get("value"):
            allowed.add(str(fact["value"]))
    return {name for name in allowed if name}


def _repair_location_drift(text: str, packet: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    if not text or not packet.get("exists"):
        return text, []
    allowed = _allowed_location_names(packet)
    current = packet.get("current_location_rules", {})
    replacement = current.get("name") if isinstance(current, dict) else ""
    replacement = replacement or next(iter(allowed), "")
    if not replacement:
        return text, []

    conflicts = []
    # Catch common invented place names in early scenes.  Do not replace names
    # already present in Canon; this keeps side scenes possible once introduced.
    pattern = re.compile(r"([\u4e00-\u9fff]{2,10}(?:村|镇|城|山|宗|门|院|坊|界|域|国|府|县|谷|岛))")
    repaired = text
    for name in pattern.findall(text):
        if name not in allowed and len(name) <= 12:
            repaired = repaired.replace(name, replacement)
            conflicts.append({
                "type": "location_drift",
                "message": f"输出提到了 Canon 外地点「{name}」，已轻修复为当前 Canon 地点「{replacement}」。",
                "offending_value": name,
                "repair": replacement,
            })
            break
    return repaired, conflicts


def validate_agent_output(
    agent_name: str,
    output: dict[str, Any],
    canon_packet: dict[str, Any],
    *,
    world_path: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Lightly repair agent output and record conflicts.

    Severe conflicts are surfaced to the caller via ``report.conflicts``.  The
    scheduler can then decide whether to emit a conflict event or block writes.
    """
    if not isinstance(output, dict) or not canon_packet.get("exists"):
        return output if isinstance(output, dict) else {}, {"conflicts": [], "repaired": False}

    repaired = copy.deepcopy(output)
    conflicts: list[dict[str, Any]] = []
    text_fields = {
        "world-engine": ["scene_description", "reasoning"],
        "chronicler": ["narrative_passage", "summary"],
        "system-agent": ["system_dialogue", "reasoning"],
    }.get(agent_name, ["reasoning"])

    for field in text_fields:
        if isinstance(repaired.get(field), str):
            next_text, field_conflicts = _repair_location_drift(repaired[field], canon_packet)
            if field_conflicts:
                repaired[field] = next_text
                conflicts.extend({**item, "agent": agent_name, "field": field} for item in field_conflicts)

    forbidden = [str(item) for item in canon_packet.get("forbidden_events", []) if item]
    if agent_name in {"system-agent", "world-engine", "chronicler"}:
        blob = "\n".join(_text(repaired.get(field)) for field in text_fields)
        for rule in forbidden:
            if rule and len(rule) <= 80 and rule in blob:
                conflicts.append({
                    "type": "forbidden_event",
                    "agent": agent_name,
                    "message": f"输出触碰禁行规则：{rule}",
                    "severity": "severe",
                })

    if conflicts and world_path:
        for conflict in conflicts:
            record_conflict(world_path, conflict)
    elif conflicts:
        try:
            for conflict in conflicts:
                record_conflict(config.world_dir(), conflict)
        except Exception:
            pass

    return repaired, {
        "conflicts": conflicts,
        "repaired": bool(conflicts),
        "blocked": any(item.get("severity") == "severe" for item in conflicts),
    }


def validate_npc_lifecycle_plan(
    plan: dict[str, Any],
    canon_packet: dict[str, Any],
    *,
    world_path: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Prevent premature key-character activation when stage gates are locked."""
    if not isinstance(plan, dict) or not canon_packet.get("exists"):
        return plan if isinstance(plan, dict) else {}, {"conflicts": [], "repaired": False}

    order = _current_arc_order(canon_packet)
    if order > 1:
        return plan, {"conflicts": [], "repaired": False}

    gated_keywords = ["最终", "天道", "终局", "幕后主宰", "归元"]
    new_chars = []
    conflicts = []
    for char in plan.get("new_characters", []) if isinstance(plan.get("new_characters"), list) else []:
        blob = _text(char)
        if any(keyword in blob for keyword in gated_keywords):
            conflicts.append({
                "type": "premature_npc_spawn",
                "agent": "npc-lifecycle",
                "message": "早期阶段拦截了疑似后期关键角色生成。",
                "offending_value": blob[:200],
            })
        else:
            new_chars.append(char)
    if conflicts:
        repaired = {**plan, "new_characters": new_chars}
        try:
            for conflict in conflicts:
                record_conflict(world_path or config.world_dir(), conflict)
        except Exception:
            pass
        return repaired, {"conflicts": conflicts, "repaired": True}
    return plan, {"conflicts": [], "repaired": False}
