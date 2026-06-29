import json
import os
from .base import call_deepseek, call_deepseek_stream, normalize_agent_output, ensure_dict, ensure_list_of_dicts
from state import read_json, write_json, update_json, get_player_memory_id
import config
from memory_manager import get_memory_context, sync_all_characters
from risk import get_risk, modify_risk, roll_fate, get_fate_prompt_context, assess_action_risk
from agent_templates import get_agent_config, build_world_engine_system_prompt
from story_context import build_agent_context
from world_shape import current_region_id, current_region_info


def _read_chat_summary():
    """读取聊天记录的压缩摘要，用于保持上下文连贯性"""
    try:
        world_dir = config.world_dir()
        if not world_dir:
            return ""
        path = os.path.join(world_dir, "chat_history.json")
        with open(path, "r", encoding="utf-8") as f:
            history = json.load(f)
        return history.get("summary", "")
    except Exception:
        return ""


def _build_world_engine_prompt():
    """构建世界引擎的 user_prompt，供同步和流式版本共用"""
    world = read_json(config.STATE_DIR, "world.json")
    sync_all_characters()
    world_meta = world.get("meta", {})
    agent_config = get_agent_config(world_meta)
    system_prompt = build_world_engine_system_prompt(agent_config, world_meta)
    current_region = current_region_id(world)
    active_events = [e for e in world.get("global_events", {}).get("active", []) if isinstance(e, dict)]
    active_event_names = [e.get("name", "") for e in active_events]
    search_context = f"当前地区：{current_region}。活跃事件：{', '.join(active_event_names) if active_event_names else '无'}。"
    memory_text = get_memory_context(get_player_memory_id(), max_items=5, context=search_context)
    fate_context = get_fate_prompt_context()
    risk_level = get_risk()
    fate = roll_fate(risk_level)

    inject_text = ""
    try:
        from state import get_pending_injections, update_json
        injections = get_pending_injections()
        unapplied = [i for i in injections if not i.get("applied")]
        if unapplied:
            inject_text = "此外，以下外部事件正在发生（高优先级，必须纳入本轮推演）：" + "；".join([i["text"] for i in unapplied]) + "。"
            def apply(data):
                for i in data.get("injections", []):
                    if not i.get("applied"):
                        i["applied"] = True
                return data
            update_json(config.STATE_DIR, "_pending_injections.json", apply, {"injections": injections})
    except Exception:
        pass

    # ── Context pruning ────────────────────────────────────────────
    all_factions = [f for f in world.get("factions", []) if isinstance(f, dict)]
    active_faction_names = {
        evt.get("faction", "") for evt in active_events if evt.get("faction")
    }
    relevant_factions = [f for f in all_factions if f.get("name") in active_faction_names or
                         f.get("region", "") == current_region]
    if not relevant_factions:
        relevant_factions = all_factions[:3]
    else:
        relevant_factions = relevant_factions[:3]

    pending_events = [e for e in world.get("global_events", {}).get("pending", []) if isinstance(e, dict)][:5]
    active_events_pruned = active_events[:5]

    chat_summary = _read_chat_summary()
    long_context = build_agent_context("world-engine")

    user_prompt = json.dumps({
        "instruction": f"推进一轮世界时间（约1{agent_config.get('world_engine', {}).get('time_unit', '天')}），推演环境变化。考虑主角最近的行动，让世界对他的行为有所响应。{fate_context}。如果命运骰子对你有利，世界保持平稳；如果不利，请描述一个符合风险等级的挑战或变故。{inject_text}输出JSON格式。",
        "protagonist_memory": memory_text,
        "chat_history_summary": chat_summary,
        "long_context": long_context,
        "fate_event": {"type": fate[0], "severity": fate[1]} if fate[0] != "neutral" else None,
        "current_time": world.get("time"),
        "current_region": current_region,
        "region_info": current_region_info(world),
        "factions_summary": [
            {"name": f.get("name", ""), "power": f.get("power_level", ""), "leader": f.get("leader")}
            for f in relevant_factions
        ],
        "pending_events": pending_events,
        "active_events": active_events_pruned,
        "current_round": world_meta.get("current_round", 0),
    }, ensure_ascii=False)

    return world, user_prompt, system_prompt



def run_world_engine(api_key: str, base_url: str, model: str) -> dict:
    _, user_prompt, system_prompt = _build_world_engine_prompt()
    return normalize_agent_output(
        call_deepseek(system_prompt, user_prompt, api_key=api_key, base_url=base_url, model=model, max_tokens=2048),
        fallback_key="reasoning",
    )


def run_world_engine_stream(api_key: str, base_url: str, model: str):
    """流式版本：yield ('token', text) 或 ('done', output_dict)"""
    _, user_prompt, system_prompt = _build_world_engine_prompt()
    full_text = ""
    for token in call_deepseek_stream(system_prompt, user_prompt, api_key=api_key,
                                       base_url=base_url, model=model, max_tokens=2048):
        full_text += token
        yield ("token", token)
    output = normalize_agent_output(full_text, fallback_key="reasoning")
    yield ("done", output)


def apply_world_output(output: dict) -> dict:
    output = normalize_agent_output(output, fallback_key="reasoning")

    def apply(world):
        # Always advance time and round, even if LLM doesn't include time_advancement
        t = ensure_dict(output.get("time_advancement", {}))
        if isinstance(t, dict) and "day" in t:
            world["time"].update(t)
        else:
            world["time"]["day"] += 1
            if world["time"]["day"] > 30:
                world["time"]["day"] = 1
                world["time"]["month"] += 1
                if world["time"]["month"] > 12:
                    world["time"]["month"] = 1
                    world["time"]["year"] += 1

        world["meta"]["current_round"] += 1
        world["meta"]["total_rounds"] = world["meta"]["current_round"]

        if "triggered_events" in output:
            for evt in ensure_list_of_dicts(output.get("triggered_events")):
                eid = evt.get("id", "")
                for pe in list(world["global_events"].get("pending", [])):
                    if isinstance(pe, dict) and pe.get("id") == eid:
                        pe["status"] = "active"
                        world["global_events"].setdefault("active", []).append(pe)
                        world["global_events"]["pending"].remove(pe)

        if isinstance(output.get("faction_movements"), list):
            world["_last_faction_movements"] = output["faction_movements"]

        world["meta"]["updated_at"] = output.get("timestamp", "")
        return world

    world = update_json(config.STATE_DIR, "world.json", apply)

    if "relationship_changes" in output and output["relationship_changes"]:
        def apply_rels(rels):
            rels.setdefault("relations", [])
            for change in ensure_list_of_dicts(output.get("relationship_changes")):
                rels["relations"].append(change)
            return rels
        update_json(config.STATE_DIR, "relationships.json", apply_rels, {"relations": []})

    return world
