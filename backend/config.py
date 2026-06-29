import os
import json

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORLDS_DIR = os.path.join(PROJECT_ROOT, "worlds")


def _write_json(dir_path, filename, data):
    os.makedirs(dir_path, exist_ok=True)
    path = os.path.join(dir_path, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _write_text(dir_path, filename, text):
    os.makedirs(dir_path, exist_ok=True)
    with open(os.path.join(dir_path, filename), "w", encoding="utf-8") as f:
        f.write(text)


def _ensure_world_scaffold(name):
    """Create the minimum files a world needs if it only has a folder."""
    world_path = os.path.join(WORLDS_DIR, name)
    for sub in ["state", "chronicle", "npc-cards", "memory", "config", "system"]:
        os.makedirs(os.path.join(world_path, sub), exist_ok=True)

    meta_path = os.path.join(world_path, "world.json")
    if not os.path.exists(meta_path):
        _write_json(world_path, "world.json", {
            "name": name,
            "type": "自定义",
            "created": "",
            "description": "自动初始化的世界",
        })

    state_path = os.path.join(world_path, "state")
    if not os.path.exists(os.path.join(state_path, "world.json")):
        _write_json(state_path, "world.json", {
            "meta": {"world_name": name, "version": "0.1.0", "total_rounds": 0, "current_round": 0},
            "time": {"year": 1, "month": 1, "day": 1, "hour": 8, "period": "清晨", "era": "元年", "dynasty": ""},
            "geography": {"current_region": "main", "regions": {}},
            "factions": [],
            "global_events": {"active": [], "pending": [], "completed": []},
        })
    if not os.path.exists(os.path.join(state_path, "protagonist.json")):
        _write_json(state_path, "protagonist.json", {
            "name": "主角",
            "realm": "凡人",
            "attributes": {},
            "skills": [],
            "inventory": [],
            "action_log": [],
            "_risk": 5,
        })
    if not os.path.exists(os.path.join(state_path, "characters.json")):
        _write_json(state_path, "characters.json", {"characters": []})
    if not os.path.exists(os.path.join(state_path, "quests.json")):
        _write_json(state_path, "quests.json", {"active": [], "completed": [], "failed": [], "templates": []})
    if not os.path.exists(os.path.join(state_path, "relationships.json")):
        _write_json(state_path, "relationships.json", {"relations": []})
    if not os.path.exists(os.path.join(state_path, "npc_agents.json")):
        _write_json(state_path, "npc_agents.json", {"version": "0.1", "updated_round": 0, "agents": []})

    memory_path = os.path.join(world_path, "memory")
    if not os.path.exists(os.path.join(memory_path, "index.json")):
        _write_json(memory_path, "index.json", {"recent": [], "medium": [], "milestones": []})

    config_path = os.path.join(world_path, "config")
    if not os.path.exists(os.path.join(config_path, "system-personality.json")):
        _write_json(config_path, "system-personality.json", {
            "type": "世界同行者",
            "name": "系统",
            "speech_patterns": {},
            "task_generation_philosophy": {},
        })
    if not os.path.exists(os.path.join(config_path, "world-setting.json")):
        _write_json(config_path, "world-setting.json", {"world_type": "自定义", "era": "自定义", "themes": []})
    if not os.path.exists(os.path.join(config_path, "agent-constraints.json")):
        _write_json(config_path, "agent-constraints.json", {"version": "0.1.0", "global_constraints": {}, "agents": {}})

    chronicle_path = os.path.join(world_path, "chronicle")
    if not os.path.exists(os.path.join(chronicle_path, "volume-01.md")):
        _write_text(chronicle_path, "volume-01.md", f"# {name} — 第一卷\n\n*（叙事尚未开始。）*\n")
    if not os.path.exists(os.path.join(chronicle_path, "timeline.md")):
        _write_text(chronicle_path, "timeline.md", "# 叙事时间线\n\n")
    if not os.path.exists(os.path.join(world_path, "world-framework.md")):
        _write_text(world_path, "world-framework.md", f"# {name} — 世界框架\n\n（待补充）\n")


def _read_current():
    path = os.path.join(WORLDS_DIR, "_current")
    if os.path.exists(path):
        with open(path) as f:
            name = f.read().strip()
        if not name:
            return ""
        if os.path.isdir(os.path.join(WORLDS_DIR, name)):
            _ensure_world_scaffold(name)
            return name
        _write_current("")
        return ""
    # List worlds directory
    try:
        entries = [d for d in os.listdir(WORLDS_DIR)
                   if os.path.isdir(os.path.join(WORLDS_DIR, d))
                   and not d.startswith(".") and not d.startswith("_")]
    except FileNotFoundError:
        os.makedirs(WORLDS_DIR, exist_ok=True)
        entries = []
    if entries:
        name = entries[0]
        _ensure_world_scaffold(name)
        _write_current(name)
        return name
    # No worlds exist — return empty
    return ""


def _write_current(name):
    os.makedirs(WORLDS_DIR, exist_ok=True)
    with open(os.path.join(WORLDS_DIR, "_current"), "w") as f:
        f.write(name)


def current_world_name():
    return _read_current()


def switch_world(name):
    _write_current(name)


def world_dir():
    return os.path.join(WORLDS_DIR, _read_current())


def state_dir():
    return os.path.join(world_dir(), "state")


def chronicle_dir():
    return os.path.join(world_dir(), "chronicle")


def memory_dir():
    return os.path.join(world_dir(), "memory")


def npc_dir():
    return os.path.join(world_dir(), "npc-cards")


def config_dir():
    return os.path.join(world_dir(), "config")


def system_dir():
    return os.path.join(world_dir(), "system")


_LAZY_PATHS = {
    "STATE_DIR": state_dir,
    "NPC_DIR": npc_dir,
    "MEMORY_DIR": memory_dir,
    "CHRONICLE_DIR": chronicle_dir,
    "CONFIG_DIR": config_dir,
    "SYSTEM_DIR": system_dir,
}


def __getattr__(name):
    if name in _LAZY_PATHS:
        return _LAZY_PATHS[name]()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def refresh_paths():
    """No-op kept for backward compatibility; paths are now lazily resolved."""
