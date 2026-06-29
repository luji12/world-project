"""Story-driven NPC agent lifecycle management.

The simulator keeps permanent NPC files in ``characters.json`` and memory
files, but only a small story-relevant subset should be active as agents in a
given round.  This module owns that runtime active-agent registry.
"""

from __future__ import annotations

import json
import time
from typing import Any

import config
from agents.base import call_deepseek, ensure_list_of_dicts, normalize_agent_output
from memory_manager import add_memory, init_character_memory
from state import read_json, update_json, write_json, get_player_character
from world_shape import current_region_id

NPC_AGENTS_FILE = "npc_agents.json"
CORE_AGENT_LIMIT = 8
SCENE_AGENT_LIMIT = 12
ACTIVE_AGENT_LIMIT = CORE_AGENT_LIMIT + SCENE_AGENT_LIMIT
RETIRE_AFTER_ROUNDS = 4
ENCOUNTER_WORDS = (
    "遇到", "遇见", "碰到", "看到", "发现", "来到", "进入", "拜访", "问路", "打听",
    "进城", "上山", "入店", "集市", "客栈", "酒楼", "药铺", "宗门", "村", "镇",
)
ACTIVE_ENCOUNTER_WORDS = (
    "遇到", "遇见", "碰到", "看到", "发现", "来到", "进入", "拜访", "问路", "打听",
    "进城", "上山", "入店",
)
RETIRE_WORDS = ("离开", "告别", "独自上路", "离店", "出城", "回屋", "休息", "闭关")


def _empty_registry(round_no: int = 0) -> dict[str, Any]:
    return {"version": "0.1", "updated_round": round_no, "agents": []}


def read_npc_agents() -> dict[str, Any]:
    try:
        data = read_json(config.STATE_DIR, NPC_AGENTS_FILE)
        return data if isinstance(data, dict) else _empty_registry()
    except Exception:
        return _empty_registry()


def write_npc_agents(registry: dict[str, Any]) -> dict[str, Any]:
    registry.setdefault("version", "0.1")
    registry.setdefault("agents", [])
    write_json(config.STATE_DIR, NPC_AGENTS_FILE, registry)
    return registry


def _current_round(world: dict) -> int:
    try:
        return int(world.get("meta", {}).get("current_round", 0) or 0)
    except Exception:
        return 0


def _character_list(chars: dict) -> list[dict]:
    return [c for c in chars.get("characters", []) if isinstance(c, dict)]


def _npc_chars(chars: dict) -> list[dict]:
    return [
        c for c in _character_list(chars)
        if not c.get("player_controlled") and c.get("status") not in {"死亡", "dead"}
    ]


def _last_action(protagonist: dict) -> str:
    action_log = protagonist.get("action_log", [])
    if isinstance(action_log, list) and action_log:
        latest = action_log[-1]
        if isinstance(latest, dict):
            return str(latest.get("action", "") or "")
    return ""


def _story_text(world: dict, protagonist: dict) -> str:
    active_events = world.get("global_events", {}).get("active", [])
    return "\n".join([
        _last_action(protagonist),
        json.dumps(active_events, ensure_ascii=False)[:2000],
        str(world.get("_last_scene_atmosphere", "")),
    ])


def _is_spawn_trigger(text: str) -> bool:
    return bool(text and any(word in text for word in ENCOUNTER_WORDS))


def _is_active_encounter_trigger(text: str) -> bool:
    return bool(text and any(word in text for word in ACTIVE_ENCOUNTER_WORDS))


def _is_retire_trigger(text: str) -> bool:
    return bool(text and any(word in text for word in RETIRE_WORDS))


def _mentioned_npcs(chars: dict, text: str) -> list[dict]:
    if not text:
        return []
    return [c for c in _npc_chars(chars) if c.get("name") and c.get("name") in text]


def _score_existing_npc(c: dict, text: str, current_region: str, active_ids: set[str], round_no: int) -> int:
    cid = str(c.get("id") or c.get("name") or "")
    score = 0
    if cid in active_ids or c.get("agent_status") == "active":
        score += 12
    if c.get("name") and c.get("name") in text:
        score += 10
    loc = str(c.get("location") or c.get("region") or "")
    if current_region and (loc.startswith(current_region) or current_region in loc):
        score += 4
    if c.get("_last_interaction_round", 0):
        score += 2
    try:
        last_active = int(c.get("last_active_round", 0) or 0)
        if round_no - last_active <= 2:
            score += 2
    except Exception:
        pass
    if c.get("role") and any(word in c.get("role", "") for word in ("店主", "守卫", "掌柜", "长老", "师傅", "朋友")):
        score += 1
    return score


def _next_npc_id(chars: dict) -> str:
    used = {str(c.get("id", "")) for c in _character_list(chars)}
    idx = len(used) + 1
    while f"npc-{idx:03d}" in used:
        idx += 1
    return f"npc-{idx:03d}"


