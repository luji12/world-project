"""Backup-first migration/reset helpers for pre-Canon worlds."""

from __future__ import annotations

import json
import os
import shutil
import time
from typing import Any

import config
from canon_engine import (
    canonicalize_world_package,
    compile_canon_from_world_package,
    now_iso,
    write_canon_files,
)
from state import write_json


RUNTIME_DIRS = ["state", "memory", "chronicle", "npc-cards"]
RUNTIME_FILES = ["chat_history.json", "story-ledger.sqlite3"]


def _safe_world_name(name: str) -> str:
    return "".join(ch for ch in name if ch.isalnum() or ch in "._-\u4e00-\u9fff").strip()


def backup_world(world_name: str) -> str:
    safe = _safe_world_name(world_name)
    if not safe:
        raise ValueError("世界名称无效")
    src = os.path.join(config.WORLDS_DIR, safe)
    if not os.path.isdir(src):
        raise FileNotFoundError(f"世界不存在：{world_name}")
    archives = os.path.join(config.WORLDS_DIR, "_archives")
    os.makedirs(archives, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(archives, f"{safe}-pre-canon-{stamp}")
    shutil.copytree(src, dst)
    return dst


def find_source_for_world(world_name: str) -> tuple[str, str]:
    world_path = os.path.join(config.WORLDS_DIR, world_name)
    candidates = [
        (os.path.join(world_path, "canon", "source.md"), "canon/source.md"),
        (os.path.join(world_path, f"{world_name}.md"), f"{world_name}.md"),
        (os.path.join(world_path, "world-framework.md"), "world-framework.md"),
    ]
    for path, label in candidates:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
            if text.strip():
                return text, label
    return f"# {world_name}\n\n（旧世界未找到原始脚本，Canon Engine 只能从世界名生成最小框架。）\n", "fallback"


def _minimal_package_from_source(world_name: str, source_text: str) -> dict[str, Any]:
    return {
        "name": world_name,
        "world_type": "自定义",
        "world_summary": source_text[:4000],
        "playable_characters": [{
            "id": "player",
            "name": "主角",
            "core_motivation": "在 Canon 约束下推进故事",
            "region": "起始地区",
            "has_system": False,
        }],
        "npcs": [],
        "world_state": {
            "world_name": world_name,
            "time": {"year": 1, "month": 1, "day": 1, "hour": 8, "period": "清晨", "era": "元年", "dynasty": ""},
            "geography": {"current_region": "", "regions": {}},
            "factions": [],
            "global_events": [],
        },
    }


def reset_world_from_canon(
    world_name: str,
    *,
    source_text: str | None = None,
    source_name: str = "",
    world_package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Backup and rebuild runtime state from Canon.

    The world directory remains, but runtime state, memories, chronicle, NPC
    cards, chat history and ledger are cleared after a full backup is created.
    """
    safe = _safe_world_name(world_name)
    if not safe:
        raise ValueError("世界名称无效")
    world_path = os.path.join(config.WORLDS_DIR, safe)
    if not os.path.isdir(world_path):
        raise FileNotFoundError(f"世界不存在：{world_name}")

    backup_path = backup_world(safe)
    if source_text is None:
        source_text, source_name = find_source_for_world(safe)
    world_package = world_package or _minimal_package_from_source(safe, source_text)
    compiled = compile_canon_from_world_package(world_package, source_text, source_name)
    package = canonicalize_world_package(world_package, compiled)

    for dirname in RUNTIME_DIRS:
        target = os.path.join(world_path, dirname)
        if os.path.exists(target):
            shutil.rmtree(target)
        os.makedirs(target, exist_ok=True)
    for filename in RUNTIME_FILES:
        target = os.path.join(world_path, filename)
        if os.path.exists(target):
            os.remove(target)

    write_canon_files(world_path, compiled)

    ws = package["world_state"]
    init_world = {
        "meta": {
            "world_name": ws.get("world_name", safe),
            "world_type": package.get("world_type", "自定义"),
            "version": "0.6.0-canon",
            "total_rounds": 0,
            "current_round": 0,
            "updated_at": now_iso(),
        },
        "time": ws.get("time", {"year": 1, "month": 1, "day": 1, "hour": 8, "period": "清晨", "era": "元年", "dynasty": ""}),
        "geography": ws.get("geography", {}),
        "factions": ws.get("factions", []),
        "global_events": {"active": [], "pending": ws.get("global_events", []), "completed": []},
    }
    write_json(os.path.join(world_path, "state"), "world.json", init_world)
    player = (package.get("playable_characters") or [{}])[0]
    write_json(os.path.join(world_path, "state"), "protagonist.json", {
        "id": player.get("id", "player"),
        "name": player.get("name", "主角"),
        "realm": player.get("realm", "凡人"),
        "attributes": {},
        "skills": [],
        "inventory": [],
        "action_log": [],
        "_risk": 5,
        "player_controlled": True,
    })
    write_json(os.path.join(world_path, "state"), "characters.json", {"characters": package.get("npcs", [])})
    write_json(os.path.join(world_path, "state"), "quests.json", {"active": [], "completed": [], "failed": [], "templates": []})
    write_json(os.path.join(world_path, "state"), "relationships.json", {"relations": []})
    write_json(os.path.join(world_path, "state"), "npc_agents.json", {"version": "0.6.0-canon", "updated_round": 0, "agents": []})
    write_json(os.path.join(world_path, "memory"), "index.json", {"recent": [], "medium": [], "milestones": []})

    with open(os.path.join(world_path, "chronicle", "volume-01.md"), "w", encoding="utf-8") as handle:
        handle.write(f"# {safe} — 第一卷\n\n*（已按 Canon 重开，叙事尚未开始。）*\n")
    with open(os.path.join(world_path, "chronicle", "timeline.md"), "w", encoding="utf-8") as handle:
        handle.write("# 叙事时间线\n\n")

    report = {
        "status": "reset",
        "world": safe,
        "backup_path": backup_path,
        "source_name": source_name,
        "reset_at": now_iso(),
        "cleared": RUNTIME_DIRS + RUNTIME_FILES,
    }
    os.makedirs(os.path.join(world_path, "canon"), exist_ok=True)
    with open(os.path.join(world_path, "canon", "migration_report.json"), "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    return report
