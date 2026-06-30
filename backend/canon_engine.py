"""Canon data layer for world scripts, story rails, and hard constraints.

The Canon Engine turns a user supplied script/world package into stable files
under ``worlds/<world>/canon``.  It is intentionally deterministic: LLMs may
help create the initial ``world_package``, but once a world exists every agent
can reload the same Canon packet and validate against it.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import time
from typing import Any

import config
from outline_engine import (
    LEDGER_FILE,
    OUTLINE_FILE,
    compile_story_outline,
    detect_start_location,
    extract_location_names,
    extract_world_name,
    initial_beat_ledger,
)


CANON_VERSION = 2
CANON_FILES = {
    "source": "source.md",
    "bible": "world_bible.json",
    "arcs": "story_arcs.json",
    "outline": OUTLINE_FILE,
    "beat_ledger": LEDGER_FILE,
    "constraints": "constraints.json",
    "source_map": "source_map.json",
    "conflicts": "conflicts.json",
    "version": "canon_version.json",
}


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def canon_dir(world_path: str | None = None) -> str:
    base = world_path or config.world_dir()
    return os.path.join(base, "canon")


def ensure_canon_dir(world_path: str | None = None) -> str:
    path = canon_dir(world_path)
    os.makedirs(path, exist_ok=True)
    return path


def _read_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data
    except Exception:
        return copy.deepcopy(default)


def _write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text or "")


def save_source(world_path: str, source_text: str, source_name: str = "") -> str:
    path = os.path.join(ensure_canon_dir(world_path), CANON_FILES["source"])
    header = ""
    if source_name:
        header = f"<!-- source: {source_name} -->\n\n"
    _write_text(path, header + (source_text or "").strip() + "\n")
    return path


def _slug(text: str, prefix: str = "region") -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", str(text or "")).strip("-")
    return cleaned[:40] or prefix


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    if value in (None, ""):
        return []
    return [value]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _extract_lines(source_text: str, keywords: list[str], limit: int = 12) -> list[str]:
    hits: list[str] = []
    for raw in (source_text or "").splitlines():
        line = raw.strip().strip("-*# 　")
        if not line or len(line) < 3:
            continue
        if any(word in line for word in keywords):
            hits.append(line[:240])
        if len(hits) >= limit:
            break
    return hits


def _derive_locations(world_package: dict[str, Any], source_text: str) -> tuple[dict[str, Any], str]:
    ws = _as_dict(world_package.get("world_state"))
    geography = _as_dict(ws.get("geography"))
    regions = _as_dict(geography.get("regions"))
    locations: dict[str, Any] = {}
    for key, value in regions.items():
        if isinstance(value, dict):
            rid = str(key or value.get("id") or _slug(value.get("name", "")))
            locations[rid] = {
                "id": rid,
                "name": value.get("name") or rid,
                "description": value.get("description", ""),
                "rules": value.get("rules", []),
            }
        else:
            rid = str(key)
            locations[rid] = {"id": rid, "name": str(value or rid), "description": "", "rules": []}

    start = geography.get("current_region") or ""
    script_locations = extract_location_names(source_text, world_package)
    for candidate in script_locations:
        if not candidate:
            continue
        if any(loc.get("name") == candidate for loc in locations.values()):
            continue
        rid = _slug(candidate, "region")
        locations[rid] = {
            "id": rid,
            "name": candidate,
            "description": "由 Canon Engine 从脚本提取的地点。",
            "rules": [],
        }

    if not locations:
        candidate = ""
        for line in _extract_lines(source_text, ["起始", "开局", "出生", "当前舞台", "第一幕", "地点", "区域"], 8):
            match = re.search(r"([\u4e00-\u9fffA-Za-z0-9]{2,16}(?:镇|城|村|山|宗|门|院|坊|界|域|国|府|县|谷|岛))", line)
            if match:
                candidate = match.group(1)
                break
        if not candidate:
            candidate = ws.get("world_name") or world_package.get("name") or "起始地区"
        rid = _slug(candidate, "main")
        locations[rid] = {"id": rid, "name": candidate, "description": "由 Canon Engine 从脚本推断的起始地区。", "rules": []}
        start = rid
    elif start not in locations:
        first_key = next(iter(locations))
        # current_region may be a display name instead of id.
        matched = next((rid for rid, loc in locations.items() if loc.get("name") == start), "")
        start = matched or first_key

    if script_locations:
        start_name = detect_start_location(source_text, [loc.get("name", "") for loc in locations.values() if isinstance(loc, dict)], "")
        matched = next((rid for rid, loc in locations.items() if loc.get("name") == start_name), "")
        if matched:
            start = matched

    return locations, start


def _derive_arcs(world_package: dict[str, Any], source_text: str, start_region: str) -> dict[str, Any]:
    raw_arcs = world_package.get("story_arcs") or world_package.get("arcs") or []
    arcs: list[dict[str, Any]] = []
    for idx, arc in enumerate(_as_list(raw_arcs)):
        if not isinstance(arc, dict):
            arc = {"name": str(arc)}
        milestones = _as_list(arc.get("milestones") or arc.get("beats") or arc.get("key_events"))
        arcs.append({
            "id": arc.get("id") or f"arc-{idx + 1:02d}",
            "name": arc.get("name") or arc.get("title") or f"主线阶段 {idx + 1}",
            "order": int(arc.get("order") or idx + 1),
            "status": arc.get("status") or ("active" if idx == 0 else "locked"),
            "entry_conditions": _as_list(arc.get("entry_conditions") or arc.get("gate") or []),
            "exit_conditions": _as_list(arc.get("exit_conditions") or []),
            "required_milestones": [
                item if isinstance(item, dict) else {"name": str(item), "status": "open"}
                for item in milestones
            ],
            "optional_milestones": _as_list(arc.get("optional_milestones") or []),
        })

    if not arcs:
        lines = _extract_lines(source_text, ["主线", "阶段", "剧情", "故事线", "第一", "第二", "第三"], 18)
        for idx, line in enumerate(lines[:6]):
            if "|" in line or re.search(rf"第[一二三四五六七八九十百千万0-9]+境", line):
                continue
            arcs.append({
                "id": f"arc-{idx + 1:02d}",
                "name": line[:32],
                "order": idx + 1,
                "status": "active" if idx == 0 else "locked",
                "entry_conditions": [] if idx == 0 else [f"完成上一阶段：{arcs[idx - 1]['name']}"],
                "exit_conditions": ["完成本阶段必达里程碑"],
                "required_milestones": [{"name": line, "status": "open"}],
                "optional_milestones": [],
            })

    if not arcs:
        events = _as_list(_as_dict(world_package.get("world_state")).get("global_events"))
        milestones = [
            {"name": item.get("name") or item.get("event") or str(item), "status": "open"}
            for item in events[:5]
            if item
        ] or [{"name": f"在{start_region}完成开篇事件", "status": "open"}]
        arcs.append({
            "id": "arc-01",
            "name": "开篇阶段",
            "order": 1,
            "status": "active",
            "entry_conditions": ["玩家进入世界"],
            "exit_conditions": ["完成开篇必达里程碑"],
            "required_milestones": milestones,
            "optional_milestones": [],
        })

    return {"version": CANON_VERSION, "current_arc_id": arcs[0]["id"], "arcs": arcs}


def compile_canon_from_world_package(
    world_package: dict[str, Any],
    source_text: str = "",
    source_name: str = "",
) -> dict[str, Any]:
    package = _as_dict(world_package)
    source_text = source_text or package.get("world_summary") or ""
    ws = _as_dict(package.get("world_state"))
    locations, start_region = _derive_locations(package, source_text)
    world_name = extract_world_name(source_text, ws.get("world_name") or package.get("name") or "未命名世界")
    factions = _as_list(ws.get("factions") or package.get("factions"))
    characters = _as_list(package.get("playable_characters")) + _as_list(package.get("npcs"))
    start_location_name = locations.get(start_region, {}).get("name", start_region)
    story_outline = compile_story_outline(
        source_text,
        package,
        world_name=world_name,
        start_location=start_location_name,
        locations=[loc.get("name", "") for loc in locations.values() if isinstance(loc, dict)],
    )
    outline_beats = [beat for beat in story_outline.get("beats", []) if isinstance(beat, dict)]
    if outline_beats:
        arcs = {
            "version": CANON_VERSION,
            "current_arc_id": outline_beats[0].get("id", "beat-001"),
            "arcs": [
                {
                    "id": beat.get("id"),
                    "name": beat.get("title"),
                    "order": beat.get("order", idx + 1),
                    "status": "active" if idx == 0 else "locked",
                    "entry_conditions": beat.get("entry_conditions", []),
                    "exit_conditions": [beat.get("required_outcome", "")],
                    "required_milestones": [{"name": beat.get("required_outcome") or beat.get("summary"), "status": "open"}],
                    "optional_milestones": [],
                }
                for idx, beat in enumerate(outline_beats)
            ],
        }
    else:
        arcs = _derive_arcs(package, source_text, start_region)

    hard_facts = [
        {"key": "world_name", "value": world_name, "source": "world_package"},
        {"key": "starting_region", "value": start_region, "source": "world_package_or_source"},
    ]
    hard_facts.extend({"key": "region", "value": loc.get("name"), "source": "geography"} for loc in locations.values())
    hard_facts.extend({"key": "faction", "value": f.get("name") if isinstance(f, dict) else str(f), "source": "factions"} for f in factions)

    power_lines = _extract_lines(source_text, ["修炼", "能力", "体系", "等级", "境界", "力量", "魔法", "异能"], 10)
    bible = {
        "version": CANON_VERSION,
        "world_name": world_name,
        "world_type": package.get("world_type") or ws.get("world_type") or "自定义",
        "starting_region": start_region,
        "starting_region_name": locations.get(start_region, {}).get("name", start_region),
        "time": ws.get("time", {}),
        "geography": {"current_region": start_region, "regions": locations},
        "factions": factions,
        "characters": characters,
        "power_system": package.get("power_system") or {"notes": power_lines},
        "world_laws": package.get("world_laws") or _extract_lines(source_text, ["规则", "禁忌", "法则", "限制", "代价"], 10),
    }
    constraints = {
        "version": CANON_VERSION,
        "hard_facts": hard_facts,
        "soft_constraints": _extract_lines(source_text, ["风格", "氛围", "主题", "基调"], 10),
        "stage_gates": [
            {
                "arc_id": arc.get("id"),
                "arc_name": arc.get("name"),
                "order": arc.get("order", 1),
                "entry_conditions": arc.get("entry_conditions", []),
                "exit_conditions": arc.get("exit_conditions", []),
            }
            for arc in arcs.get("arcs", [])
        ],
        "forbidden_events": [
            "未满足阶段门槛时不得跳到后期主线",
            "不得替换或遗忘 Canon 起始地区、核心势力、力量体系",
            "不得让角色知道 Canon 标注为秘密且未被玩家发现的信息",
            "不得提前完成 beat_ledger 中 locked 的未来剧情节点",
        ],
        "outline_director": {
            "active_beat_id": story_outline.get("current_beat_id", ""),
            "start_location": story_outline.get("start_location", ""),
            "beat_count": len(outline_beats),
        },
        "free_zones": ["玩家解决问题的具体路径", "支线遭遇", "非关键 NPC 的日常行动"],
    }
    source_hash = hashlib.sha256((source_text or json.dumps(package, ensure_ascii=False)).encode("utf-8")).hexdigest()
    return {
        "source_text": source_text,
        "world_bible": bible,
        "story_arcs": arcs,
        "story_outline": story_outline,
        "beat_ledger": initial_beat_ledger(story_outline),
        "constraints": constraints,
        "source_map": {
            "source_name": source_name,
            "source_hash": source_hash,
            "compiled_at": now_iso(),
            "inferred_from": ["world_package", "source_text"],
        },
        "conflicts": {"version": CANON_VERSION, "items": []},
        "canon_version": {
            "version": CANON_VERSION,
            "compiled_at": now_iso(),
            "source_name": source_name,
            "source_hash": source_hash,
        },
    }


def write_canon_files(world_path: str, compiled: dict[str, Any]) -> dict[str, str]:
    base = ensure_canon_dir(world_path)
    source_text = compiled.get("source_text", "")
    if source_text:
        save_source(world_path, source_text, compiled.get("source_map", {}).get("source_name", ""))
    for key in ["bible", "arcs", "outline", "beat_ledger", "constraints", "source_map", "conflicts", "version"]:
        data_key = (
            "world_bible" if key == "bible"
            else "story_arcs" if key == "arcs"
            else "story_outline" if key == "outline"
            else "canon_version" if key == "version"
            else key
        )
        _write_json(os.path.join(base, CANON_FILES[key]), compiled.get(data_key, {}))
    return {key: os.path.join(base, filename) for key, filename in CANON_FILES.items()}


def load_canon(world_path: str | None = None) -> dict[str, Any]:
    base = canon_dir(world_path)
    source_path = os.path.join(base, CANON_FILES["source"])
    try:
        with open(source_path, "r", encoding="utf-8") as handle:
            source = handle.read()
    except Exception:
        source = ""
    return {
        "source_text": source,
        "world_bible": _read_json(os.path.join(base, CANON_FILES["bible"]), {}),
        "story_arcs": _read_json(os.path.join(base, CANON_FILES["arcs"]), {"arcs": []}),
        "story_outline": _read_json(os.path.join(base, CANON_FILES["outline"]), {"beats": []}),
        "beat_ledger": _read_json(os.path.join(base, CANON_FILES["beat_ledger"]), {}),
        "constraints": _read_json(os.path.join(base, CANON_FILES["constraints"]), {}),
        "source_map": _read_json(os.path.join(base, CANON_FILES["source_map"]), {}),
        "conflicts": _read_json(os.path.join(base, CANON_FILES["conflicts"]), {"items": []}),
        "canon_version": _read_json(os.path.join(base, CANON_FILES["version"]), {}),
    }


def canon_exists(world_path: str | None = None) -> bool:
    base = canon_dir(world_path)
    return os.path.exists(os.path.join(base, CANON_FILES["bible"])) and os.path.exists(os.path.join(base, CANON_FILES["arcs"]))


def canon_summary(world_path_or_compiled: str | dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(world_path_or_compiled, dict):
        canon = world_path_or_compiled
    else:
        canon = load_canon(world_path_or_compiled)
    bible = _as_dict(canon.get("world_bible"))
    arcs = _as_dict(canon.get("story_arcs")).get("arcs", [])
    constraints = _as_dict(canon.get("constraints"))
    conflicts = _as_dict(canon.get("conflicts")).get("items", [])
    outline = _as_dict(canon.get("story_outline"))
    ledger = _as_dict(canon.get("beat_ledger"))
    current_id = _as_dict(canon.get("story_arcs")).get("current_arc_id")
    current_arc = next((arc for arc in arcs if isinstance(arc, dict) and arc.get("id") == current_id), None)
    if not current_arc and arcs:
        current_arc = next((arc for arc in arcs if isinstance(arc, dict) and arc.get("status") == "active"), None) or arcs[0]
    beats = [beat for beat in _as_list(outline.get("beats")) if isinstance(beat, dict)]
    active_beat_id = ledger.get("active_beat_id") or outline.get("current_beat_id", "")
    active_beat = next((beat for beat in beats if beat.get("id") == active_beat_id), None) or (beats[0] if beats else {})
    return {
        "exists": bool(bible),
        "version": _as_dict(canon.get("canon_version")).get("version", CANON_VERSION),
        "world_name": bible.get("world_name", ""),
        "starting_region": bible.get("starting_region_name") or bible.get("starting_region", ""),
        "current_arc": current_arc or {},
        "active_beat": active_beat or {},
        "beat_count": len(beats),
        "outline_version": outline.get("version", 0),
        "arc_count": len([arc for arc in arcs if isinstance(arc, dict)]),
        "hard_constraints": len(_as_list(constraints.get("hard_facts"))),
        "conflicts_count": len([item for item in conflicts if isinstance(item, dict) and item.get("status", "open") == "open"]),
        "compiled_at": _as_dict(canon.get("canon_version")).get("compiled_at", ""),
    }


def canonicalize_world_package(world_package: dict[str, Any], canon: dict[str, Any]) -> dict[str, Any]:
    package = copy.deepcopy(_as_dict(world_package))
    ws = _as_dict(package.get("world_state"))
    bible = _as_dict(canon.get("world_bible"))
    ws["world_name"] = ws.get("world_name") or bible.get("world_name") or package.get("name") or "未命名世界"
    ws["geography"] = copy.deepcopy(bible.get("geography") or ws.get("geography") or {})
    if not ws.get("factions"):
        ws["factions"] = copy.deepcopy(bible.get("factions") or [])
    if not ws.get("time"):
        ws["time"] = copy.deepcopy(bible.get("time") or {"year": 1, "month": 1, "day": 1, "hour": 8, "period": "清晨", "era": "元年", "dynasty": ""})
    package["world_state"] = ws
    package["canon_summary"] = canon_summary(canon)
    return package


def record_conflict(world_path: str, conflict: dict[str, Any]) -> dict[str, Any]:
    base = ensure_canon_dir(world_path)
    path = os.path.join(base, CANON_FILES["conflicts"])
    data = _read_json(path, {"version": CANON_VERSION, "items": []})
    items = data.get("items", [])
    if not isinstance(items, list):
        items = []
    conflict = {
        "id": conflict.get("id") or f"conflict-{int(time.time() * 1000)}",
        "created_at": conflict.get("created_at") or now_iso(),
        "status": conflict.get("status") or "open",
        **conflict,
    }
    items.append(conflict)
    data["items"] = items[-500:]
    data["updated_at"] = now_iso()
    _write_json(path, data)
    return conflict


def resolve_conflict(world_path: str, conflict_id: str, status: str = "resolved", note: str = "") -> dict[str, Any]:
    base = ensure_canon_dir(world_path)
    path = os.path.join(base, CANON_FILES["conflicts"])
    data = _read_json(path, {"version": CANON_VERSION, "items": []})
    for item in data.get("items", []):
        if isinstance(item, dict) and item.get("id") == conflict_id:
            item["status"] = status
            item["resolved_at"] = now_iso()
            if note:
                item["resolution_note"] = note
    _write_json(path, data)
    return data
