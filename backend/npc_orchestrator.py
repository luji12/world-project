import json
import os
from state import read_json, write_json, update_json, get_player_character
import config
from canon_context import build_canon_packet
from agent_templates import get_agent_config
from agents.base import normalize_agent_output, ensure_list_of_dicts
from world_shape import current_region_id, current_region_info
from memory_manager import add_memory, init_character_memory

CORE_NPC_LIMIT = 8
SCENE_NPC_LIMIT = 15
BATCH_SIZE = 5
PLAYER_VISIBLE_VISIBILITIES = {"direct", "overheard", "public_observed", "public"}
PRIVATE_VISIBILITIES = {"private", "secret", "internal", "background", "offscreen"}
PRIVATE_SIGNAL_WORDS = (
    "暗中", "心中", "心想", "默想", "隐于", "云端", "窥视", "推算", "密谋",
    "秘密", "背地", "无人知", "未被察觉", "远处", "内心", "独自", "自言自语",
)
DIRECT_SIGNAL_WORDS = ("你", "您", "叶然", "叶公子", "叶大哥", "病秧子", "道友", "公子", "少侠")


def _get_world_context():
    try:
        world = read_json(config.STATE_DIR, "world.json")
    except Exception:
        world = {}
    world_meta = world.get("meta", {})
    agent_cfg = get_agent_config(world_meta)
    wt = world_meta.get("world_type", "xuanhuan")
    narrator_role = agent_cfg.get("narrator", {}).get("role", "小说家")
    we_role = agent_cfg.get("world_engine", {}).get("role", "故事世界")
    return world, wt, narrator_role, we_role


def _npc_lookup(active_npcs: list) -> dict:
    lookup = {}
    for item in active_npcs or []:
        c = item.get("character") if isinstance(item, dict) else item
        if not isinstance(c, dict):
            continue
        for key in (c.get("name"), c.get("id")):
            if key:
                lookup[str(key)] = c
    return lookup


def _looks_private(action: dict) -> bool:
    text = f"{action.get('action', '')}\n{action.get('dialogue', '')}\n{action.get('reasoning', '')}"
    return any(word in text for word in PRIVATE_SIGNAL_WORDS)


def _looks_direct(action: dict) -> bool:
    dialogue = str(action.get("dialogue", "") or "")
    action_text = str(action.get("action", "") or "")
    if dialogue and any(word in dialogue for word in DIRECT_SIGNAL_WORDS):
        return True
    return bool(action_text and any(word in action_text for word in ("递给", "走到", "端着", "推门", "房门前", "对着")))


def normalize_npc_action_visibility(action: dict, active_npcs: list | None = None) -> dict:
    """Fill stable player-visibility fields for an NPC action.

    The world may simulate private NPC behavior, but the chat UI should only
    receive actions the protagonist could plausibly perceive.
    """
    if not isinstance(action, dict):
        return {}
    normalized = dict(action)
    npc_name = str(normalized.get("npc") or normalized.get("npc_name") or "")
    lookup = _npc_lookup(active_npcs or [])
    npc = lookup.get(npc_name, {})
    if npc and not normalized.get("npc_id"):
        normalized["npc_id"] = npc.get("id", "")

    raw_visibility = str(normalized.get("visibility") or "").strip().lower()
    explicit_observed = normalized.get("observed_by_player")
    explicit_exposed = normalized.get("exposed_to_player")

    if isinstance(explicit_exposed, bool):
        exposed = explicit_exposed
    elif isinstance(explicit_observed, bool):
        exposed = explicit_observed
    elif raw_visibility in PRIVATE_VISIBILITIES:
        exposed = False
    elif raw_visibility in PLAYER_VISIBLE_VISIBILITIES:
        exposed = True
    else:
        exposed = _looks_direct(normalized) and not _looks_private(normalized)

    if not raw_visibility:
        raw_visibility = "direct" if exposed else "private"

    normalized["visibility"] = raw_visibility
    normalized["observed_by_player"] = bool(exposed)
    normalized["exposed_to_player"] = bool(exposed)
    if not normalized.get("audience"):
        normalized["audience"] = ["player"] if exposed else []
    return normalized


