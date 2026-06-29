import json
import os
from state import read_json, write_json, update_json, get_player_character, get_player_memory_id
import config


def init_character_memory(char_id: str, char_name: str, char_type: str = "npc"):
    """Initialize memory file for a character if it doesn't exist."""
    mem_path = os.path.join(config.MEMORY_DIR, f"{char_id}.json")
    if not os.path.exists(mem_path):
        write_json(config.MEMORY_DIR, f"{char_id}.json", {
            "char_id": char_id,
            "char_name": char_name,
            "char_type": char_type,  # protagonist, npc, system
            "recent": [],
            "milestones": [],
            "compressed": [],
            "relationships": {},
        })
    elif char_type == "protagonist":
        def apply(mem):
            mem["char_name"] = char_name
            mem["char_type"] = char_type
            return mem
        update_json(config.MEMORY_DIR, f"{char_id}.json", apply)
    return mem_path


def add_memory(char_id: str, entry: dict, api_key: str = "", base_url: str = "", model: str = ""):
    """Add a memory entry for a character. Auto-classifies as recent or milestone.
    If api_key is provided, uses LLM compression when recent memories exceed threshold.
    """
    try:
        read_json(config.MEMORY_DIR, f"{char_id}.json")
    except Exception:
        init_character_memory(char_id, char_id, "npc")
    entry.setdefault("round", 0)
    entry.setdefault("importance", 3)

    def apply(mem):
        if entry.get("importance", 3) >= 4:
            mem.setdefault("milestones", []).append(entry)
            mem["milestones"] = mem["milestones"][-20:]  # Keep last 20 milestones
        else:
            mem.setdefault("recent", []).append(entry)

        # Trigger compression when recent exceeds threshold
        if len(mem.get("recent", [])) > 15:
            old = mem["recent"][:-10]   # compress the oldest 5+
            compressed_entry = _compress_memories(old, api_key, base_url, model)
            if compressed_entry:
                mem.setdefault("compressed", []).append(compressed_entry)
                mem["compressed"] = mem["compressed"][-15:]  # Keep last 15 compressions
            mem["recent"] = mem["recent"][-10:]
        return mem

    mem = update_json(config.MEMORY_DIR, f"{char_id}.json", apply)

    # Try vector store — warn loudly if it fails (no silent fallback)
    try:
        from memory.chroma_store import add_memory_embedding
        mem_id = f"{char_id}_{entry.get('round', 0)}_{len(mem.get('recent', [])) + len(mem.get('milestones', []))}"
        add_memory_embedding(char_id, mem_id, entry.get("content", ""), {
            "round": entry.get("round", 0),
            "importance": entry.get("importance", 3),
            "timestamp": entry.get("timestamp", ""),
        })
    except ImportError:
        pass  # chromadb not installed — acceptable fallback
    except Exception as ve:
        # chromadb installed but errored — log it
        import sys
        print(f"[memory] ChromaDB write error for {char_id}: {ve}", file=sys.stderr)


def update_relationship(char_id: str, target_name: str, change: str):
    """Update relationship tracking for a character."""
    try:
        read_json(config.MEMORY_DIR, f"{char_id}.json")
    except Exception:
        init_character_memory(char_id, char_id, "npc")

    def apply(mem):
        rels = mem.setdefault("relationships", {})
        rels[target_name] = {
            "last_update": change,
            "timestamp": len(mem.get("recent", [])) + len(mem.get("milestones", [])),
        }
        return mem

    update_json(config.MEMORY_DIR, f"{char_id}.json", apply)