def _fallback_character(chars: dict, world: dict, action_text: str, round_no: int) -> dict:
    current_region = current_region_id(world) or "当前区域"
    if any(word in action_text for word in ("药铺", "入店", "疗伤", "药")):
        role = "药铺掌柜"
        name = "回春堂掌柜"
        goal = "判断来客伤势与来意"
    elif any(word in action_text for word in ("进城", "城门", "问路")):
        role = "城门守卫"
        name = "城门守卫"
        goal = "盘问陌生来客"
    else:
        role = "路人"
        name = "陌生人"
        goal = "观察主角并决定是否接触"
    existing_names = {c.get("name") for c in _character_list(chars)}
    suffix = 2
    base_name = name
    while name in existing_names:
        name = f"{base_name}{suffix}"
        suffix += 1
    return {
        "id": _next_npc_id(chars),
        "name": name,
        "role": role,
        "personality": "谨慎、会根据局势调整态度",
        "location": current_region,
        "realm": "凡人",
        "secret": "暂未揭示",
        "desires": [goal],
        "daily_routine": {"上午": "处理本职事务", "下午": "观察往来人群", "晚上": "整理今日见闻"},
        "status": "活跃",
        "agent_status": "active",
        "spawn_round": round_no,
        "last_active_round": round_no,
        "current_goal": goal,
        "story_importance": "scene",
    }


def _generate_story_npcs(chars: dict, world: dict, protagonist: dict, api_key: str, base_url: str, model: str, count: int = 1) -> list[dict]:
    round_no = _current_round(world)
    action_text = _last_action(protagonist)
    current_region = current_region_id(world)
    existing_names = [c.get("name") for c in _character_list(chars) if c.get("name")]
    system_prompt = (
        "你是剧情驱动的NPC Agent生命周期设计师。只在当前剧情确实需要新人物时创建NPC。"
        "NPC必须有可推演的人设、欲望、秘密、当前场景目标。输出JSON。"
    )
    user_prompt = json.dumps({
        "instruction": f"根据当前剧情创建{count}个会立即入场的NPC Agent。不要重复已有名字；不要创建远离当前场景的人物。",
        "player_action": action_text,
        "world_time": world.get("time"),
        "current_region": current_region,
        "existing_names": existing_names[-80:],
        "output_format": {
            "characters": [{
                "name": "NPC名",
                "role": "场景身份",
                "personality": "性格",
                "location": "当前位置",
                "realm": "境界/能力",
                "secret": "秘密",
                "desires": ["当前欲望"],
                "daily_routine": {"上午": "...", "下午": "...", "晚上": "..."},
                "current_goal": "本场景目标",
                "story_importance": "core|scene",
            }]
        },
    }, ensure_ascii=False)
    try:
        output = normalize_agent_output(
            call_deepseek(system_prompt, user_prompt, api_key=api_key, base_url=base_url, model=model, max_tokens=1200),
            fallback_key="characters",
        )
        generated = ensure_list_of_dicts(output.get("characters"))[:count]
    except Exception:
        generated = []
    if not generated:
        generated = [_fallback_character(chars, world, action_text, round_no)]

    existing_names = {c.get("name") for c in _character_list(chars)}
    new_chars = []
    for raw in generated:
        name = raw.get("name") or "陌生人"
        if name in existing_names:
            continue
        raw["id"] = _next_npc_id({"characters": _character_list(chars) + new_chars})
        raw.setdefault("status", "活跃")
        raw["agent_status"] = "active"
        raw.setdefault("spawn_round", round_no)
        raw["last_active_round"] = round_no
        raw.setdefault("location", current_region)
        raw.setdefault("desires", [])
        raw.setdefault("current_goal", "参与当前剧情")
        raw.setdefault("story_importance", "scene")
        new_chars.append(raw)
        existing_names.add(name)
    return new_chars


def _upsert_agents(existing_agents: list[dict], chars_by_id: dict[str, dict], activate_ids: list[str], reason: str, round_no: int) -> list[dict]:
    by_id = {
        str(agent.get("npc_id")): dict(agent)
        for agent in existing_agents
        if isinstance(agent, dict) and agent.get("npc_id")
    }
    for npc_id in activate_ids:
        c = chars_by_id.get(npc_id)
        if not c:
            continue
        by_id[npc_id] = {
            "npc_id": npc_id,
            "name": c.get("name", npc_id),
            "role_in_scene": c.get("role", "NPC"),
            "activation_reason": reason,
            "scene_goal": c.get("current_goal") or (c.get("desires") or ["参与当前剧情"])[0],
            "visibility_scope": "player_scene",
            "last_tick_round": round_no,
            "activated_at": by_id.get(npc_id, {}).get("activated_at", time.time()),
        }
    return list(by_id.values())[:ACTIVE_AGENT_LIMIT]