def is_player_visible_action(action: dict) -> bool:
    if not isinstance(action, dict):
        return False
    if action.get("exposed_to_player") is False or action.get("observed_by_player") is False:
        return False
    visibility = str(action.get("visibility") or "").strip().lower()
    if visibility in PRIVATE_VISIBILITIES:
        return False
    if visibility in PLAYER_VISIBLE_VISIBILITIES:
        return True
    return _looks_direct(action) and not _looks_private(action)


def _score_npc(c, current_region, active_events, protagonist):
    score = 0
    loc = c.get("location") or c.get("region") or ""

    if loc.startswith(current_region) or c.get("region") == current_region:
        score += 4
    elif current_region and (current_region in loc or loc in current_region):
        score += 1

    for evt in active_events:
        evt_text = json.dumps(evt, ensure_ascii=False)
        if c.get("id", "") in evt_text or c.get("name", "") in evt_text:
            score += 3
            break

    action_log = protagonist.get("action_log", [])
    if action_log:
        recent_actions = " ".join(a.get("action", "") for a in action_log[-3:])
        if c.get("name", "") in recent_actions:
            score += 3

    if c.get("_last_interaction_round", 0) > 0:
        score += 1

    if c.get("role") and any(kw in c.get("role", "") for kw in ["店主", "长老", "守卫", "师傅", "对手", "朋友"]):
        score += 1

    return score


def get_active_npcs() -> dict:
    """返回三层NPC结构：core（核心近景）、scene（场景中景）、background（远景，仅描述）"""
    try:
        world = read_json(config.STATE_DIR, "world.json")
    except Exception:
        return {"core": [], "scene": []}
    try:
        chars = read_json(config.STATE_DIR, "characters.json")
    except Exception:
        return {"core": [], "scene": []}
    protagonist = get_player_character() or {}

    current_region = current_region_id(world)
    active_events = world.get("global_events", {}).get("active", [])
    lifecycle_registry_present = os.path.exists(os.path.join(config.STATE_DIR, "npc_agents.json"))
    try:
        from npc_lifecycle import read_npc_agents
        registry = read_npc_agents()
        registry_agents = registry.get("agents", []) if isinstance(registry.get("agents"), list) else []
    except Exception:
        registry_agents = []

    if lifecycle_registry_present:
        if not registry_agents:
            return {"core": [], "scene": []}
        by_id = {
            str(c.get("id") or c.get("name")): c for c in chars.get("characters", [])
            if isinstance(c, dict) and not c.get("player_controlled") and c.get("status") not in {"死亡", "dead"}
        }
        scored = []
        for index, agent in enumerate(registry_agents):
            if not isinstance(agent, dict):
                continue
            npc_id = str(agent.get("npc_id", ""))
            c = by_id.get(npc_id)
            if not c:
                continue
            score = 100 - index
            if agent.get("role_in_scene") in {"核心", "core"} or c.get("story_importance") == "core":
                score += 20
            scored.append({"character": c, "score": score, "agent": agent})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return {"core": scored[:CORE_NPC_LIMIT], "scene": scored[CORE_NPC_LIMIT:CORE_NPC_LIMIT + SCENE_NPC_LIMIT]}

    scored = []
    for c in chars.get("characters", []):
        if c.get("player_controlled") or c.get("status") == "死亡":
            continue
        score = _score_npc(c, current_region, active_events, protagonist)
        if score > 0:
            scored.append({"character": c, "score": score})

    scored.sort(key=lambda x: x["score"], reverse=True)

    core = scored[:CORE_NPC_LIMIT]
    scene = scored[CORE_NPC_LIMIT:CORE_NPC_LIMIT + SCENE_NPC_LIMIT]

    return {"core": core, "scene": scene}


