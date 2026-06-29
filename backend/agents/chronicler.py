import json
import os
from .base import call_deepseek, normalize_agent_output, ensure_dict, ensure_list, ensure_list_of_dicts
from state import (
    read_json, read_text, append_text, write_text, write_json, update_json,
    get_player_character, get_player_memory_id,
)
import config
from memory_manager import get_memory_context, add_memory, update_relationship, sync_all_characters
from story_ledger import StoryLedger
from prose_quality import review_prose
from agent_templates import get_agent_config, build_narrator_system_prompt
from story_context import build_agent_context


def _prompt_for(protagonist: dict, world: dict) -> str:
    world_meta = world.get("meta", {})
    agent_config = get_agent_config(world_meta)
    return build_narrator_system_prompt(protagonist, agent_config, world_meta)


def run_chronicler(agent_outputs: dict, api_key: str, base_url: str, model: str) -> dict:
    world = read_json(config.STATE_DIR, "world.json")
    protagonist = get_player_character() or read_json(config.STATE_DIR, "protagonist.json")
    current_volume = f"volume-{max(1, (world['meta']['current_round'] // 30) + 1):02d}"
    chronicle_text = read_text(config.CHRONICLE_DIR, f"{current_volume}.md")

    # Build writing context
    agent_summary = {}
    for k, v in agent_outputs.items():
        if isinstance(v, dict):
            agent_summary[k] = str(v.get("summary", v.get("reasoning", "")))[:400]

    # Get protagonist's recent arc
    action_log = protagonist.get("action_log", [])
    recent = action_log[-5:] if action_log else []

    # Get memory context for continuity
    sync_all_characters()
    previous_tail = chronicle_text[-300:] if chronicle_text else "（新卷开始）"
    search_context = f"上一段叙事结尾：{previous_tail}"
    memory_text = get_memory_context(get_player_memory_id(), max_items=10, context=search_context)
    ledger = StoryLedger(config.world_dir())
    active_chapter = ledger.active_chapter(round_no=world["meta"]["current_round"])
    ledger_context = ledger.context_for(
        player_id=protagonist.get("id"),
        chapter_no=active_chapter["chapter_no"],
        event_limit=20,
    )
    current_word_count = active_chapter.get("word_count", 0)

    user_prompt = json.dumps({
        "instruction": "用上面的写作铁律，写一段小说叙事。把世界变化、系统对话、主角行动都融合成一个有血有肉的故事段落。",
        "protagonist_memory": memory_text,
        "current_round": world["meta"]["current_round"],
        "world_time": world.get("time"),
        "protagonist": {
            "name": protagonist.get("name") or protagonist.get("meta", {}).get("name", "主角"),
            "realm": (protagonist.get("realm") or protagonist.get("cultivation", {}).get("realm", "凡人")),
            "personality": {k: v for k, v in protagonist.get("personality_profile", {}).items()},
            "recent_actions": recent,
            "last_location": recent[-1].get("location") if recent else "当前场景",
            "last_emotional_state": recent[-1].get("emotional_state") if recent else "初来乍到的迷茫",
        },
        "agent_outputs": agent_summary,
        "previous_narrative_tail": chronicle_text[-600:] if chronicle_text else "(新卷开始)",
        "long_context": build_agent_context("chronicler"),
        "story_ledger": ledger_context,
        "active_chapter": {
            "chapter_no": active_chapter["chapter_no"],
            "current_word_count": current_word_count,
            "instruction": f"当前章节已累计{current_word_count}字。账本中的既有事实不可推翻；未回收伏笔应自然推进或明确回收。当字数接近10000字时，请设置need_new_chapter为true并提供章节标题。",
        },
    }, ensure_ascii=False)

    return normalize_agent_output(
        call_deepseek(_prompt_for(protagonist, world), user_prompt, api_key=api_key, base_url=base_url, model=model, max_tokens=8192),
        fallback_key="narrative_passage",
    )