def get_memory_context(char_id: str, max_items: int = 10, context: str = "") -> str:
    """Get a compact text summary of a character's memory for agent prompts.
    Uses semantic search if ChromaDB is available, falls back to recency-based retrieval.
    """
    # Semantic search takes priority
    if context:
        try:
            from memory.chroma_store import search_memories
            memories = search_memories(char_id, context, max_items)
            if memories:
                lines = ["【相关记忆（语义检索）】"]
                for m in memories:
                    lines.append(f"- {m['content'][:120]}")
                # Also append the most recent 3 items for continuity
                try:
                    mem = read_json(config.MEMORY_DIR, f"{char_id}.json")
                    recent = mem.get("recent", [])[-3:]
                    if recent:
                        lines.append("【最近动态】")
                        for m in recent:
                            lines.append(f"- 第{m.get('round', '?')}轮: {m.get('content', str(m))[:100]}")
                except Exception:
                    pass
                return "\n".join(lines)
        except ImportError:
            pass
        except Exception:
            pass

    try:
        mem = read_json(config.MEMORY_DIR, f"{char_id}.json")
    except (FileNotFoundError, Exception):
        return "（无记忆）"

    lines = []
    # Milestones first (most important)
    milestones = mem.get("milestones", [])[-5:]
    if milestones:
        lines.append("【重要记忆】")
        for m in milestones:
            lines.append(f"- 第{m.get('round', '?')}轮: {m.get('content', str(m))[:120]}")

    # Recent memories
    recent = mem.get("recent", [])[-max_items:]
    if recent:
        lines.append("【近期经历】")
        for m in recent:
            lines.append(f"- 第{m.get('round', '?')}轮: {m.get('content', str(m))[:120]}")

    # Compressed history (LLM-summarized)
    compressed = mem.get("compressed", [])[-3:]
    if compressed:
        lines.append("【过往概要（AI总结）】")
        for c in compressed:
            lines.append(f"- {c.get('summary', str(c))[:200]}")

    # Relationships
    rels = mem.get("relationships", {})
    if rels:
        lines.append("【人际关系】")
        for name, info in list(rels.items())[:8]:
            lines.append(f"- {name}: {info.get('last_update', '')[:80]}")

    return "\n".join(lines) if lines else "（无记忆）"


def _compress_memories(entries: list, api_key: str = "", base_url: str = "", model: str = "") -> dict:
    """Compress multiple memory entries into a meaningful summary.
    Uses LLM if api_key is available, otherwise falls back to simple concatenation.
    """
    if not entries:
        return {}

    rounds = [e.get("round", "?") for e in entries if isinstance(e.get("round"), int)]
    contents = [e.get("content", str(e))[:150] for e in entries]

    # Try LLM compression if credentials available
    if api_key and base_url:
        try:
            from agents.base import call_deepseek
            use_model = model or "deepseek-chat"
            system_prompt = "你是记忆管理员。将以下若干条角色记忆条目提炼为一段简洁的叙事摘要（100-200字），保留关键事件、重要决定和情感变化，删除重复和琐碎内容。直接输出摘要文本，不需要JSON格式。"
            user_prompt = "\n".join([f"第{e.get('round', '?')}轮: {e.get('content', '')[:200]}" for e in entries])
            result = call_deepseek(system_prompt, user_prompt,
                                   api_key=api_key, base_url=base_url,
                                   model=use_model, max_tokens=300)
            # result is a dict from call_deepseek; handle both raw text and dict
            if isinstance(result, dict):
                summary_text = result.get("narrative_passage") or result.get("summary") or str(result)
            else:
                summary_text = str(result)
            return {
                "summary": summary_text,
                "compressed_count": len(entries),
                "round_range": [min(rounds) if rounds else 0, max(rounds) if rounds else 0],
                "method": "llm",
            }
        except Exception as e:
            import sys
            print(f"[memory] LLM compression failed, falling back to concat: {e}", file=sys.stderr)

    # Fallback: structured concatenation (better than pure string join)
    key_points = []
    for e in entries:
        content = e.get("content", "")
        if any(kw in content for kw in ["突破", "战斗", "发现", "决定", "第一次", "秘密", "死亡", "逃跑"]):
            key_points.append(f"[关键] {content[:100]}")
        else:
            key_points.append(content[:60])

    return {
        "summary": f"第{min(rounds) if rounds else '?'}-{max(rounds) if rounds else '?'}轮概要: " + "；".join(key_points[:6]),
        "compressed_count": len(entries),
        "round_range": [min(rounds) if rounds else 0, max(rounds) if rounds else 0],
        "method": "concat",
    }


def sync_all_characters():
    """Ensure all characters in characters.json have memory files."""
    try:
        chars = read_json(config.STATE_DIR, "characters.json")
    except Exception:
        return

    # Protagonist
    player = get_player_character() or {}
    player_name = player.get("name", "主角")
    player_memory_id = get_player_memory_id()
    init_character_memory("protagonist", player_name, "protagonist")
    if player_memory_id != "protagonist":
        init_character_memory(player_memory_id, player_name, "protagonist")

    # System
    init_character_memory("system", "系统", "system")

    # NPCs
    for c in chars.get("characters", []):
        cid = c.get("id", "")
        if cid:
            init_character_memory(cid, c.get("name", cid), "npc")