def build_core_prompt(core_npcs: list) -> str:
    """为核心NPC构建详细prompt，包含性格、欲望、记忆等"""
    world, wt, narrator_role, we_role = _get_world_context()
    try:
        protagonist = get_player_character() or {}
    except Exception:
        protagonist = {}

    npc_descriptions = []
    for item in core_npcs:
        c = item["character"]
        name = c.get('name', '')
        role = c.get('role', '')
        realm = c.get('realm', '凡人')
        location = c.get('location', c.get('region', ''))
        personality = (c.get('personality', '') or '')[:80]
        secret = c.get('secret', '')[:60]
        desires = c.get('desires', [])
        desire_str = "; ".join(str(d)[:30] for d in desires[:3]) if desires else '无明确目标'
        last_action = c.get('_last_action', '')
        desc = f"{name}({role},{realm},在{location}): 性格{personality}。秘密:{secret}。欲望:{desire_str}。上次行动:{last_action}。"
        npc_descriptions.append(desc)

    protagonist_name = protagonist.get("name") or protagonist.get("meta", {}).get("name", "主角")
    protagonist_realm = protagonist.get("realm") or protagonist.get("cultivation", {}).get("realm", "凡人")
    protagonist_last_action = ""
    action_log = protagonist.get("action_log", [])
    if action_log:
        protagonist_last_action = action_log[-1].get("action", "")

    region_info = current_region_info(world)
    region_name = region_info.get("name", "未知地区")
    canon_packet = build_canon_packet("npc-agents")

    return json.dumps({
        "instruction": f"你是{narrator_role}笔下{we_role}的场景导演。当前世界类型为{wt}。主角{protagonist_name}（{protagonist_realm}）刚{protagonist_last_action or '来到此处'}。以下是场景中最重要的{len(core_npcs)}个角色，请为每人决定本轮行为和对话。只有主角能亲眼看见、亲耳听见、或被NPC直接接触的内容才标记为direct/overheard/public_observed；暗中谋划、内心想法、远处行动、上帝视角信息必须标记为private/secret/internal，不要写成给玩家看的台词。所有术语、行为、对话风格必须符合{wt}世界观。",
        "canon_packet": canon_packet,
        "scene": {
            "time": world.get("time"),
            "region": region_name,
            "atmosphere": world.get("_last_scene_atmosphere", ""),
        },
        "npcs": npc_descriptions,
        "active_events": [e.get("name", "") for e in world.get("global_events", {}).get("active", [])],
        "output_format": {
            "npc_actions": [
                {"npc": "角色名", "action": "做了什么（2-3句话，要有细节）", "dialogue": "玩家可听见的具体台词；私密行动则为空字符串", "emotion": "情绪状态", "visibility": "direct|overheard|public_observed|private|secret|internal|background", "observed_by_player": True, "audience": ["player"], "memory_note": "写入该NPC记忆的简短记录"}
            ],
            "scene_atmosphere": "本轮场景氛围"
        }
    }, ensure_ascii=False)


def build_scene_batch_prompt(scene_npcs: list) -> str:
    """为场景层NPC构建批量简化prompt"""
    world, wt, narrator_role, we_role = _get_world_context()
    try:
        protagonist = get_player_character() or {}
    except Exception:
        protagonist = {}

    npc_descriptions = []
    for item in scene_npcs:
        c = item["character"]
        name = c.get('name', '')
        role = c.get('role', '')
        realm = c.get('realm', '凡人')
        location = c.get('location', c.get('region', ''))
        personality = (c.get('personality', '') or '')[:25]
        desc = f"{name}({role},{realm},在{location}): {personality}。"
        npc_descriptions.append(desc)

    protagonist_name = protagonist.get("name") or protagonist.get("meta", {}).get("name", "主角")

    region_info = current_region_info(world)
    region_name = region_info.get("name", "未知地区")
    canon_packet = build_canon_packet("npc-agents")

    return json.dumps({
        "instruction": f"你是{narrator_role}笔下{we_role}的群演导演。当前世界类型为{wt}。主角{protagonist_name}在{region_name}，以下是周围的次要角色。为每人简要描述本轮行为，一两句话即可。只有主角能感知的行为才标记direct/overheard/public_observed；远处、背地、心理活动标记private/secret/internal，不要主动暴露给玩家。行为要符合{wt}世界观。",
        "canon_packet": canon_packet,
        "npcs": npc_descriptions,
        "output_format": {
            "npc_actions": [
                {"npc": "角色名", "action": "简要行为（1句话）", "dialogue": "玩家可听见的简短台词或空字符串", "visibility": "direct|overheard|public_observed|private|secret|internal|background", "observed_by_player": True, "audience": ["player"], "memory_note": "写入该NPC记忆的简短记录"}
            ]
        }
    }, ensure_ascii=False)