def apply_chronicle_output(output: dict) -> dict:
    output = normalize_agent_output(output, fallback_key="narrative_passage")
    world = read_json(config.STATE_DIR, "world.json")
    try:
        import session_config
        api_key, base_url, model = session_config.get_all()
    except Exception:
        api_key, base_url, model = "", "", ""
    player = get_player_character() or {}
    player_name = player.get("name", "主角")
    player_memory_id = get_player_memory_id()
    round_num = world["meta"]["current_round"]
    vol_num = max(1, (round_num // 30) + 1)
    volume_file = f"volume-{vol_num:02d}.md"

    if "narrative_passage" in output:
        narrative = output["narrative_passage"].strip()
        passage = f"\n\n---\n\n### 第{round_num}轮\n\n{narrative}"
        append_text(config.CHRONICLE_DIR, volume_file, passage)

        # Keep the generated prose as a revision candidate rather than treating
        # the append-only chronicle as a publication-ready manuscript.
        try:
            from story_ledger import StoryLedger
            quality_report = review_prose(narrative)
            ledger = StoryLedger(config.world_dir())
            chapter_summary = ensure_dict(output.get("chapter_summary", {}))
            chapter_title = chapter_summary.get("title", "") if chapter_summary.get("need_new_chapter") else ""
            scene = ledger.append_scene(
                narrative,
                round_no=round_num,
                timeline_update=output.get("timeline_update", ""),
                summary=chapter_summary,
                quality_report=quality_report,
                close_chapter=bool(chapter_summary.get("need_new_chapter")),
                chapter_title=chapter_title,
            )
            ledger.append_event(
                "scene_drafted",
                actor_id=player.get("id"),
                chapter_no=scene["chapter_no"],
                round_no=round_num,
                origin="chronicler",
                payload={"scene_id": scene["id"], "quality_score": quality_report["score"], "chapter_closed": scene["chapter_closed"]},
            )
            for fact in ensure_list_of_dicts(output.get("canon_updates")):
                if all(fact.get(key) for key in ("subject_id", "predicate", "object_value")):
                    ledger.upsert_fact(
                        subject_id=str(fact["subject_id"]),
                        predicate=str(fact["predicate"]),
                        object_value=str(fact["object_value"]),
                        valid_from_chapter=scene["chapter_no"],
                        visibility=fact.get("visibility", "world"),
                    )
            for update in ensure_list_of_dicts(output.get("foreshadow_updates")):
                if update.get("operation") == "plant" and update.get("title") and update.get("detail"):
                    ledger.add_foreshadow(
                        update["title"], update["detail"],
                        planted_chapter=scene["chapter_no"],
                        target_chapter_to=update.get("target_chapter_to"),
                    )
                elif update.get("operation") == "resolve" and update.get("id"):
                    ledger.resolve_foreshadow(update["id"])
        except Exception as error:
            # The legacy chronicle stays available even if the new ledger is
            # unavailable; callers can surface the error through diagnostics.
            print(f"[chronicle] ledger draft skipped: {error}")

        # Record as protagonist memory (compressed narrative)
        importance = 4 if len(passage) > 300 else 3
        memory_entry = {
            "round": round_num,
            "content": passage[:300],
            "importance": importance,
        }
        add_memory(player_memory_id, memory_entry, api_key=api_key, base_url=base_url, model=model)
        if player_memory_id != "protagonist":
            add_memory("protagonist", memory_entry, api_key=api_key, base_url=base_url, model=model)

        # Update relationships based on narrative content
        chars = read_json(config.STATE_DIR, "characters.json")
        rels_data = read_json(config.STATE_DIR, "relationships.json")
        rels_data.setdefault("relations", [])

        llm_rels = {}
        for ru in ensure_list_of_dicts(output.get("relationship_updates")):
            llm_rels[ru.get("character", "")] = ru.get("description", "")

        char_map = {c.get("name", ""): c for c in chars.get("characters", [])}
        for c in chars.get("characters", []):
            cname = c.get("name", "")
            if not cname or cname not in passage:
                continue
            desc = llm_rels.get(cname, f"{c.get('role', '身份不明')}，{c.get('personality', '')}")
            update_relationship(player_memory_id, cname, f"第{round_num}轮：{desc}")
            rels_data["relations"] = [r for r in rels_data["relations"] if r.get("target") != cname]
            rels_data["relations"].append({
                "source": player_name,
                "target": cname,
                "type": "关联",
                "relation": desc,
                "description": desc,
                "round": round_num,
            })
        update_json(config.STATE_DIR, "relationships.json", lambda _: rels_data, {"relations": []})

    if "timeline_update" in output:
        entry = f"- 第{round_num}轮: {output['timeline_update']}\n"
        append_text(config.CHRONICLE_DIR, "timeline.md", entry)

    if "memory_entries" in output:
        index = read_json(config.MEMORY_DIR, "index.json")
        for entry in ensure_list_of_dicts(output.get("memory_entries")):
            importance = entry.get("importance", 3)
            mem_type = "milestones" if importance >= 4 else "recent"
            index.setdefault(mem_type, []).append({
                "round": round_num,
                "content": entry.get("content", ""),
                "importance": importance,
                "timestamp": f"{int(world['time']['year'])}-{int(world['time']['month']):02d}-{int(world['time']['day']):02d}",
            })
        write_json(config.MEMORY_DIR, "index.json", index)

    if "chapter_summary" in output:
        summary = ensure_dict(output.get("chapter_summary"))
        summary_lines = [f"\n\n---\n\n### 第{round_num}轮 章节摘要\n"]
        key_events = [str(item) for item in ensure_list(summary.get("key_events")) if isinstance(item, (str, int, float))]
        if key_events:
            summary_lines.append("**关键事件：**")
            for ev in key_events:
                summary_lines.append(f"- {ev}")
        char_devs = [str(item) for item in ensure_list(summary.get("character_developments")) if isinstance(item, (str, int, float))]
        if char_devs:
            summary_lines.append("**角色变化：**")
            for cd in char_devs:
                summary_lines.append(f"- {cd}")
        new_clues = [str(item) for item in ensure_list(summary.get("new_clues")) if isinstance(item, (str, int, float))]
        if new_clues:
            summary_lines.append("**新线索：**")
            for nc in new_clues:
                summary_lines.append(f"- {nc}")
        emotional_arc = summary.get("emotional_arc", "")
        if emotional_arc:
            summary_lines.append(f"**情感走向：** {emotional_arc}")
        append_text(config.CHRONICLE_DIR, volume_file, "\n".join(summary_lines))

        for ev in key_events:
            memory_entry = {
                "round": round_num,
                "content": f"[关键事件] {ev}",
                "importance": 5,
            }
            add_memory(player_memory_id, memory_entry, api_key=api_key, base_url=base_url, model=model)
            if player_memory_id != "protagonist":
                add_memory("protagonist", memory_entry, api_key=api_key, base_url=base_url, model=model)

    return {"volume": volume_file, "chapter": max(1, round_num)}


def run_chronicler_stream(agent_outputs: dict, api_key: str, base_url: str, model: str):
    import json as _json
    from .base import call_deepseek_stream

    world = read_json(config.STATE_DIR, "world.json")
    protagonist = get_player_character() or read_json(config.STATE_DIR, "protagonist.json")
    current_volume = f"volume-{max(1, (world['meta']['current_round'] // 30) + 1):02d}"
    chronicle_text = read_text(config.CHRONICLE_DIR, f"{current_volume}.md")

    agent_summary = {}
    for k, v in agent_outputs.items():
        if isinstance(v, dict):
            agent_summary[k] = str(v.get("summary", v.get("reasoning", "")))[:400]

    action_log = protagonist.get("action_log", [])
    recent = action_log[-5:] if action_log else []

    sync_all_characters()
    previous_tail = chronicle_text[-300:] if chronicle_text else "（新卷开始）"
    memory_text = get_memory_context(get_player_memory_id(), max_items=10, context=f"上一段叙事结尾：{previous_tail}")
    ledger_context = {}
    try:
        active_chapter = StoryLedger(config.world_dir()).active_chapter(round_no=world["meta"]["current_round"])
        ledger_context = StoryLedger(config.world_dir()).context_for(
            player_id=protagonist.get("id"),
            chapter_no=active_chapter["chapter_no"],
            event_limit=20,
        )
    except Exception:
        ledger_context = {}

    user_prompt = _json.dumps({
        "instruction": "写一段小说叙事。把世界变化、系统对话、主角行动融合成故事段落。",
        "protagonist_memory": memory_text,
        "current_round": world["meta"]["current_round"],
        "world_time": world.get("time"),
        "protagonist": {
            "name": protagonist.get("name") or protagonist.get("meta", {}).get("name", "主角"),
            "realm": (protagonist.get("realm") or protagonist.get("cultivation", {}).get("realm", "凡人")),
            "personality": protagonist.get("personality_profile", {}),
            "recent_actions": recent,
        },
        "agent_outputs": agent_summary,
        "previous_narrative_tail": previous_tail,
        "long_context": build_agent_context("chronicler"),
        "story_ledger": ledger_context,
    }, ensure_ascii=False)

    full_text = ""
    for token in call_deepseek_stream(_prompt_for(protagonist, world), user_prompt, api_key=api_key, base_url=base_url, model=model, max_tokens=4096):
        full_text += token
        yield ("token", token)

    output = normalize_agent_output(full_text, fallback_key="narrative_passage")

    yield ("done", output)
