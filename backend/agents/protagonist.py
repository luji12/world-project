import json
import os
from .base import call_deepseek, call_deepseek_stream, normalize_agent_output
from state import (
    read_json, update_json, get_player_character, get_player_memory_id,
    sync_player_character_state,
)
import config
from memory_manager import get_memory_context, init_character_memory, add_memory, sync_all_characters
from story_context import build_agent_context
from world_shape import current_region_id, current_region_info, landmark_names


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


def _system_prompt(protagonist: dict) -> str:
    name = protagonist.get("name", "主角") if protagonist else "主角"
    personality = protagonist.get("personality") or protagonist.get("personality_profile") or "有真实动机和情绪，会根据处境谨慎行动"
    backstory = protagonist.get("backstory", "")
    motivation = protagonist.get("core_motivation") or protagonist.get("desires", ["活下去并找到自己的道路"])[0]
    return f"""你是{name}。请严格扮演当前世界的玩家角色，不要把自己写成其他人。

角色性格：{personality}
角色背景：{backstory[:300] if backstory else "以当前世界设定为准"}
核心目标：{motivation}

行动需合理渐进，有情感反应。
输出JSON：{{"action":"行动描述","thoughts":"内心想法","location":"位置","emotional_state":"情绪","needs_decision":false,"decision_prompt":"","reasoning":"为什么"}}
needs_decision约3-5轮一次为true，暂停等玩家选择。"""


def run_protagonist(api_key: str, base_url: str, model: str) -> dict:
    world = read_json(config.STATE_DIR, "world.json")
    protagonist = get_player_character()
    quests = read_json(config.STATE_DIR, "quests.json")
    chars = read_json(config.STATE_DIR, "characters.json")

    sync_all_characters()
    action_log = protagonist.get("action_log", [])
    last_action = action_log[-1].get("action", "") if action_log else "刚来到这个世界"
    last_location = action_log[-1].get("location", "") if action_log else ""
    last_emotion = action_log[-1].get("emotional_state", "") if action_log else ""
    search_context = f"行动：{last_action}。位置：{last_location}。情绪：{last_emotion}。"
    memory_text = get_memory_context(get_player_memory_id(), max_items=15, context=search_context)

    current_region = current_region_id(world)
    region_info = current_region_info(world)
    nearby = [c.get("name") for c in chars.get("characters", [])[:5]
              if isinstance(c, dict) and (not current_region or (c.get("location") or c.get("region") or "").startswith(current_region))]

    chat_summary = _read_chat_summary()

    user_prompt = json.dumps({
        "instruction": f"描述{protagonist.get('name', '主角')}今天的行为。像一个真实的人。",
        "memory": memory_text,
        "chat_history_summary": chat_summary,
        "long_context": build_agent_context("protagonist"),
        "time": world.get("time"),
        "region": region_info.get("name", ""),
        "landmarks": landmark_names(region_info),
        "nearby_npcs": nearby,
        "realm": protagonist.get("realm", "凡人"),
        "active_quests": [q.get("name") for q in quests.get("active", [])[:3] if isinstance(q, dict)],
        "active_events": [e.get("name") for e in world.get("global_events", {}).get("active", []) if isinstance(e, dict)],
    }, ensure_ascii=False)

    return normalize_agent_output(
        call_deepseek(_system_prompt(protagonist), user_prompt, api_key=api_key, base_url=base_url, model=model, max_tokens=1024),
        fallback_key="action",
    )


def run_protagonist_stream(api_key: str, base_url: str, model: str):
    """流式版本"""
    world = read_json(config.STATE_DIR, "world.json")
    protagonist = get_player_character()
    quests = read_json(config.STATE_DIR, "quests.json")
    chars = read_json(config.STATE_DIR, "characters.json")
    sync_all_characters()
    action_log = protagonist.get("action_log", [])
    last_action = action_log[-1].get("action", "") if action_log else "刚来到这个世界"
    last_location = action_log[-1].get("location", "") if action_log else ""
    last_emotion = action_log[-1].get("emotional_state", "") if action_log else ""
    search_context = f"行动：{last_action}。位置：{last_location}。情绪：{last_emotion}。"
    memory_text = get_memory_context(get_player_memory_id(), max_items=15, context=search_context)
    current_region = current_region_id(world)
    region_info = current_region_info(world)
    nearby = [c.get("name") for c in chars.get("characters", [])[:5]
              if isinstance(c, dict) and (not current_region or (c.get("location") or c.get("region") or "").startswith(current_region))]
    chat_summary = _read_chat_summary()
    user_prompt = json.dumps({
        "instruction": f"描述{protagonist.get('name', '主角')}今天的行为。像一个真实的人。",
        "memory": memory_text, "time": world.get("time"),
        "chat_history_summary": chat_summary,
        "long_context": build_agent_context("protagonist"),
        "region": region_info.get("name", ""),
        "landmarks": landmark_names(region_info),
        "nearby_npcs": nearby, "realm": protagonist.get("realm", "凡人"),
        "active_quests": [q.get("name") for q in quests.get("active", [])[:3] if isinstance(q, dict)],
        "active_events": [e.get("name") for e in world.get("global_events", {}).get("active", []) if isinstance(e, dict)],
    }, ensure_ascii=False)

    full_text = ""
    for token in call_deepseek_stream(_system_prompt(protagonist), user_prompt, api_key=api_key,
                                       base_url=base_url, model=model, max_tokens=1024):
        full_text += token
        yield ("token", token)
    output = normalize_agent_output(full_text, fallback_key="action")
    yield ("done", output)


def apply_protagonist_output(output: dict):
    output = normalize_agent_output(output, fallback_key="action")
    world = read_json(config.STATE_DIR, "world.json")
    player = get_player_character() or {}
    current_round = world["meta"]["current_round"]

    def apply(protagonist):
        if player.get("name") and not protagonist.get("name"):
            protagonist["name"] = player["name"]
        # Record action — keep only last 5 for context efficiency
        protagonist.setdefault("action_log", []).append({
            "round": current_round,
            "action": output.get("action", ""),
            "thoughts": output.get("thoughts", ""),
            "location": output.get("location", ""),
            "emotional_state": output.get("emotional_state", ""),
        })
        protagonist["action_log"] = protagonist["action_log"][-5:]

        if output.get("location"):
            protagonist["_current_location"] = output.get("location")
        return protagonist

    protagonist = update_json(config.STATE_DIR, "protagonist.json", apply)
    sync_player_character_state(protagonist)

    # Read session api credentials for LLM memory compression
    try:
        import session_config
        api_key, base_url, model = session_config.get_all()
    except Exception:
        api_key, base_url, model = "", "", ""

    # Record memory for protagonist
    mem_text = f"{output.get('action', '')}｜想法：{output.get('thoughts', '')}｜情绪：{output.get('emotional_state', '')}"
    importance = 5 if any(kw in mem_text for kw in ["突破", "战斗", "发现", "决定", "第一次", "秘密", "死亡", "选择"]) else 3
    memory_entry = {
        "round": current_round,
        "content": mem_text[:300],
        "importance": importance,
    }
    memory_id = get_player_memory_id()
    add_memory(memory_id, memory_entry, api_key=api_key, base_url=base_url, model=model)
    if memory_id != "protagonist":
        add_memory("protagonist", memory_entry, api_key=api_key, base_url=base_url, model=model)