def build_batch_prompt(active_npcs: list) -> str:
    """Legacy compatibility: build prompt from a flat list of NPCs"""
    world, wt, narrator_role, we_role = _get_world_context()
    try:
        protagonist = get_player_character() or {}
    except Exception:
        protagonist = {}

    npc_descriptions = []
    for item in active_npcs:
        c = item["character"] if isinstance(item, dict) and "character" in item else item
        name = c.get('name', '')
        role = c.get('role', '')
        realm = c.get('realm', '凡人')
        location = c.get('location', c.get('region', ''))
        personality = (c.get('personality', '') or '')[:30]
        desires = c.get('desires', [])
        desire_str = desires[0][:20] if desires else '无'
        desc = f"{name}({role},{realm},在{location}): {personality}。欲{desire_str}。"
        npc_descriptions.append(desc)

    protagonist_name = protagonist.get("name") or protagonist.get("meta", {}).get("name", "主角")
    protagonist_realm = protagonist.get("realm") or protagonist.get("cultivation", {}).get("realm", "凡人")

    region_info = current_region_info(world)
    region_name = region_info.get("name", "未知地区")

    return json.dumps({
        "instruction": f"你是{narrator_role}笔下{we_role}的场景导演。当前世界类型为{wt}。主角{protagonist_name}（{protagonist_realm}）正在行动。请为在场的每个NPC决定他们这一轮做什么。每个NPC的行为必须符合其性格、欲望和当前处境。所有行为和对话必须符合{wt}世界观。",
        "scene": {
            "time": world.get("time"),
            "region": region_name,
            "atmosphere": world.get("_last_scene_atmosphere", "平常的一天"),
        },
        "npcs": npc_descriptions,
        "active_events": [e.get("name", "") for e in world.get("global_events", {}).get("active", [])],
        "output_format": {
            "npc_actions": [
                {"npc": "角色名", "action": "做了什么（1-2句话）", "dialogue": "说了什么（如有，否则空字符串）", "reasoning": "为什么这样做"}
            ],
            "interactions": ["角色之间的互动描述"],
            "scene_atmosphere": "本轮场景氛围描述"
        }
    }, ensure_ascii=False)


