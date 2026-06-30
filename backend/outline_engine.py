"""Executable story outline and beat ledger.

Canon v1 preserved a world bible and broad story arcs.  That is useful context,
but it is not enough for a detailed outline: the scheduler needs to know which
beat is active *this round*, which future beats are locked, and what text would
count as satisfying the current beat.  This module compiles a deterministic
outline from the user's source script and persists a small ledger beside Canon.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any


OUTLINE_VERSION = 2
OUTLINE_FILE = "story_outline.json"
LEDGER_FILE = "beat_ledger.json"

_CN_NUM = "一二三四五六七八九十百千万0123456789"
_PLACE_SUFFIX = "镇|城|村|山|宗|门|院|坊|界|域|国|府|县|谷|岛|州|郡|宫|阁|楼|铺|堂|河|湖|海"
_GENERIC_PLACE_NAMES = {
    "当前世界", "根据世界", "凡人世界", "修仙世界", "灵界", "仙界",
    "第一阶段", "第二阶段", "第三阶段", "第四阶段", "第五阶段",
}
_FUTURE_TERMS = [
    "飞升", "渡劫", "成仙", "终局", "终章", "最终", "大道本源", "归元",
    "天道联盟", "世界编程", "星际舰队", "天基武器", "统一天下",
]


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _read_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data
    except Exception:
        return default


def _write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    if value in (None, ""):
        return []
    return [value]


def _clean_line(line: str) -> str:
    line = re.sub(r"<[^>]+>", "", line or "")
    return line.strip().strip("-*# 　")


def _slug(text: str, prefix: str = "beat") -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", str(text or "")).strip("-")
    return cleaned[:44] or prefix


def _normalize_place_name(name: str) -> str:
    value = str(name or "").strip()
    value = re.sub(r"^(进入|前往|来到|抵达|拜入|拜访|去往|赶赴|离开)", "", value)
    return value.strip()


def extract_world_name(source_text: str, fallback: str = "") -> str:
    patterns = [
        r"\*{0,2}(?:世界名称|世界名)\*{0,2}\s*[：:]\s*([^\n\r。；]+)",
        r"^\s*(?:世界名称|世界名)\s*[：:]\s*([^\n\r。；]+)",
        r"《([^》]{2,32})》",
        r"#\s*([^\n\r]{2,32})",
    ]
    for pattern in patterns:
        match = re.search(pattern, source_text or "")
        if match:
            value = _clean_line(match.group(1)).strip("：: ")
            if value and value not in {"世界", "世界设定", "完整设定"}:
                return value[:40]
    return fallback or "未命名世界"


def extract_location_names(source_text: str, world_package: dict[str, Any] | None = None) -> list[str]:
    names: list[str] = []
    package = _as_dict(world_package)
    geography = _as_dict(_as_dict(package.get("world_state")).get("geography"))
    regions = geography.get("regions")
    if isinstance(regions, dict):
        for key, value in regions.items():
            if isinstance(value, dict):
                candidate = value.get("name") or key
            else:
                candidate = str(value or key)
            if candidate:
                names.append(str(candidate))
    elif isinstance(regions, list):
        for item in regions:
            if isinstance(item, dict) and item.get("name"):
                names.append(str(item["name"]))

    pattern = re.compile(rf"([\u4e00-\u9fffA-Za-z0-9]{{2,18}}(?:{_PLACE_SUFFIX}))")
    for raw in (source_text or "").splitlines():
        line = _clean_line(raw)
        if not line or line.startswith("|---") or line.startswith("----"):
            continue
        for name in pattern.findall(line):
            name = _normalize_place_name(name)
            if name in _GENERIC_PLACE_NAMES:
                continue
            if name.endswith("世界") and name not in {"凡人世界", "修仙世界"}:
                continue
            if name not in names:
                names.append(name)
    return names[:80]


def detect_start_location(source_text: str, locations: list[str], fallback: str = "") -> str:
    source = source_text or ""
    def _best_location(text: str) -> str:
        matches = [name for name in locations if name and name in text]
        if not matches:
            found = re.findall(rf"([\u4e00-\u9fffA-Za-z0-9]{{2,18}}(?:{_PLACE_SUFFIX}))", text)
            matches = [_normalize_place_name(item) for item in found]
        if not matches:
            return ""
        def score(name: str) -> tuple[int, int]:
            suffix_score = 4 if name.endswith(("镇", "城", "村", "县", "府")) else 3 if name.endswith(("宗", "门", "山", "谷", "岛")) else 1
            generic_penalty = -5 if name in _GENERIC_PLACE_NAMES or name.endswith("世界") else 0
            return (suffix_score + generic_penalty, len(name))
        return sorted(matches, key=score, reverse=True)[0]

    for pattern in [
        r"\*{0,2}(?:开局地点|起始地点|起始地区|出生地|主角出生地|当前舞台|第一幕地点)\*{0,2}\s*[：:]\s*([^\n\r，,。；;]+)",
        r"(?:开局|起始|出生|第一幕|初始)[^\n\r]{0,18}?([\u4e00-\u9fffA-Za-z0-9]{2,18}(?:%s))" % _PLACE_SUFFIX,
    ]:
        match = re.search(pattern, source)
        if match:
            text = match.group(1)
            best = _best_location(text)
            if best:
                return best
    for name in locations:
        if name not in _GENERIC_PLACE_NAMES:
            return name
    return fallback or "起始地区"


def _line_has_story_signal(line: str) -> bool:
    return any(word in line for word in ["剧情", "主线", "故事线", "阶段", "篇章", "章节", "开局", "前期", "中期", "后期", "终章"])


def _line_is_table_separator(line: str) -> bool:
    stripped = line.replace("|", "").replace("-", "").replace(":", "").strip()
    return not stripped


def _table_beats(lines: list[str]) -> list[dict[str, str]]:
    beats: list[dict[str, str]] = []
    header: list[str] = []
    header_is_story = False
    for raw in lines:
        line = raw.strip()
        if not line.startswith("|") or _line_is_table_separator(line):
            continue
        cols = [col.strip() for col in line.strip("|").split("|")]
        if not header:
            header = cols
            header_is_story = any(any(key in col for key in ["剧情", "主线", "故事", "阶段", "篇章"]) for col in header)
            continue
        if not header_is_story:
            continue
        if len(cols) < 2:
            continue
        mapping = {header[i] if i < len(header) else f"col{i}": cols[i] for i in range(len(cols))}
        title = ""
        summary = ""
        for key, value in mapping.items():
            if not value:
                continue
            if any(k in key for k in ["阶段", "篇章", "名称", "路线"]):
                title = title or value
            if any(k in key for k in ["剧情", "主线", "故事", "作用"]):
                summary = summary or value
        if summary or title:
            beats.append({"title": title or summary[:24], "summary": summary or title})
    return beats


def _paragraph_beats(lines: list[str]) -> list[dict[str, str]]:
    beats: list[dict[str, str]] = []
    seen: set[str] = set()
    stage_pattern = re.compile(rf"(第[{_CN_NUM}]+(?:阶段|卷|幕|章|篇)[：:·、\s-]*[^\n\r]*)")
    for raw in lines:
        line = _clean_line(raw)
        if not line or len(line) < 4:
            continue
        if line.startswith("|") or line.startswith("----"):
            continue
        if any(marker in line for marker in ["核心缺陷", "核心局限", "身份", "修为", "能力", "关键设定"]) and not any(marker in line for marker in ["事件", "剧情线", "主线"]):
            continue
        if re.search(r"(核心剧情线|主线剧情|剧情大纲|故事线)\s*$", line):
            continue
        matches = stage_pattern.findall(line)
        candidate = matches[0] if matches else line
        if not _line_has_story_signal(candidate):
            continue
        # Avoid treating power-system rows such as "第一境·启明" as plot beats.
        if re.search(rf"第[{_CN_NUM}]+境", candidate) and "剧情" not in candidate:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        title = re.sub(r"[。；;].*$", "", candidate).strip()
        if len(title) > 36:
            title = title[:36]
        beats.append({"title": title, "summary": candidate[:260]})
    return beats


def _focused_story_lines(lines: list[str]) -> list[str]:
    markers = ["核心剧情线", "主线剧情", "剧情大纲", "故事线", "事件详表", "详细事件"]
    for idx, raw in enumerate(lines):
        line = _clean_line(raw)
        if any(marker in line for marker in markers):
            return lines[idx + 1:]
    return []


def _fallback_beats(source_text: str, start_location: str) -> list[dict[str, str]]:
    beats = [
        {"title": f"{start_location}开局立足", "summary": f"主角必须先在{start_location}完成开篇立足，不得跳到后期地图或终局主线。"},
    ]
    cue_map = [
        ("商业", "凡人商业扩张"),
        ("京城", "京城关键转折"),
        ("国师", "国师与灵石线索"),
        ("灵石", "灵石揭示修仙门槛"),
        ("修仙", "进入修仙世界"),
        ("宗门", "宗门与修行秩序"),
        ("天道", "天道博弈"),
        ("终章", "终章收束"),
    ]
    for cue, title in cue_map:
        if cue in (source_text or "") and not any(cue in b["summary"] for b in beats):
            beats.append({"title": title, "summary": f"根据原始脚本，后续需要推进「{title}」相关剧情。"})
    return beats


def _keywords(text: str, location: str = "") -> list[str]:
    words: list[str] = []
    for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,8}", text or ""):
        token = _normalize_place_name(token)
        if token in {"第一阶段", "第二阶段", "当前阶段", "对应剧情", "主线剧情"}:
            continue
        if token not in words:
            words.append(token)
    if location and location not in words:
        words.insert(0, location)
    return words[:12]


def compile_story_outline(
    source_text: str,
    world_package: dict[str, Any] | None = None,
    *,
    world_name: str = "",
    start_location: str = "",
    locations: list[str] | None = None,
) -> dict[str, Any]:
    source_text = source_text or ""
    package = _as_dict(world_package)
    locations = locations or extract_location_names(source_text, package)
    world_name = extract_world_name(source_text, world_name or package.get("name") or "未命名世界")
    start_location = start_location or detect_start_location(source_text, locations, "起始地区")
    lines = source_text.splitlines()

    focus_lines = _focused_story_lines(lines)
    if focus_lines:
        raw_beats = _paragraph_beats(focus_lines)
        if not raw_beats:
            raw_beats = _table_beats(focus_lines)
    else:
        raw_beats = _table_beats(lines) + _paragraph_beats(lines)
    if not raw_beats:
        raw_beats = _fallback_beats(source_text, start_location)

    # Ensure the first beat is explicitly anchored at the start location.  This
    # is the most important fix for scripts that keep getting ignored at开局.
    first_summary = raw_beats[0].get("summary", "")
    if start_location and start_location not in first_summary:
        raw_beats.insert(0, {
            "title": f"{start_location}开局",
            "summary": f"开篇必须从{start_location}开始，先完成该地点的现实问题与人物接触。",
        })

    beats: list[dict[str, Any]] = []
    for idx, raw in enumerate(raw_beats[:48]):
        title = _clean_line(raw.get("title") or raw.get("summary") or f"剧情节点 {idx + 1}")
        summary = _clean_line(raw.get("summary") or title)
        location = next((name for name in locations if name and name in summary + title), "")
        if idx == 0:
            location = location or start_location
        key_terms = _keywords(f"{title} {summary}", location)
        forbidden = []
        if idx == 0:
            forbidden = _FUTURE_TERMS[:]
        beats.append({
            "id": f"beat-{idx + 1:03d}-{_slug(title)}",
            "act_id": "act-01",
            "order": idx + 1,
            "title": title[:64],
            "summary": summary[:420],
            "location": location,
            "status": "active" if idx == 0 else "locked",
            "entry_conditions": [] if idx == 0 else [f"完成上一节点：{raw_beats[idx - 1].get('title') or raw_beats[idx - 1].get('summary')}"],
            "required_outcome": summary[:260],
            "completion_signals": key_terms[:8],
            "forbidden_before_completion": forbidden,
            "source_excerpt": summary[:420],
        })

    for idx, beat in enumerate(beats):
        future = []
        for item in beats[idx + 1:]:
            future.extend(item.get("completion_signals", [])[:3])
            future.append(item.get("title", ""))
        beat["locked_future_terms"] = [term for term in future if term][:30]

    outline = {
        "version": OUTLINE_VERSION,
        "world_name": world_name,
        "start_location": start_location,
        "current_act_id": "act-01",
        "current_beat_id": beats[0]["id"] if beats else "",
        "acts": [{
            "id": "act-01",
            "order": 1,
            "name": "主线轨道",
            "summary": "由用户原始大纲编译出的可执行剧情节点。",
            "status": "active",
            "beat_ids": [beat["id"] for beat in beats],
        }],
        "beats": beats,
        "locations": locations,
        "compiled_at": now_iso(),
    }
    return outline


def outline_path(world_path: str) -> str:
    return os.path.join(world_path, "canon", OUTLINE_FILE)


def ledger_path(world_path: str) -> str:
    return os.path.join(world_path, "canon", LEDGER_FILE)


def load_story_outline(world_path: str) -> dict[str, Any]:
    return _read_json(outline_path(world_path), {"version": OUTLINE_VERSION, "acts": [], "beats": [], "current_beat_id": ""})


def write_story_outline(world_path: str, outline: dict[str, Any]) -> None:
    _write_json(outline_path(world_path), outline)


def initial_beat_ledger(outline: dict[str, Any]) -> dict[str, Any]:
    beats = _as_list(outline.get("beats"))
    active_id = outline.get("current_beat_id") or (beats[0].get("id") if beats and isinstance(beats[0], dict) else "")
    return {
        "version": OUTLINE_VERSION,
        "active_beat_id": active_id,
        "updated_at": now_iso(),
        "beats": {
            beat.get("id"): {
                "status": "active" if beat.get("id") == active_id else "locked",
                "attempts": 0,
                "completed_round": None,
                "last_evidence": "",
            }
            for beat in beats
            if isinstance(beat, dict) and beat.get("id")
        },
        "history": [],
    }


def load_beat_ledger(world_path: str, outline: dict[str, Any] | None = None) -> dict[str, Any]:
    ledger = _read_json(ledger_path(world_path), {})
    if isinstance(ledger, dict) and ledger.get("active_beat_id"):
        return ledger
    if outline is None:
        outline = load_story_outline(world_path)
    ledger = initial_beat_ledger(outline)
    write_beat_ledger(world_path, ledger)
    return ledger


def write_beat_ledger(world_path: str, ledger: dict[str, Any]) -> None:
    ledger["updated_at"] = now_iso()
    _write_json(ledger_path(world_path), ledger)


def current_beat(outline: dict[str, Any], ledger: dict[str, Any]) -> dict[str, Any]:
    active_id = ledger.get("active_beat_id") or outline.get("current_beat_id")
    beats = [beat for beat in _as_list(outline.get("beats")) if isinstance(beat, dict)]
    if active_id:
        for beat in beats:
            if beat.get("id") == active_id:
                return beat
    return beats[0] if beats else {}


def build_round_contract(world_path: str, *, player_action: str = "", max_locked_terms: int = 40) -> dict[str, Any]:
    outline = load_story_outline(world_path)
    ledger = load_beat_ledger(world_path, outline)
    beat = current_beat(outline, ledger)
    locked_terms: list[str] = []
    if beat:
        locked_terms.extend(_as_list(beat.get("forbidden_before_completion")))
        locked_terms.extend(_as_list(beat.get("locked_future_terms")))
    locked_terms = [str(term) for term in locked_terms if term]
    seen = set()
    locked_unique = []
    for term in locked_terms:
        if term not in seen:
            seen.add(term)
            locked_unique.append(term)
    return {
        "version": OUTLINE_VERSION,
        "exists": bool(beat),
        "active_beat_id": beat.get("id", ""),
        "active_beat": beat,
        "required_outcome": beat.get("required_outcome", ""),
        "completion_signals": _as_list(beat.get("completion_signals")),
        "forbidden_terms": locked_unique[:max_locked_terms],
        "source_excerpt": beat.get("source_excerpt", ""),
        "player_action": player_action,
        "directive": (
            "本轮必须围绕 active_beat 推进；可以改变解决方式，但不得提前完成 locked future beats。"
            if beat else ""
        ),
    }


def validate_text_against_contract(text: str, contract: dict[str, Any]) -> dict[str, Any]:
    if not contract.get("exists") or not text:
        return {"allowed": True, "violations": []}
    active = _as_dict(contract.get("active_beat"))
    active_blob = " ".join([active.get("title", ""), active.get("summary", ""), active.get("location", "")])
    violations = []
    for term in _as_list(contract.get("forbidden_terms")):
        term = str(term)
        if len(term) < 2:
            continue
        if term in active_blob:
            continue
        variants = {term, _normalize_place_name(term)}
        for place in re.findall(rf"([\u4e00-\u9fffA-Za-z0-9]{{2,18}}(?:{_PLACE_SUFFIX}))", term):
            variants.add(_normalize_place_name(place))
        variants = {item for item in variants if len(item) >= 2}
        if any(item and item in text for item in variants):
            violations.append({
                "type": "outline_future_leak",
                "term": term,
                "message": f"当前剧情节点是「{active.get('title', '当前节点')}」，输出提前触碰了未解锁节点关键词「{term}」。",
                "severity": "severe",
            })
            if len(violations) >= 3:
                break
    return {"allowed": not violations, "violations": violations}


def advance_beat_if_satisfied(world_path: str, evidence_text: str, round_no: int = 0) -> dict[str, Any]:
    outline = load_story_outline(world_path)
    ledger = load_beat_ledger(world_path, outline)
    beat = current_beat(outline, ledger)
    if not beat:
        return {"advanced": False, "reason": "no_active_beat"}

    signals = [str(item) for item in _as_list(beat.get("completion_signals")) if item]
    if not signals:
        return {"advanced": False, "reason": "no_signals"}
    hits = [signal for signal in signals if signal in (evidence_text or "")]
    # It should be possible to progress after a round that clearly addresses the
    # beat, but not merely because the beat title was present in a prompt.
    needed = 2 if len(signals) >= 4 else 1
    if len(hits) < needed:
        ledger.setdefault("beats", {}).setdefault(beat["id"], {}).setdefault("attempts", 0)
        ledger["beats"][beat["id"]]["attempts"] = int(ledger["beats"][beat["id"]].get("attempts") or 0) + 1
        ledger["beats"][beat["id"]]["last_evidence"] = (evidence_text or "")[:260]
        write_beat_ledger(world_path, ledger)
        return {"advanced": False, "reason": "signals_missing", "hits": hits}

    beat_state = ledger.setdefault("beats", {}).setdefault(beat["id"], {})
    beat_state["status"] = "satisfied"
    beat_state["completed_round"] = round_no
    beat_state["last_evidence"] = (evidence_text or "")[:260]

    beats = [item for item in _as_list(outline.get("beats")) if isinstance(item, dict)]
    next_beat = None
    for idx, item in enumerate(beats):
        if item.get("id") == beat.get("id") and idx + 1 < len(beats):
            next_beat = beats[idx + 1]
            break
    if next_beat:
        ledger["active_beat_id"] = next_beat["id"]
        ledger.setdefault("beats", {}).setdefault(next_beat["id"], {})["status"] = "active"
        ledger["history"] = (_as_list(ledger.get("history")) + [{
            "at": now_iso(),
            "round": round_no,
            "from": beat.get("id"),
            "to": next_beat.get("id"),
            "evidence": (evidence_text or "")[:260],
            "hits": hits,
        }])[-200:]
    else:
        ledger["active_beat_id"] = beat["id"]
        ledger["history"] = (_as_list(ledger.get("history")) + [{
            "at": now_iso(),
            "round": round_no,
            "from": beat.get("id"),
            "to": "",
            "evidence": (evidence_text or "")[:260],
            "hits": hits,
        }])[-200:]
    write_beat_ledger(world_path, ledger)
    return {"advanced": bool(next_beat), "completed": beat.get("id"), "next": next_beat or {}, "hits": hits}
