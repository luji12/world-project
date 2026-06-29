import json
import os
from .base import call_deepseek, call_deepseek_stream, normalize_agent_output, ensure_list_of_dicts, ensure_dict
from state import (
    read_json, update_json, get_player_character, get_player_memory_id,
    sync_player_character_state,
)
import config
from memory_manager import get_memory_context, add_memory, sync_all_characters
from agent_templates import get_agent_config, build_system_agent_system_prompt
from story_context import build_agent_context


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


def _system_prompt(protagonist: dict, world_meta: dict) -> str:
    agent_config = get_agent_config(world_meta)
    return build_system_agent_system_prompt(protagonist, agent_config)


def _empty_output(reason: str):
    return {"system_dialogue": "", "quest_updates": [], "rewards": [], "reasoning": reason}


def run_system_agent(api_key: str, base_url: str, model: str) -> dict:
    world = read_json(config.STATE_DIR, "world.json")
    world_meta = world.get("meta", {})
    agent_config = get_agent_config(world_meta)
    protagonist = get_player_character()
    quests = read_json(config.STATE_DIR, "quests.json")
    sys_cfg = agent_config.get("system", {})
    system_enabled = True
    if protagonist:
        system_enabled = protagonist.get("has_system", sys_cfg.get("default_enabled", True))
    else:
        system_enabled = sys_cfg.get("default_enabled", True)
    if not system_enabled:
        return _empty_output("当前世界/角色没有绑定系统，跳过系统推演")

    # ── 惰性检查：无任务变化、无新事件、非首轮时跳过LLM ──
    active_quests = [q for q in quests.get("active", []) if isinstance(q, dict)]
    active_events = [e for e in world.get("global_events", {}).get("active", []) if isinstance(e, dict)]
    pending_events = [e for e in world.get("global_events", {}).get("pending", []) if isinstance(e, dict)]
    is_first_round = world["meta"]["current_round"] <= 1

    has_task_change = False
    if active_quests:
        has_task_change = True
    if active_events:
        has_task_change = True
    if pending_events:
        for pe in pending_events:
            if _check_event_trigger(pe, protagonist, world):
                has_task_change = True
                break

    if not is_first_round and not has_task_change:
        return _empty_output("本轮无任务变更，跳过系统推演")

    # ── 正常 LLM 调用 ──
    personality = read_json(config.CONFIG_DIR, "system-personality.json")

    action_log = protagonist.get("action_log", []) if protagonist else []
    last_actions = action_log[-3:] if action_log else []

    sync_all_characters()
    active_quest_names = [q.get("name", "") for q in quests.get("active", [])]
    search_context = f"当前任务：{', '.join(active_quest_names) if active_quest_names else '无'}。"
    memory_text = get_memory_context(get_player_memory_id(), max_items=10, context=search_context)
    system_memory = get_memory_context("system", max_items=5, context=search_context)

    user_prompt = json.dumps({
        "instruction": f"你是{(protagonist or {}).get('name', '主角')}的AI伙伴。看看其最近做了什么，用朋友的语气聊天。可以吐槽、鼓励、提醒、给建议。",
        "protagonist_memory": memory_text,
        "your_memory": system_memory,
        "chat_history_summary": _read_chat_summary(),
        "long_context": build_agent_context("system-agent"),
        "current_time": world.get("time"),
        "protagonist": {
            "name": protagonist.get("name", "主角") if protagonist else "主角",
            "realm": protagonist.get("realm", "凡人") if protagonist else "凡人",
            "has_system": protagonist.get("has_system", True) if protagonist else True,
            "system_name": protagonist.get("system_name", "系统") if protagonist else "系统",
            "recent_actions": last_actions,
        },
        "world_events": world.get("global_events", {}).get("active", []),
        "pending_events": world.get("global_events", {}).get("pending", []),
        "active_quests": active_quests,
        "quest_templates": [q for q in quests.get("templates", []) if isinstance(q, dict)],
        "system_personality": personality.get("speech_patterns", {}),
    }, ensure_ascii=False)

    return normalize_agent_output(
        call_deepseek(_system_prompt(protagonist, world_meta), user_prompt, api_key=api_key, base_url=base_url, model=model),
        fallback_key="system_dialogue",
    )