def plan_npc_lifecycle(api_key: str = "", base_url: str = "", model: str = "") -> dict[str, Any]:
    """Plan and apply NPC Agent spawn/activate/retire for the current round."""
    try:
        world = read_json(config.STATE_DIR, "world.json")
    except Exception:
        world = {"meta": {"current_round": 0}}
    try:
        chars = read_json(config.STATE_DIR, "characters.json")
    except Exception:
        chars = {"characters": []}
    protagonist = get_player_character() or {}
    round_no = _current_round(world)
    story_text = _story_text(world, protagonist)
    action_text = _last_action(protagonist)
    registry = read_npc_agents()
    existing_agents = registry.get("agents", []) if isinstance(registry.get("agents"), list) else []
    active_ids = {str(agent.get("npc_id")) for agent in existing_agents if isinstance(agent, dict) and agent.get("npc_id")}
    retire_trigger = _is_retire_trigger(action_text)
    spawn_trigger = _is_spawn_trigger(story_text)
    active_encounter_trigger = _is_active_encounter_trigger(action_text)
    should_activate_existing = spawn_trigger and not retire_trigger
    should_spawn_new = spawn_trigger and (not retire_trigger or active_encounter_trigger)

    for c in _npc_chars(chars):
        c.setdefault("agent_status", "dormant")
        c.setdefault("spawn_round", round_no)

    mentioned = _mentioned_npcs(chars, story_text)
    scored = []
    current_region = current_region_id(world)
    for c in _npc_chars(chars):
        score = _score_existing_npc(c, story_text, current_region, active_ids, round_no)
        if score > 0:
            scored.append((score, c))
    scored.sort(key=lambda item: item[0], reverse=True)

    activate_ids = []
    reason_parts = []
    if not retire_trigger:
        for c in mentioned:
            cid = str(c.get("id") or c.get("name"))
            if cid and cid not in activate_ids:
                activate_ids.append(cid)
    if mentioned and not retire_trigger:
        reason_parts.append("剧情提及旧NPC")

    if should_activate_existing:
        reason_parts.append("玩家行动触发新场景/接触NPC")
        for _, c in scored[:ACTIVE_AGENT_LIMIT]:
            cid = str(c.get("id") or c.get("name"))
            if cid and cid not in activate_ids:
                activate_ids.append(cid)
            if len(activate_ids) >= min(3, ACTIVE_AGENT_LIMIT):
                break
    elif should_spawn_new:
        reason_parts.append("玩家行动触发新场景/接触NPC")

    new_chars = []
    if should_spawn_new and not activate_ids:
        new_chars = _generate_story_npcs(chars, world, protagonist, api_key, base_url, model, count=1)
        chars.setdefault("characters", []).extend(new_chars)
        activate_ids.extend([str(c["id"]) for c in new_chars if c.get("id")])

    retire_ids = []
    if retire_trigger:
        retire_ids.extend(active_ids - set(activate_ids))
    for agent in existing_agents:
        if not isinstance(agent, dict):
            continue
        npc_id = str(agent.get("npc_id", ""))
        if not npc_id or npc_id in activate_ids:
            continue
        try:
            last_tick = int(agent.get("last_tick_round", 0) or 0)
        except Exception:
            last_tick = 0
        if round_no - last_tick >= RETIRE_AFTER_ROUNDS:
            retire_ids.append(npc_id)

    retire_ids = list(dict.fromkeys(retire_ids))
    chars_by_id = {str(c.get("id") or c.get("name")): c for c in _npc_chars(chars)}
    active_after_retire = [agent for agent in existing_agents if str(agent.get("npc_id", "")) not in set(retire_ids)]
    reason = "；".join(reason_parts) or "无剧情触发，仅保持现有活跃NPC"
    agents = _upsert_agents(active_after_retire, chars_by_id, activate_ids, reason, round_no)

    active_id_set = {str(agent.get("npc_id")) for agent in agents}
    retired_id_set = set(retire_ids)
    for c in _npc_chars(chars):
        cid = str(c.get("id") or c.get("name"))
        if cid in active_id_set:
            c["agent_status"] = "active"
            c["last_active_round"] = round_no
            c["exit_reason"] = ""
        elif cid in retired_id_set:
            c["agent_status"] = "dormant"
            c["exit_reason"] = "离开当前活跃剧情"
        else:
            c.setdefault("agent_status", "dormant")

    def apply_chars(_latest):
        return chars
    update_json(config.STATE_DIR, "characters.json", apply_chars, {"characters": []})

    registry = {
        "version": "0.1",
        "updated_round": round_no,
        "agents": agents,
        "last_plan": {
            "reason": reason,
            "new_character_ids": [c.get("id") for c in new_chars],
            "activate_ids": activate_ids,
            "retire_ids": retire_ids,
        },
    }
    write_npc_agents(registry)

    for c in new_chars:
        init_character_memory(str(c["id"]), c.get("name", c["id"]), "npc")
        add_memory(str(c["id"]), {
            "round": round_no,
            "content": f"[spawn] {c.get('name')}因“{reason}”进入剧情。目标：{c.get('current_goal', '')}",
            "importance": 4,
        })
    for npc_id in retire_ids:
        c = chars_by_id.get(npc_id)
        if c:
            add_memory(npc_id, {
                "round": round_no,
                "content": f"[retire] {c.get('name', npc_id)}退出当前活跃剧情；档案和记忆保留。",
                "importance": 4,
            })

    return {
        "new_characters": new_chars,
        "activate_ids": activate_ids,
        "retire_ids": retire_ids,
        "active_count": len(agents),
        "reason": reason,
    }
