import json
import os
import threading

_locks = {}
_lock_registry = threading.Lock()

def _get_lock(path: str) -> threading.Lock:
    with _lock_registry:
        if path not in _locks:
            _locks[path] = threading.Lock()
        return _locks[path]

def read_json(dir_path: str, filename: str) -> dict:
    filepath = os.path.join(dir_path, filename)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        raise ValueError(f"读取文件失败 {filepath}: {e}")

def write_json(dir_path: str, filename: str, data):
    lock = _get_lock(os.path.join(dir_path, filename))
    with lock:
        filepath = os.path.join(dir_path, filename)
        os.makedirs(dir_path, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

def update_json(dir_path: str, filename: str, updater, default=None):
    """Atomically read, update, and write a JSON file under one file lock."""
    filepath = os.path.join(dir_path, filename)
    lock = _get_lock(filepath)
    with lock:
        os.makedirs(dir_path, exist_ok=True)
        data = default if default is not None else {}
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except json.JSONDecodeError:
                data = default if default is not None else {}
        next_data = updater(data)
        if next_data is None:
            next_data = data
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(next_data, f, ensure_ascii=False, indent=2)
        return next_data

def read_text(dir_path: str, filename: str) -> str:
    filepath = os.path.join(dir_path, filename)
    if not os.path.exists(filepath):
        return ""
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()

def append_text(dir_path: str, filename: str, text: str):
    filepath = os.path.join(dir_path, filename)
    lock = _get_lock(filepath)
    with lock:
        os.makedirs(dir_path, exist_ok=True)
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(text)

def write_text(dir_path: str, filename: str, text: str):
    filepath = os.path.join(dir_path, filename)
    lock = _get_lock(filepath)
    with lock:
        os.makedirs(dir_path, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(text)


# ── 注入系统 ──

def get_pending_injections() -> list:
    import config
    try:
        data = read_json(config.STATE_DIR, "_pending_injections.json")
        return data.get("injections", [])
    except Exception:
        return []

def add_injection(text: str):
    import config
    try:
        world = read_json(config.STATE_DIR, "world.json")
        current_round = world.get("meta", {}).get("current_round", 0)
    except Exception:
        current_round = 0
    def apply(data):
        injections = data.get("injections", [])
        injections.append({"text": text, "created_round": current_round, "applied": False})
        data["injections"] = injections
        return data
    update_json(config.STATE_DIR, "_pending_injections.json", apply, {"injections": []})

def clear_applied_injections():
    import config
    def apply(data):
        data["injections"] = [i for i in data.get("injections", []) if not i.get("applied")]
        return data
    update_json(config.STATE_DIR, "_pending_injections.json", apply, {"injections": []})


# ── 玩家角色 ──

def get_player_character() -> dict:
    player = None
    import config
    try:
        chars = read_json(config.STATE_DIR, "characters.json")
        for c in chars.get("characters", []):
            if c.get("player_controlled"):
                player = dict(c)
                break
    except Exception:
        pass
    try:
        p = read_json(config.STATE_DIR, "protagonist.json")
        if player:
            merged = dict(player)
            for key in [
                "name", "realm", "attributes", "skills", "inventory", "action_log",
                "_risk", "has_system", "system_name", "backstory", "personality",
                "personality_profile", "_current_location",
            ]:
                if key in p:
                    merged[key] = p[key]
            return merged
        return {
            "name": p.get("name") or p.get("meta", {}).get("name", "主角"),
            "id": p.get("id", "protagonist"),
            "player_controlled": True,
            "has_system": p.get("has_system", True),
            "system_name": p.get("system_name", "系统"),
            "realm": p.get("realm") or p.get("cultivation", {}).get("realm", "凡人"),
            "backstory": p.get("backstory", ""),
            "personality_profile": p.get("personality_profile", {}),
            "action_log": p.get("action_log", []),
            "attributes": p.get("attributes", {}),
            "skills": p.get("skills", []),
            "inventory": p.get("inventory", []),
            "_risk": p.get("_risk", 0),
        }
    except Exception:
        return player

def get_player_memory_id() -> str:
    player = get_player_character() or {}
    return player.get("id") or "protagonist"

def get_player_name(default="主角") -> str:
    player = get_player_character() or {}
    return player.get("name") or default

def sync_player_character_state(protagonist_state: dict = None):
    """Mirror mutable protagonist state onto the selected character card."""
    import config
    try:
        p = protagonist_state or read_json(config.STATE_DIR, "protagonist.json")
    except Exception:
        return

    def apply(chars):
        updated = False
        for c in chars.get("characters", []):
            if not c.get("player_controlled"):
                continue
            for key in [
                "name", "realm", "attributes", "skills", "inventory", "action_log",
                "_risk", "has_system", "system_name", "backstory", "personality",
                "personality_profile", "_current_location",
            ]:
                if key in p:
                    c[key] = p[key]
            updated = True
            break
        return chars if updated else chars

    try:
        update_json(config.STATE_DIR, "characters.json", apply, {"characters": []})
    except Exception:
        pass