def run_system_agent_stream(api_key: str, base_url: str, model: str):
    """流式版本——惰性检查保留"""
    world = read_json(config.STATE_DIR, "world.json")
    world_meta = world.get("meta", {})
    agent_config = get_agent_config(world_meta)
    protagonist = get_player_character()
    quests = read_json(config.STATE_DIR, "quests.json")
    sys_cfg = agent_config.get("system", {})
    system_enabled = True
    if protagonist:
        system_enabled = protagonist.get("has_system", sys_cfg.get("default_enabled", True))
    else:
        system_enabled = sys_cfg.get("default_enabled", True)
    if not system_enabled:
        yield ("done", _empty_output("当前世界/角色没有绑定系统，跳过系统推演"))
        return

    active_quests = [q for q in quests.get("active", []) if isinstance(q, dict)]
    active_events = [e for e in world.get("global_events", {}).get("active", []) if isinstance(e, dict)]
    pending_events = [e for e in world.get("global_events", {}).get("pending", []) if isinstance(e, dict)]
    is_first_round = world["meta"]["current_round"] <= 1
    has_task_change = False
    if active_quests:
        has_task_change = True
    if active_events:
        has_task_change = True
    if not has_task_change and pending_events:
        for pe in pending_events:
            if _check_event_trigger(pe, protagonist, world):
                has_task_change = True
                break

    if not is_first_round and not has_task_change:
        yield ("done", _empty_output("本轮无任务变更，跳过系统推演"))
        return

    personality = read_json(config.CONFIG_DIR, "system-personality.json")
    action_log = protagonist.get("action_log", []) if protagonist else []
    last_actions = action_log[-3:] if action_log else []
    sync_all_characters()
    active_quest_names = [q.get("name", "") for q in quests.get("active", [])]
    search_context = f"当前任务：{', '.join(active_quest_names) if active_quest_names else '无'}。"
    memory_text = get_memory_context(get_player_memory_id(), max_items=10, context=search_context)
    system_memory = get_memory_context("system", max_items=5, context=search_context)

    user_prompt = json.dumps({
        "instruction": f"你是{(protagonist or {}).get('name', '主角')}的AI伙伴。看看其最近做了什么，用朋友的语气聊天。",
        "protagonist_memory": memory_text, "your_memory": system_memory,
        "chat_history_summary": _read_chat_summary(),
        "long_context": build_agent_context("system-agent"),
        "current_time": world.get("time"),
        "protagonist": {
            "name": protagonist.get("name", "主角") if protagonist else "主角",
            "realm": protagonist.get("realm", "凡人") if protagonist else "凡人",
            "recent_actions": last_actions,
        },
        "world_events": active_events, "pending_events": pending_events,
        "active_quests": active_quests,
        "system_personality": personality.get("speech_patterns", {}),
    }, ensure_ascii=False)

    full_text = ""
    for token in call_deepseek_stream(_system_prompt(protagonist, world_meta), user_prompt, api_key=api_key,
                                       base_url=base_url, model=model, max_tokens=1024):
        full_text += token
        yield ("token", token)
    output = normalize_agent_output(full_text, fallback_key="system_dialogue")
    yield ("done", output)


def apply_system_output(output: dict):
    output = normalize_agent_output(output, fallback_key="system_dialogue")

    def apply_quests(quests):
        for upd in ensure_list_of_dicts(output.get("quest_updates")):
            action = upd.get("action", "update")
            if action == "add":
                quest = upd.get("quest", upd)
                if isinstance(quest, dict):
                    quests.setdefault("active", []).append(quest)
            elif action == "complete":
                qid = upd.get("quest_id")
                for q in list(quests.get("active", [])):
                    if isinstance(q, dict) and q.get("id") == qid:
                        quests["active"].remove(q)
                        quests.setdefault("completed", []).append(q)
                        break
            elif action == "fail":
                qid = upd.get("quest_id")
                for q in list(quests.get("active", [])):
                    if isinstance(q, dict) and q.get("id") == qid:
                        quests["active"].remove(q)
                        quests.setdefault("failed", []).append(q)
                        break
        return quests

    if "quest_updates" in output:
        update_json(config.STATE_DIR, "quests.json", apply_quests, {"active": [], "completed": [], "failed": [], "templates": []})

    def apply_rewards(protagonist):
        for reward in ensure_list_of_dicts(output.get("rewards")):
            if reward.get("type") == "exp":
                protagonist["exp"] = protagonist.get("exp", 0) + reward.get("value", 0)
            elif reward.get("type") == "item":
                protagonist.setdefault("inventory", []).append(reward)
        return protagonist

    if "rewards" in output:
        protagonist = update_json(config.STATE_DIR, "protagonist.json", apply_rewards)
        sync_player_character_state(protagonist)

    # Record system memory
    dialogue = output.get("system_dialogue", "")
    if dialogue:
        world = read_json(config.STATE_DIR, "world.json")
        player_name = (get_player_character() or {}).get("name", "主角")
        add_memory("system", {
            "round": world["meta"]["current_round"],
            "content": f"系统对{player_name}说：{dialogue[:200]}",
            "importance": 3,
        })


def _check_event_trigger(event: dict, protagonist: dict, world: dict) -> bool:
    """检查世界事件触发条件是否满足"""
    event = ensure_dict(event)
    trigger = event.get("trigger_condition", "")
    if not trigger:
        return False
    realm = (protagonist or {}).get("realm", "凡人")

    if "达到" in trigger and ("等级" in trigger or "修为" in trigger or "境界" in trigger or "阶位" in trigger):
        target = trigger.split("达到")[-1].strip() if "达到" in trigger else ""
        return target in realm

    if "炼气" in trigger or "筑基" in trigger or "金丹" in trigger:
        return trigger in realm

    if "时间推进至" in trigger:
        target = trigger.split("至")[-1].strip() if "至" in trigger else ""
        current = f"{world['time']['year']}年{world['time']['month']}月"
        return current == target

    return False