def apply_npc_output(output: dict, active_npcs: list):
    output = normalize_agent_output(output, fallback_key="scene_atmosphere")
    npc_actions = [
        normalize_npc_action_visibility(action, active_npcs)
        for action in ensure_list_of_dicts(output.get("npc_actions"))
    ]
    if not npc_actions:
        if output.get("scene_atmosphere"):
            try:
                def apply_world(world):
                    world["_last_scene_atmosphere"] = output["scene_atmosphere"]
                    prev = world.get("_last_npc_batch_output", {})
                    prev_npcs = prev.get("npc_actions", []) if isinstance(prev, dict) else []
                    world["_last_npc_batch_output"] = {"npc_actions": prev_npcs, "scene_atmosphere": output["scene_atmosphere"]}
                    return world
                update_json(config.STATE_DIR, "world.json", apply_world)
            except Exception:
                pass
        return

    def apply_chars(chars):
        for action in npc_actions:
            npc_name = action.get("npc")
            for c in chars.get("characters", []):
                if isinstance(c, dict) and c.get("name") == npc_name:
                    c["_last_action"] = action.get("action", "")
                    c["_last_dialogue"] = action.get("dialogue", "")
                    c["_last_visibility"] = action.get("visibility", "")
                    break
        return chars

    try:
        update_json(config.STATE_DIR, "characters.json", apply_chars, {"characters": []})
    except Exception:
        return

    try:
        chars = read_json(config.STATE_DIR, "characters.json")
        char_by_name = {
            c.get("name"): c for c in chars.get("characters", [])
            if isinstance(c, dict) and c.get("name")
        }
        world = read_json(config.STATE_DIR, "world.json")
        round_no = world.get("meta", {}).get("current_round", 0)
        for action in npc_actions:
            npc_name = action.get("npc")
            character = char_by_name.get(npc_name, {})
            char_id = action.get("npc_id") or character.get("id") or npc_name
            if not char_id:
                continue
            init_character_memory(str(char_id), npc_name or str(char_id), "npc")
            note = action.get("memory_note") or action.get("action") or action.get("dialogue")
            if note:
                visibility = action.get("visibility", "private")
                add_memory(str(char_id), {
                    "round": round_no,
                    "content": f"[{visibility}] {note}",
                    "importance": 3 if is_player_visible_action(action) else 4,
                })
    except Exception:
        pass

    if output.get("scene_atmosphere") or True:
        try:
            def apply_world(world):
                if output.get("scene_atmosphere"):
                    world["_last_scene_atmosphere"] = output["scene_atmosphere"]
                prev = world.get("_last_npc_batch_output", {})
                prev_npcs = prev.get("npc_actions", []) if isinstance(prev, dict) else []
                merged = {a.get("npc"): a for a in prev_npcs}
                for a in npc_actions:
                    merged[a.get("npc")] = a
                world["_last_npc_batch_output"] = {"npc_actions": list(merged.values()), "scene_atmosphere": output.get("scene_atmosphere", prev.get("scene_atmosphere", ""))}
                return world
            update_json(config.STATE_DIR, "world.json", apply_world)
        except Exception:
            pass


def get_background_npc_routines() -> str:
    """为不在当前场景的NPC生成纯文本行为描述。基于daily_routine字段，不调LLM。"""
    try:
        world = read_json(config.STATE_DIR, "world.json")
    except Exception:
        return ""
    try:
        chars = read_json(config.STATE_DIR, "characters.json")
    except Exception:
        return ""

    current_region = world.get("geography", {}).get("current_region", "")
    time_period = world.get("time", {}).get("period", "上午")
    layered = get_active_npcs()
    active_names = set()
    for group in (layered.get("core", []), layered.get("scene", [])):
        for a in group:
            active_names.add(a["character"].get("name"))

    lines = []
    for c in chars.get("characters", []):
        if c.get("player_controlled") or c.get("status") == "死亡":
            continue
        if c.get("name") in active_names:
            continue

        routine = c.get("daily_routine", {})
        if isinstance(routine, dict) and routine:
            action = routine.get(time_period, list(routine.values())[0])
        else:
            action = "忙碌自己的事"
        loc = c.get("location", c.get("region", ""))
        lines.append(f"- {c.get('name', '')}（{loc}）：{action}。")

    return "\n".join(lines) if lines else ""


def get_npc_summary_for_chronicler() -> str:
    """合并活跃NPC和背景NPC的行为摘要，供记录员使用"""
    parts = []

    bg = get_background_npc_routines()
    if bg:
        parts.append("【远景角色】\n" + bg)

    try:
        world = read_json(config.STATE_DIR, "world.json")
        last = world.get("_last_npc_batch_output", {})
        actions = last.get("npc_actions", []) if isinstance(last, dict) else []
        if actions:
            parts.append("【近景角色】")
            for a in actions:
                dialogue = f" 说：「{a.get('dialogue', '')}」" if a.get('dialogue') else ""
                parts.append(f"- {a.get('npc', '')}：{a.get('action', '')}{dialogue}")
    except Exception:
        pass

    return "\n".join(parts)
