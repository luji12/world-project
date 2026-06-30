import json
import time
import threading
import queue
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs
import os
import re
import shutil

from scheduler import run_round, run_rounds_auto, RoundEvent
from state import read_json, read_text
from doc_parser import extract_text, summarize_long_text
from story_ledger import StoryLedger
from prose_quality import review_prose
from canon_engine import (
    canonicalize_world_package,
    canon_exists,
    canon_summary,
    compile_canon_from_world_package,
    load_canon,
    resolve_conflict,
    write_canon_files,
)
from canon_migration import reset_world_from_canon
import config

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in separate threads for concurrent API calls."""
    daemon_threads = True

AUTO_STATE = {"paused": False, "stop": False}
PORT = 3101

# 聊天记录事件白名单 — 仅持久化有展示价值的事件
_CHAT_EVENT_TYPES = {
    "system-message", "narration", "npc-message", "player-action-recorded",
    "agent-output", "agent-error", "story-end", "auto-stop", "turn-start",
    "canon-violation", "canon-conflict",
}


def _world_names():
    try:
        return [
            name for name in os.listdir(config.WORLDS_DIR)
            if os.path.isdir(os.path.join(config.WORLDS_DIR, name))
            and not name.startswith(".") and not name.startswith("_")
        ]
    except FileNotFoundError:
        return []


def _world_status_payload(**extra):
    worlds = _world_names()
    return {
        **extra,
        "current_world": config.current_world_name(),
        "has_world": len(worlds) > 0,
        "worlds_count": len(worlds),
    }


def _chat_history_path():
    """返回当前世界的聊天记录文件路径"""
    import os
    world_dir = config.world_dir()
    if not world_dir:
        return None
    return os.path.join(world_dir, "chat_history.json")


def _safe_event_data(data):
    return data if isinstance(data, (dict, list, str, int, float, bool, type(None))) else str(data)


def _event_projection(event_type, data):
    safe_data = _safe_event_data(data)
    data_dict = safe_data if isinstance(safe_data, dict) else {}
    actor = ""
    source = ""
    text = ""
    round_no = data_dict.get("round", 0)

    if event_type == "player-action-recorded":
        actor = "player"
        source = "player"
        text = data_dict.get("action", "")
    elif event_type == "narration":
        actor = "world"
        source = "world-engine"
        text = data_dict.get("text", "")
    elif event_type == "npc-message":
        actor = data_dict.get("npc_name", "NPC")
        source = "npc-agents"
        text = data_dict.get("dialogue") or data_dict.get("action_desc", "")
    elif event_type == "system-message":
        actor = "命运系统"
        source = "system-agent"
        text = data_dict.get("dialogue", "")
    elif event_type == "agent-output":
        source = data_dict.get("agent", "")
        actor = source
        text = data_dict.get("summary", "")
    elif event_type == "agent-error":
        source = data_dict.get("agent", "")
        actor = source
        text = data_dict.get("error", "")
    elif event_type == "story-end":
        actor = "system"
        source = "story"
        text = data_dict.get("message", "")
    elif event_type == "auto-stop":
        actor = "system"
        source = "auto"
        text = data_dict.get("reason", "")
    elif event_type == "turn-start":
        actor = "system"
        source = "turn"
        text = data_dict.get("summary") or data_dict.get("reason", "")
    elif event_type == "canon-violation":
        actor = "Canon"
        source = "canon-validator"
        text = data_dict.get("reason", "")
    elif event_type == "canon-conflict":
        actor = "Canon"
        source = "canon-validator"
        text = data_dict.get("message", "")

    return {
        "type": event_type,
        "data": safe_data,
        "round": round_no,
        "source": source,
        "actor": actor,
        "text": str(text or "")[:4000],
    }


def _normalize_history_event(event):
    if not isinstance(event, dict):
        return None
    event_type = event.get("type", "")
    if not event_type:
        return None
    projected = _event_projection(event_type, event.get("data", {}))
    projected["ts"] = event.get("ts", time.time())
    if event.get("round") is not None:
        projected["round"] = event.get("round")
    if event.get("source"):
        projected["source"] = event.get("source")
    if event.get("actor"):
        projected["actor"] = event.get("actor")
    if event.get("text"):
        projected["text"] = str(event.get("text"))[:4000]
    return projected


def _append_chat_event(event_type, data):
    """将事件追加到 chat_history.json，超阈值时触发压缩"""
    if event_type not in _CHAT_EVENT_TYPES:
        return
    path = _chat_history_path()
    if not path:
        return
    try:
        import json as _json
        try:
            with open(path, "r", encoding="utf-8") as f:
                history = _json.load(f)
        except (FileNotFoundError, _json.JSONDecodeError):
            history = {"events": [], "summary": "", "total_compressed": 0, "updated_at": ""}
        history.setdefault("events", [])
        history.setdefault("summary", "")
        history.setdefault("total_compressed", 0)
        # 过滤掉不可序列化的数据，同时补齐稳定投影字段，方便前端和长上下文复用。
        event = _event_projection(event_type, data)
        event["ts"] = time.time()
        history["events"].append(event)
        history["events"] = history["events"][-500:]  # 硬上限 500
        history["updated_at"] = time.time()
        # 超 300 条触发压缩
        if len(history["events"]) > 300:
            _compress_chat_history(history)
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(history, f, ensure_ascii=False)
    except Exception as e:
        import sys
        print(f"[chat_history] append error: {e}", file=sys.stderr)


def _compress_chat_history(history):
    """压缩旧聊天事件为摘要，复用 memory_manager 的 LLM 压缩能力"""
    try:
        from memory_manager import _compress_memories
        from state import get_player_memory_id
        events = history.get("events", [])
        if len(events) <= 100:
            return
        old_events = events[:-100]  # 压缩最旧的
        # 转换为 memory entry 格式
        entries = []
        for evt in old_events:
            data = evt.get("data", {}) if isinstance(evt.get("data"), dict) else {}
            etype = evt.get("type", "")
            if etype == "player-action-recorded":
                content = f"玩家行动：{data.get('action', '')}"
                importance = 4
            elif etype == "narration":
                content = f"世界变化：{data.get('text', '')[:200]}"
                importance = 3
            elif etype == "npc-message":
                content = f"{data.get('npc_name', 'NPC')}：{data.get('dialogue') or data.get('action_desc', '')}"
                importance = 3
            elif etype == "system-message":
                content = f"系统：{data.get('dialogue', '')}"
                importance = 3
            elif etype == "agent-output" and data.get("agent") == "chronicler":
                content = f"叙事：{data.get('summary', '')[:300]}"
                importance = 4
            elif etype == "agent-error":
                continue  # 跳过错误事件
            else:
                content = str(data)[:150]
                importance = 2
            entries.append({"content": content, "importance": importance, "round": data.get("round", 0)})
        if not entries:
            history["events"] = events[-100:]
            return
        # 尝试从 session_config 获取 API 配置以启用 LLM 压缩，否则走 fallback
        api_key, base_url, model = "", "", ""
        try:
            import session_config
            api_key, base_url, model = session_config.get_all()
        except Exception:
            pass
        compressed = _compress_memories(entries, api_key, base_url, model)
        if compressed and compressed.get("summary"):
            existing_summary = history.get("summary", "")
            new_summary = compressed["summary"]
            if existing_summary:
                history["summary"] = f"{existing_summary}\n\n---\n\n{new_summary}"[-8000:]
            else:
                history["summary"] = new_summary
            history["total_compressed"] = history.get("total_compressed", 0) + compressed.get("compressed_count", len(entries))
        # 关键事件写入主角记忆（复用现有压缩管道）
        try:
            player_mem_id = get_player_memory_id()
            for entry in entries:
                if entry.get("importance", 0) >= 4:
                    from memory_manager import add_memory
                    add_memory(player_mem_id, entry)
        except Exception:
            pass
        history["events"] = events[-100:]
    except Exception as e:
        import sys
        print(f"[chat_history] compress error: {e}", file=sys.stderr)
ALLOWED_STATE_FILES = {
    "world.json",
    "characters.json",
    "protagonist.json",
    "quests.json",
    "relationships.json",
    "npc_agents.json",
}
SAFE_WORLD_RE = re.compile(r"^[^/\\._][^/\\]*$")


def _try_parse_world_json(content: str):
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```\w*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
        cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    brace_start = cleaned.find("{")
    if brace_start >= 0:
        try:
            return json.loads(cleaned[brace_start:])
        except json.JSONDecodeError:
            pass
    depth = 0
    start = -1
    for i, ch in enumerate(cleaned):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(cleaned[start:i + 1])
                except json.JSONDecodeError:
                    start = -1
    return None


class AppHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress log noise

    def _send_cors(self):
        origin = self.headers.get("Origin", "")
        if origin.startswith(("http://localhost:", "http://127.0.0.1:")):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        else:
            self.send_header("Access-Control-Allow-Origin", "http://localhost:5173")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key, X-Base-URL, X-Model")
        self.send_header("Access-Control-Max-Age", "86400")

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._send_cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _send_sse(self):
        self.send_response(200)
        self._send_cors()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

    def _send_book_export(self, filename: str, content_type: str) -> None:
        """Serve only the compiler's fixed export names for the active world."""
        if not config.current_world_name():
            self._send_json({"error": "请先创建或切换世界"}, 404)
            return
        export_path = os.path.join(config.world_dir(), "exports", filename)
        if not os.path.isfile(export_path):
            self._send_json({"error": "尚未编译小说，请先完成导出"}, 404)
            return
        with open(export_path, "rb") as handle:
            body = handle.read()
        self.send_response(200)
        self._send_cors()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", len(body))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        if path == "/api/health":
            self._send_json({"status": "ok"})

        elif path.startswith("/api/state/"):
            filename = path.split("/api/state/", 1)[1]
            if filename not in ALLOWED_STATE_FILES:
                self._send_json({"error": "invalid state filename"}, 400)
                return
            try:
                data = read_json(config.STATE_DIR, filename)
                self._send_json(data)
            except FileNotFoundError:
                self._send_json({"error": "not found"}, 404)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/api/characters":
            try:
                data = read_json(config.STATE_DIR, "characters.json")
                self._send_json(data)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path.startswith("/api/chronicle/"):
            volume = path.split("/api/chronicle/", 1)[1] or "volume-01"
            if not re.match(r"^volume-\d{2}$", volume):
                self._send_json({"error": "invalid volume"}, 400)
                return
            try:
                text = read_text(config.CHRONICLE_DIR, f"{volume}.md")
                self._send_json({"volume": volume, "content": text})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/api/timeline":
            try:
                text = read_text(config.CHRONICLE_DIR, "timeline.md")
                self._send_json({"timeline": text})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/api/rounds-log":
            try:
                import os as _os
                log_file = _os.path.join(config.CHRONICLE_DIR, "rounds-log.json")
                if not _os.path.exists(log_file):
                    self._send_json({"rounds": []})
                    return
                data = read_json(config.CHRONICLE_DIR, "rounds-log.json")
                self._send_json(data)
            except Exception as e:
                self._send_json({"rounds": [], "_error": str(e)})

        elif path == "/api/memory":
            mem_type = params.get("type", ["recent"])[0]
            char_filter = params.get("char", [None])[0]
            try:
                import os as _os
                memories = {}
                for fname in _os.listdir(config.MEMORY_DIR):
                    if not fname.endswith(".json") or fname == "index.json":
                        continue
                    cid = fname.replace(".json", "")
                    if char_filter and cid != char_filter:
                        continue
                    try:
                        data = read_json(config.MEMORY_DIR, fname)
                        name = data.get("char_name", cid)
                        ctype = data.get("char_type", "npc")
                        entries = []
                        if mem_type == "all":
                            entries = data.get("recent", []) + data.get("milestones", []) + data.get("compressed", [])
                        elif mem_type == "milestones":
                            entries = data.get("milestones", [])
                        elif mem_type == "compressed":
                            entries = data.get("compressed", [])
                        else:
                            entries = data.get("recent", [])
                        entries.sort(key=lambda e: e.get("round", 0), reverse=True)
                        rels = data.get("relationships", {})
                        memories[cid] = {"name": name, "type": ctype, "entries": entries[:20], "total": len(data.get("recent",[])) + len(data.get("milestones",[])), "relationships": rels}
                    except:
                        pass
                self._send_json({"characters": memories})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/api/worlds":
            self._handle_list_worlds()

        elif path == "/api/worlds/current":
            self._send_json({"name": config.current_world_name()})

        elif path == "/api/world-realms":
            self._handle_get_world_realms()

        elif path == "/api/status":
            api_key = self.headers.get("X-API-Key", "")
            self._send_json(_world_status_payload(
                has_api_key=bool(api_key),
                canon=canon_summary(config.world_dir()) if config.current_world_name() and canon_exists(config.world_dir()) else {"exists": False},
            ))

        elif path == "/api/canon/status":
            self._handle_canon_status()

        elif path == "/api/canon/source":
            self._handle_canon_source()

        elif path == "/api/canon/bible":
            self._handle_canon_bible()

        elif path == "/api/canon/conflicts":
            self._handle_canon_conflicts()

        elif path == "/api/story/context":
            world_name = config.current_world_name()
            if not world_name:
                self._send_json({"error": "请先创建或切换世界"}, 404)
                return
            player_id = params.get("player", [""])[0]
            chapter = int(params.get("chapter", ["0"])[0] or 0)
            self._send_json(
                StoryLedger(config.world_dir()).context_for(player_id=player_id, chapter_no=chapter)
            )

        elif path == "/api/story/events":
            world_name = config.current_world_name()
            if not world_name:
                self._send_json({"error": "请先创建或切换世界"}, 404)
                return
            limit = min(max(int(params.get("limit", ["50"])[0] or 50), 1), 200)
            self._send_json({"events": StoryLedger(config.world_dir()).list_events(limit=limit)})

        elif path == "/api/chapters":
            world_name = config.current_world_name()
            if not world_name:
                self._send_json({"error": "请先创建或切换世界"}, 404)
                return
            status = params.get("status", [""])[0] or None
            self._send_json({"chapters": StoryLedger(config.world_dir()).list_chapter_revisions(status)})

        elif path == "/api/foreshadows":
            self._handle_foreshadows()

        elif path == "/api/checkpoint/list":
            self._handle_checkpoint_list()

        elif path == "/api/chat/history":
            self._handle_chat_history_get()

        elif path == "/api/book/export":
            export_format = params.get("format", ["html"])[0]
            if export_format == "html":
                self._send_book_export("novel.html", "text/html; charset=utf-8")
            elif export_format == "md":
                self._send_book_export("novel.md", "text/markdown; charset=utf-8")
            else:
                self._send_json({"error": "仅支持 html 或 md 导出"}, 400)

        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        body = {}
        content_length = int(self.headers.get("Content-Length", 0))
        content_type = self.headers.get("Content-Type", "")

        # Skip JSON parsing for file uploads and raw content
        if "multipart/form-data" in content_type or path == "/api/worlds/upload-doc":
            if path == "/api/worlds/upload-doc":
                self._handle_upload_doc()
                return
            raw_body = self.rfile.read(content_length) if content_length > 0 else b""
            return

        if content_length > 0:
            raw = self.rfile.read(content_length)
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                self._send_json({"error": "请求体格式错误，需要JSON"}, 400)
                return

        if path == "/api/round/start":
            self._handle_single_round()

        elif path == "/api/auto/start":
            self._handle_auto_start(body)

        elif path == "/api/auto/pause":
            AUTO_STATE["paused"] = True
            self._send_json({"status": "paused"})

        elif path == "/api/auto/resume":
            AUTO_STATE["paused"] = False
            self._send_json({"status": "resumed"})

        elif path == "/api/npc/generate":
            self._handle_npc_generate()

        elif path == "/api/worlds/switch":
            self._handle_switch_world(body)

        elif path == "/api/worlds/create":
            self._handle_create_world(body)

        elif path == "/api/worlds/create-v2":
            self._handle_create_world_v2(body)

        elif path == "/api/worlds/generate-details":
            self._handle_world_generate_details(body)

        elif path == "/api/worlds/chat":
            self._handle_world_chat(body)

        elif path == "/api/worlds/upload-doc":
            self._handle_upload_doc()

        elif path == "/api/worlds/framework":
            self._handle_framework_update(body)

        elif path == "/api/worlds/restart":
            self._handle_restart_world(body)

        elif path == "/api/worlds/delete":
            self._handle_delete_world(body)

        elif path == "/api/canon/recompile":
            self._handle_canon_recompile(body)

        elif path == "/api/canon/reset-world":
            self._handle_canon_reset_world(body)

        elif path == "/api/canon/conflicts/resolve":
            self._handle_canon_conflict_resolve(body)

        elif path == "/api/polish":
            self._handle_polish(body)

        elif path == "/api/interact/start":
            self._handle_interact_start(body)

        elif path == "/api/inject":
            self._handle_inject(body)

        elif path == "/api/story/checkpoint":
            self._handle_story_checkpoint(body)

        elif path == "/api/chapters/approve":
            self._handle_chapter_approve(body)

        elif path == "/api/chapters/edit":
            self._handle_chapter_edit(body)

        elif path == "/api/chapters/review":
            self._handle_chapter_review(body)

        elif path == "/api/book/compile":
            self._handle_book_compile(body)

        elif path == "/api/checkpoint/save":
            self._handle_checkpoint_save(body)

        elif path == "/api/chat/history/clear":
            self._handle_chat_history_clear()

        else:
            self._send_json({"error": "not found"}, 404)

    def _get_api_config(self):
        return (
            self.headers.get("X-API-Key", ""),
            self.headers.get("X-Base-URL", "https://api.deepseek.com"),
            self.headers.get("X-Model", "deepseek-chat"),
        )

    def _validate_world_name(self, name):
        return bool(name and SAFE_WORLD_RE.match(name.strip()))

    def _handle_single_round(self):
        api_key, base_url, model = self._get_api_config()
        if not api_key:
            self._send_json({"error": "missing API key"}, 400)
            return

        self._send_sse()
        q = queue.Queue()

        def callback(event: RoundEvent):
            q.put(event)

        def runner():
            try:
                run_round(api_key, base_url, model, event_callback=callback)
            finally:
                q.put(None)

        t = threading.Thread(target=runner)
        t.start()

        try:
            while True:
                event = q.get(timeout=300)
                if event is None:
                    self._write_sse_event("close", "{}")
                    break
                try:
                    self._write_sse_event(event.event, json.dumps(event.data, ensure_ascii=False))
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
        except queue.Empty:
            pass
        finally:
            t.join(timeout=5)

    def _handle_auto_start(self, body):
        api_key, base_url, model = self._get_api_config()
        if not api_key:
            self._send_json({"error": "missing API key"}, 400)
            return

        AUTO_STATE["paused"] = False
        AUTO_STATE["stop"] = False
        stop_conditions = body.get("stop_conditions", {})
        intervention_nodes = body.get("intervention_nodes", {})
        interactive_mode = body.get("interactive_mode", False)

        self._send_sse()
        q = queue.Queue()

        def callback(event: RoundEvent):
            _append_chat_event(event.event, event.data)
            q.put(event)

        def pause_check():
            return AUTO_STATE["paused"]

        def runner():
            try:
                run_rounds_auto(
                    stop_conditions, intervention_nodes,
                    api_key, base_url, model,
                    event_callback=callback,
                    pause_check=pause_check,
                    interactive_mode=interactive_mode,
                )
            finally:
                q.put(None)

        t = threading.Thread(target=runner)
        t.start()

        try:
            while True:
                event = q.get(timeout=600)
                if event is None:
                    self._write_sse_event("close", "{}")
                    break
                try:
                    self._write_sse_event(event.event, json.dumps(event.data, ensure_ascii=False))
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
        except queue.Empty:
            pass
        finally:
            t.join(timeout=5)

    def _handle_npc_generate(self):
        api_key, base_url, model = self._get_api_config()
        if not api_key:
            self._send_json({"error": "缺少 API 密钥"}, 400)
            return

        from agents.base import call_deepseek
        from state import update_json

        world = read_json(config.STATE_DIR, "world.json")
        chars = read_json(config.STATE_DIR, "characters.json")
        world_meta = world.get("meta", {})
        from agent_templates import get_agent_config
        agent_cfg = get_agent_config(world_meta)
        wt = world_meta.get("world_type", "xuanhuan")
        we_cfg = agent_cfg.get("world_engine", {})
        narrator_role = agent_cfg.get("narrator", {}).get("role", "小说世界设计师")

        system_prompt = f"""你是一个{narrator_role}，专精于{we_cfg.get('role', '故事世界')}的角色设计。根据当前世界背景，创建新的NPC角色。
角色必须有独立的动机、性格和故事线钩子，不能是纯功能型角色。
输出JSON格式：{{"characters": [{{name, role, personality, location, realm, secret, status:"活跃"}}]}}
术语要求：realm字段使用符合{wt}类型世界观的能力等级（如修真境界、义体等级、魔法阶位、职业等级等）。"""

        user_prompt = json.dumps({
            "instruction": "根据当前世界背景和已有角色，创建1-2个新的NPC角色。确保新角色与现有角色不冲突，有独立动机。",
            "world_summary": {
                "time": world.get("time"),
                "current_region": world.get("geography", {}).get("current_region"),
                "factions": [{"name": f.get("name", ""), "leader": f.get("leader")} for f in world.get("factions", [])],
            },
            "existing_characters": [{"name": c["name"], "role": c.get("role", ""), "location": c.get("location", "")} for c in chars.get("characters", [])],
        }, ensure_ascii=False)

        try:
            output = call_deepseek(system_prompt, user_prompt, api_key=api_key, base_url=base_url, model=model, max_tokens=2048)
            new_chars = output.get("characters", [])
            if not isinstance(new_chars, list):
                new_chars = []
            base_id = len(chars.get("characters", []))
            for i, nc in enumerate(new_chars):
                nc["id"] = f"npc-{base_id + i + 1:03d}"
                nc.setdefault("status", "活跃")
            def apply_chars(latest):
                existing_ids = {c.get("id") for c in latest.get("characters", [])}
                existing_names = {c.get("name") for c in latest.get("characters", [])}
                for nc in new_chars:
                    if nc.get("id") in existing_ids or nc.get("name") in existing_names:
                        continue
                    latest.setdefault("characters", []).append(nc)
                return latest
            update_json(config.STATE_DIR, "characters.json", apply_chars, {"characters": []})
            self._send_json({"status": "ok", "characters": new_chars})
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_list_worlds(self):
        worlds = []
        try:
            entries = os.listdir(config.WORLDS_DIR)
        except FileNotFoundError:
            self._send_json({"worlds": []})
            return
        for name in entries:
            path = os.path.join(config.WORLDS_DIR, name)
            if not os.path.isdir(path) or name.startswith(".") or name.startswith("_"):
                continue
            meta_path = os.path.join(path, "world.json")
            meta = {}
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, encoding="utf-8") as f:
                        meta = json.load(f)
                except Exception:
                    pass
            world_json = os.path.join(path, "state", "world.json")
            rounds = 0
            if os.path.exists(world_json):
                try:
                    with open(world_json, encoding="utf-8") as f:
                        w = json.load(f)
                        rounds = w.get("meta", {}).get("current_round", 0)
                except Exception:
                    pass
            framework = ""
            fw_path = os.path.join(path, "world-framework.md")
            if os.path.exists(fw_path):
                try:
                    with open(fw_path, encoding="utf-8") as f:
                        framework = f.read()
                except Exception:
                    pass
            worlds.append({
                "name": name,
                "type": meta.get("type", ""),
                "description": meta.get("description", ""),
                "created": meta.get("created", ""),
                "rounds": rounds,
                "current": name == config.current_world_name(),
                "framework": framework[:500],  # truncate for response size
            })
        self._send_json({"worlds": sorted(worlds, key=lambda w: w["created"], reverse=True)})

    def _handle_switch_world(self, body):
        name = body.get("name", "").strip()
        if not self._validate_world_name(name):
            self._send_json({"error": "缺少世界名称"}, 400)
            return
        world_path = os.path.join(config.WORLDS_DIR, name)
        if not os.path.isdir(world_path):
            self._send_json({"error": f"世界 '{name}' 不存在"}, 404)
            return
        config.switch_world(name)
        config.refresh_paths()
        try:
            from risk import reset_risk
            reset_risk()
        except Exception:
            pass
        self._send_json({"status": "ok", "name": name})

    def _handle_create_world(self, body):
        name = body.get("name", "").strip()
        summary = body.get("summary", "")
        world_type = body.get("type", "自定义")
        if not self._validate_world_name(name):
            self._send_json({"error": "世界名称不能为空，且不能以点、下划线开头或包含路径分隔符"}, 400)
            return

        world_path = os.path.join(config.WORLDS_DIR, name)
        if os.path.exists(world_path):
            self._send_json({"error": "世界已存在"}, 409)
            return

        # Create world directories
        for sub in ["state", "chronicle", "npc-cards", "memory", "config", "system"]:
            os.makedirs(os.path.join(world_path, sub), exist_ok=True)

        # Save world meta
        with open(os.path.join(world_path, "world.json"), "w") as f:
            json.dump({"name": name, "type": world_type, "created": time.strftime("%Y-%m-%d"), "description": (summary or "")[:200]}, f, ensure_ascii=False, indent=2)

        # Save world framework document
        framework = f"""# {name} — 世界框架

## 世界概述
{summary or '（待补充）'}

## 世界观架构
（在新建世界对话中与创造助手讨论后自动生成）

## 核心法则与力量体系
（待补充）

## 主要阵营与势力
（待补充）

## 主角设定
（待补充）

## 叙事节点与故事线
（待补充——故事的关键转折点、阶段性目标）

## 可能的结局方向
（待补充——故事可能走向的几种结局）

---
*此文档可在世界管理中查看和编辑。探索过程中会逐步完善。*
"""
        with open(os.path.join(world_path, "world-framework.md"), "w") as f:
            f.write(framework)

        # Initialize state files
        from state import write_json
        init_world = {
            "meta": {"world_name": name, "version": "0.4.0", "total_rounds": 0, "current_round": 0},
            "time": {"year": 1, "month": 1, "day": 1, "hour": 8, "period": "清晨", "era": "元年", "dynasty": ""},
            "geography": {"current_region": "main", "regions": {}},
            "factions": [],
            "global_events": {"active": [], "pending": [], "completed": []}
        }
        write_json(os.path.join(world_path, "state"), "world.json", init_world)
        write_json(os.path.join(world_path, "state"), "protagonist.json", {"name": "主角", "realm": "凡人", "attributes": {}, "skills": [], "inventory": [], "action_log": [], "_risk": 5})
        write_json(os.path.join(world_path, "state"), "characters.json", {"characters": []})
        write_json(os.path.join(world_path, "state"), "quests.json", {"active": [], "completed": [], "failed": [], "templates": []})
        write_json(os.path.join(world_path, "state"), "relationships.json", {"relations": []})
        write_json(os.path.join(world_path, "memory"), "index.json", {"recent": [], "medium": [], "milestones": []})
        # Create default config files
        write_json(os.path.join(world_path, "config"), "system-personality.json", {
            "type": "世界同行者", "name": "系统",
            "speech_patterns": {"greeting": "温暖的语气，偶尔俏皮", "task_issuance": "清晰说明后加鼓励", "danger_warning": "认真严肃"},
            "task_generation_philosophy": {"difficulty_progression": "渐进式", "world_integration": "根植于世界状态", "player_agency": "提供方向但不规定方法"}
        })
        write_json(os.path.join(world_path, "config"), "world-setting.json", {"world_type": world_type, "era": "自定义", "themes": []})
        write_json(os.path.join(world_path, "config"), "agent-constraints.json", {"version": "0.4.0", "global_constraints": {}, "agents": {}})
        with open(os.path.join(world_path, "chronicle", "volume-01.md"), "w") as f:
            f.write(f"# {name} — 第一卷\n\n*（叙事尚未开始。）*\n")
        with open(os.path.join(world_path, "chronicle", "timeline.md"), "w") as f:
            f.write("# 叙事时间线\n\n")

        # Switch to new world
        config.switch_world(name)
        config.refresh_paths()

        self._send_json({"status": "ok", "name": name})

    def _handle_create_world_v2(self, body):
        name = body.get("name", "").strip()
        world_package = body.get("world_package", {})
        selected_character_id = body.get("selected_character", "")

        if not self._validate_world_name(name):
            self._send_json({"error": "世界名称不能为空"}, 400)
            return
        if not world_package:
            self._send_json({"error": "缺少世界包数据"}, 400)
            return
        if not selected_character_id:
            self._send_json({"error": "请选择要扮演的角色"}, 400)
            return

        world_path = os.path.join(config.WORLDS_DIR, name)
        if os.path.exists(world_path):
            self._send_json({"error": "世界已存在"}, 409)
            return

        source_text = world_package.get("_source_text") or world_package.get("world_summary", "")
        source_name = world_package.get("_source_name") or "world-package"
        compiled_canon = compile_canon_from_world_package(world_package, source_text, source_name)
        world_package = canonicalize_world_package(world_package, compiled_canon)

        for sub in ["state", "chronicle", "npc-cards", "memory", "config", "system"]:
            os.makedirs(os.path.join(world_path, sub), exist_ok=True)
        write_canon_files(world_path, compiled_canon)

        from state import write_json

        ws = world_package.get("world_state", {})
        world_type = world_package.get("world_type", "xuanhuan")
        agent_config = world_package.get("agent_config", {})
        init_world = {
            "meta": {
                "world_name": ws.get("world_name", name),
                "world_type": world_type,
                "agent_config": agent_config,
                "version": "0.5.0",
                "total_rounds": 0,
                "current_round": 0,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            "time": ws.get("time", {"year": 1, "month": 1, "day": 1, "hour": 8, "period": "清晨", "era": "元年", "dynasty": ""}),
            "geography": ws.get("geography", {"current_region": "main", "regions": {}}),
            "factions": ws.get("factions", []),
            "global_events": {
                "active": [],
                "pending": ws.get("global_events", []),
                "completed": [],
            },
        }
        write_json(os.path.join(world_path, "state"), "world.json", init_world)

        all_characters = []
        playable = world_package.get("playable_characters", [])
        npcs = world_package.get("npcs", [])

        def _ensure_id(char, fallback_prefix, idx):
            cid = char.get("id")
            if cid:
                return cid
            name = char.get("name", "")
            if name:
                return name
            return f"{fallback_prefix}-{idx + 1:03d}"

        for pi, pc in enumerate(playable):
            pc_id = _ensure_id(pc, "pc", pi)
            pc_key = pc_id
            is_selected = pc_key == selected_character_id
            char_entry = {
                "id": pc_id,
                "name": pc.get("name"),
                "player_controlled": is_selected,
                "has_system": pc.get("has_system", False) if is_selected else False,
                "system_name": pc.get("system_name", "") if is_selected else "",
                "role": "玩家角色" if is_selected else "可选角色（未选中）",
                "region": pc.get("region"),
                "location": pc.get("region"),
                "age": pc.get("age"),
                "gender": pc.get("gender"),
                "appearance": pc.get("appearance"),
                "personality": pc.get("personality"),
                "desires": [pc.get("core_motivation", "")],
                "fears": [],
                "secrets": [],
                "realm": pc.get("realm", "凡人"),
                "specialties": pc.get("specialties", []),
                "daily_routine": pc.get("daily_routine", {}),
                "backstory": pc.get("backstory", ""),
                "status": "活跃",
            }
            all_characters.append(char_entry)

        for ni, npc in enumerate(npcs):
            npc_id = _ensure_id(npc, "npc", ni)
            npc_entry = {
                "id": npc_id,
                "name": npc.get("name"),
                "player_controlled": False,
                "has_system": False,
                "role": npc.get("role"),
                "region": npc.get("region"),
                "location": npc.get("location", npc.get("region", "")),
                "age": npc.get("age"),
                "gender": npc.get("gender"),
                "appearance": npc.get("appearance"),
                "personality": npc.get("personality"),
                "desires": npc.get("desires", []),
                "fears": npc.get("fears", []),
                "secrets": npc.get("secrets", []),
                "realm": npc.get("realm", "凡人"),
                "specialties": npc.get("specialties", []),
                "limitations": npc.get("limitations", []),
                "speech_style": npc.get("speech_style", ""),
                "daily_routine": npc.get("daily_routine", {}),
                "narrative_hooks": npc.get("narrative_hooks", []),
                "status": "活跃",
            }
            all_characters.append(npc_entry)

        write_json(os.path.join(world_path, "state"), "characters.json", {
            "meta": {"total_characters": len(all_characters), "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")},
            "characters": all_characters,
        })

        player_char = next((c for c in all_characters if c.get("player_controlled")), None)
        if player_char:
            sys_default = agent_config.get("system", {}) if agent_config else {}
            default_has_system = sys_default.get("enabled", True) if world_type != "modern" else False
            default_system_name = sys_default.get("name", "系统")
            write_json(os.path.join(world_path, "state"), "protagonist.json", {
                "name": player_char["name"],
                "realm": player_char.get("realm", "凡人"),
                "attributes": {},
                "skills": player_char.get("specialties", []),
                "inventory": [],
                "action_log": [],
                "_risk": 5,
                "has_system": player_char.get("has_system", default_has_system),
                "system_name": player_char.get("system_name", default_system_name),
                "backstory": player_char.get("backstory", ""),
                "personality": player_char.get("personality", ""),
            })

        write_json(os.path.join(world_path, "state"), "quests.json", {
            "active": [], "completed": [], "failed": [], "templates": [],
        })

        init_rels = world_package.get("relationships", [])
        write_json(os.path.join(world_path, "state"), "relationships.json", {"relations": init_rels})

        # The SQLite ledger is the durable evidence trail for later chapter
        # compilation.  JSON remains the live projection used by legacy agents.
        ledger = StoryLedger(world_path)
        ledger.bootstrap(ws.get("world_name", name), player_char)
        creation_event = ledger.append_event(
            "world_created",
            actor_id=player_char.get("id") if player_char else None,
            origin="world_creator",
            visibility="world",
            payload={
                "world_name": ws.get("world_name", name),
                "player_character": player_char.get("name") if player_char else "",
                "world_type": ws.get("world_type", ""),
            },
        )
        for character in all_characters:
            if character.get("id"):
                ledger.upsert_fact(
                    subject_id=character["id"],
                    predicate="location",
                    object_value=character.get("location") or character.get("region") or "未知",
                    source_event_id=creation_event["id"],
                    metadata={"name": character.get("name", "")},
                )
        for ni, npc in enumerate(npcs):
            npc_id = _ensure_id(npc, "npc", ni)
            for hook in npc.get("narrative_hooks", []):
                hook_text = hook.get("hook", "") if isinstance(hook, dict) else str(hook)
                if hook_text:
                    ledger.add_foreshadow(
                        hook_text[:80],
                        hook.get("trigger", hook_text) if isinstance(hook, dict) else hook_text,
                        importance=hook.get("importance", "moderate") if isinstance(hook, dict) else "moderate",
                        planted_event_id=creation_event["id"],
                        metadata={"character_id": npc_id, "character_name": npc.get("name", "")},
                    )

        for ni, npc in enumerate(npcs):
            npc_id = _ensure_id(npc, "npc", ni)
            npc_region = npc.get("region", "unknown")
            region_dir = os.path.join(world_path, "npc-cards", npc_region)
            os.makedirs(region_dir, exist_ok=True)
            card = {
                "id": npc_id,
                "name": npc.get("name"),
                "role": npc.get("role"),
                "region": npc_region,
                "status": "alive",
                "first_appearance": "",
                "profile": {
                    "age": npc.get("age"),
                    "gender": npc.get("gender"),
                    "appearance": npc.get("appearance"),
                    "personality": npc.get("personality"),
                    "desires": npc.get("desires", []),
                    "fears": npc.get("fears", []),
                    "secrets": npc.get("secrets", []),
                    "speech_style": npc.get("speech_style", ""),
                },
                "abilities": {
                    "cultivation": npc.get("realm", "凡人"),
                    "specialties": npc.get("specialties", []),
                    "limitations": npc.get("limitations", []),
                },
                "narrative_hooks": npc.get("narrative_hooks", []),
                "created_by": "world-creator-v2",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            safe_npc_filename = npc_id.replace("/", "_").replace("\\", "_")
            with open(os.path.join(region_dir, f"{safe_npc_filename}.json"), "w") as f:
                json.dump(card, f, ensure_ascii=False, indent=2)

        def init_world_character_memory(char_id, char_name, char_type):
            write_json(os.path.join(world_path, "memory"), f"{char_id}.json", {
                "char_id": char_id,
                "char_name": char_name,
                "char_type": char_type,
                "recent": [],
                "milestones": [],
                "compressed": [],
                "relationships": {},
            })

        for c in all_characters:
            ctype = "protagonist" if c.get("player_controlled") else "npc"
            init_world_character_memory(c["id"], c["name"], ctype)
            if ctype == "protagonist":
                init_world_character_memory("protagonist", c["name"], ctype)

        framework = world_package.get("world_summary", f"# {name}\n\n世界概述待补充。")
        with open(os.path.join(world_path, "world-framework.md"), "w") as f:
            f.write(framework)

        with open(os.path.join(world_path, "world.json"), "w") as f:
            json.dump({
                "name": name,
                "type": ws.get("world_name", "自定义"),
                "created": time.strftime("%Y-%m-%d"),
                "description": framework[:200],
            }, f, ensure_ascii=False, indent=2)

        write_json(os.path.join(world_path, "memory"), "index.json", {
            "meta": {
                "owner": player_char["id"] if player_char else "protagonist",
                "last_compaction": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "total_memories": 0,
            },
            "memory_timeline": [],
        })

        with open(os.path.join(world_path, "chronicle", "volume-01.md"), "w") as f:
            f.write(f"# {name} — 第一卷\n\n> {framework[:200]}\n\n---\n\n*（叙事尚未开始。世界的舞台已经搭好，等待你的第一步。）*\n")
        with open(os.path.join(world_path, "chronicle", "timeline.md"), "w") as f:
            f.write("# 叙事时间线\n\n| 日期 | 轮次 | 地点 | 关键事件 | 涉及角色 | 章节 |\n|------|------|------|----------|----------|------|\n| *（叙事尚未开始）* | | | | | |\n")

        write_json(os.path.join(world_path, "config"), "system-personality.json", {
            "type": "世界同行者", "name": "系统",
            "speech_patterns": {"greeting": "温暖的语气，偶尔俏皮", "task_issuance": "清晰说明后加鼓励", "danger_warning": "认真严肃"},
            "task_generation_philosophy": {"difficulty_progression": "渐进式", "world_integration": "根植于世界状态", "player_agency": "提供方向但不规定方法"},
        })
        write_json(os.path.join(world_path, "config"), "world-setting.json", {"world_type": ws.get("world_name", ""), "era": ws.get("time", {}).get("era", ""), "themes": []})
        write_json(os.path.join(world_path, "config"), "agent-constraints.json", {"version": "0.4.0", "global_constraints": {}, "agents": {}})

        config.switch_world(name)
        config.refresh_paths()
        try:
            from risk import reset_risk
            reset_risk()
        except Exception:
            pass

        player_name = player_char["name"] if player_char else "未知"
        self._send_json({
            "status": "ok",
            "name": name,
            "player_character": player_name,
            "total_characters": len(all_characters),
            "canon": canon_summary(world_path),
        })

    def _handle_world_chat(self, body):
        api_key, base_url, model = self._get_api_config()
        if not api_key:
            self._send_json({"error": "缺少 API 密钥"}, 400)
            return

        messages = body.get("messages", [])
        if not messages:
            self._send_json({"error": "缺少对话内容"}, 400)
            return

        from agents.base import call_deepseek

        system_prompt = """你是一位世界架构师——专业、富有想象力、严谨。你通过对话帮助用户从零构建一个完整的虚构世界。你不是在填表，你是在唤醒一个世界。

## 核心原则
1. 内部一致性高于一切——每条规则、历史事件、地理特征必须不矛盾。矛盾摧毁可信度。
2. 展示胜于灌输——把世界观融入具体场景中讨论，而不是罗列设定条目。
3. 势力需要欲望，不只是标签——每个阵营/组织都要有公开目标、隐藏意图、资源限制、敌对关系。
4. 地理塑造文化——气候、地形、资源决定文明如何发展、贸易、战争、建筑。
5. 规则先于例外——先建立世界的基本法则，再引入特殊案例。
6. 历史创造当下——过去的战争、灾难、发现必须直接引发当前世界的冲突和联盟。
7. 基调是与用户之间的契约——一旦确立，后续所有设定都要保持一致的基调。

## 世界类型映射
用户描述世界类型时，请对应到以下类型ID之一，并在后续设定中保持一致的术语体系：
- "xuanhuan"：东方玄幻（灵气、修为、宗门、丹药、法宝）—region_type用"主城|宗门|荒野|秘境|村庄"
- "xianxia"：古典仙侠（仙道、飞剑、洞府、天劫、仙门）—region_type用"仙山|洞府|凡尘|秘境|妖域"
- "western_fantasy"：西方奇幻（魔法、骑士、龙、精灵、法师塔）—region_type用"城堡|城镇|森林|地下城|王国"
- "scifi"：赛博朋克/科幻（义体、算力、企业、黑客、太空）—region_type用"城区|企业区|地下|太空站|废土"
- "modern"：现代都市（都市、悬疑、职场、日常）—region_type用"商圈|住宅区|公司|街道|公共场所"
- "post_apoc"：末日废土（辐射、变异、避难所、拾荒）—region_type用"避难所|废墟|聚落|辐射区|荒野"
- "custom"：融合创新/自定义（根据用户描述灵活设定）

## 渐进式引导（严格按此顺序，不跳跃）
第1阶段：世界基石
- 世界的名字和一句话描述
- **必须首先确定世界类型（对应上面7种之一）**——这决定了后续所有术语和规则
- 时代背景和技术/魔法/力量水平
- 核心基调（黑暗沉重/热血燃向/轻松治愈/悬疑诡秘/史诗壮阔）
- 2-3个核心主题
- **主角是否有系统/随身伙伴？** 如果有，系统是什么性格？（如：傲娇养成系、冰冷AI、温柔精灵、情报贩子）

第2阶段：世界法则
- 这个世界的核心力量体系是什么（灵气/魔法/科技/超能力/基因改造等）
- 力量体系的规则、层级、代价、限制——约束比能力更重要
- 世界的基本物理/魔法法则——什么是可能的，什么是不可能的
- 如果存在多种体系，它们如何共存或冲突

第3阶段：地理与历史
- 世界的地理概貌——大陆、海洋、气候区
- 选择1-2个核心区域深度展开
- 过去发生过什么重大事件直接塑造了现在——战争、灾难、发现、背叛
- 不同地区的资源分布如何影响贸易和冲突

第4阶段：势力与阵营
- 至少设计3个主要势力，彼此之间有明确的盟友/敌对/中立关系
- 每个势力：公开目标、隐藏意图、掌控的资源、敌人、在故事中的作用
- 势力之间的动态——为什么还没有全面开战？脆弱平衡靠什么维持？

第5阶段：文化与人物
- 核心区域的文化特征——习俗、信仰、节日、禁忌、审美
- 社会结构——谁掌权、谁被压迫、谁在夹缝中游走
- 主角的设定——名字、身份、性格、核心动机、独特之处
- 2-3个关键NPC——他们和主角的关系、各自的目标和秘密

第6阶段：故事引擎
- 世界的核心冲突是什么——是什么正在打破平衡
- 主角的起点状态和可能的成长轨迹
- 至少2-3条叙事钩子——可以由此展开的故事线索
- 这个世界最特别的地方——有什么是其他世界没有的

## 对话风格
- 每次只问1-2个问题，不要一下子抛出太多
- 根据用户的回答深入挖掘——追问"为什么""之前发生了什么""这个选择有什么代价"
- 给用户提供选项时也留出自由发挥空间
- 时刻记住之前所有对话中建立的事实，确保不矛盾
- 当用户对某个方面不感兴趣时，快速跳过，不要强迫
- 热情但不浮夸——用专业的世界架构师语气，而不是推销员

## 输出世界摘要
当用户说"差不多了"或信息足够时，生成一份结构清晰的世界设定摘要，包含：
1. 世界概述（名字、类型、基调、核心主题）
2. 核心法则（力量体系、规则、限制）
3. 地理与历史概要
4. 主要阵营与势力关系
5. 主角设定
6. 核心冲突与故事方向
7. 这个世界最特别之处

摘要要有画面感——不只是列清单，而是让人读完能在脑海中看到这个世界的一角。

## 第7阶段：结构化世界包（第一步——框架与角色概要）
当用户确认世界观设定完成时，你必须输出一个结构化世界包。这是机器可读的 JSON 数据。

输出格式必须是严格的 JSON（不要用 markdown 代码块包裹）：
{
  "mode": "world_package",
  "world_package": {
    "world_type": "xuanhuan|xianxia|western_fantasy|scifi|modern|post_apoc|custom",
    "world_state": {
      "world_name": "世界名",
      "time": {"year": 数字, "month": 数字, "day": 数字, "era": "年号", "dynasty": "朝代"},
      "geography": {
        "current_region": "起始地区id",
        "regions": {
          "地区id": {
            "name": "地区名",
            "type": "主城|宗门|荒野|秘境|村庄",
            "description": "生动的地区描述，至少100字",
            "size": "小型|中型|大型|超大型",
            "population": 数字,
            "climate": "气候描述",
            "landmarks": [
              {"name": "地标名", "type": "市集|武馆|军营|茶楼|危险区域|修炼场所|情报据点", "description": "描述"}
            ],
            "neighbors": ["相邻地区id"]
          }
        }
      },
      "factions": [
        {
          "id": "kebab-case势力id",
          "name": "势力名",
          "type": "官方势力|商业势力|民间势力|修仙宗门|黑暗势力",
          "power_level": 1到10,
          "territory": "势力范围描述",
          "leader": "首领名",
          "description": "势力描述，至少80字",
          "public_goal": "公开目标",
          "hidden_agenda": "隐藏意图"
        }
      ],
      "global_events": [
        {
          "id": "事件id",
          "name": "事件名",
          "type": "势力冲突|自然现象|隐秘事件|社会动荡",
          "trigger_condition": "触发条件",
          "description": "事件描述",
          "phases": [
            {"phase": 1, "name": "阶段名", "description": "阶段描述"}
          ],
          "related_factions": ["势力id"],
          "importance": "major|moderate|minor"
        }
      ]
    },
    "playable_characters": [
      {
        "id": "kebab-case角色id",
        "name": "角色名",
        "aliases": ["称号"],
        "age": 数字,
        "gender": "男|女",
        "core_motivation": "核心动机（一句话）",
        "region": "起始地区id",
        "realm": "当前能力等级（根据世界类型填写：修真境界/义体等级/魔法阶位/职业等级等）",
        "has_system": true或false,
        "system_name": "系统名（仅has_system为true时填写）",
        "suggested_story_direction": "建议的故事方向（一句话）"
      }
    ],
    "npcs": [
      {
        "id": "kebab-case角色id",
        "name": "NPC名",
        "role": "角色定位（一句话）",
        "region": "所在地区id",
        "location": "具体地点"
      }
    ],
    "relationships": [
      {"source": "角色名", "target": "角色名", "type": "关系类型", "description": "关系描述"}
    ],
    "agent_config": {
      "narrator": {
        "role": "根据世界类型决定的叙事者角色（如：东方玄幻小说家、赛博朋克科幻作家等）",
        "style": "叙事风格描述",
        "chapter_title_style": "章节标题风格"
      },
      "world_engine": {
        "role": "世界引擎角色描述"
      },
      "system": {
        "enabled": true或false,
        "name": "系统/伙伴名称（如：系统、NEXUS、指引精灵）",
        "personality": "系统性格描述",
        "relationship": "与主角的关系类型"
      }
    },
    "world_summary": "给用户看的完整世界摘要（markdown格式）"
  }
}

关键要求：
1. playable_characters 必须提供 3-5 个有吸引力的选择，每个角色身份、动机、故事方向各不相同
2. 至少有一个 playable_character 的 has_system 为 true（如果world_type对应默认有系统的话）
3. 每个 playable_character 必须和至少一个 NPC 有初始关系
4. npcs 至少 3 个，最多 8 个
5. 初始事件必须关联到具体角色和势力
6. 每个地区的 landmarks 至少 2 个
7. 世界至少包含 2 个地区
8. 势力至少 3 个，两两之间有明确的盟友/敌对/中立关系
9. playable_characters 只需要概要信息（名字、动机、修为/能力等级、是否有系统），详细设定会在用户选择角色后单独生成
10. npcs 只需要概要信息（名字、定位、位置），详细设定会在用户选择角色后单独生成
11. **world_type必须填写，从指定的7种中选择**
12. **agent_config必须根据world_type和用户对话中提到的设定填写**
13. **realm字段要符合世界类型：玄幻/仙侠用修为境界，科幻用义体等级/权限等级，西幻用魔法等级/骑士阶位，现代用职业/社会地位，末日用生存等级**"""

        messages_payload = [{"role": "system", "content": system_prompt}]
        for m in messages:
            messages_payload.append({"role": m.get("role", "user"), "content": m.get("content", "")})

        import urllib.request
        url = f"{base_url}/v1/chat/completions"
        payload = {
            "model": model,
            "messages": messages_payload,
            "max_tokens": 8192,
            "temperature": 0.8,
        }
        body_raw = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body_raw, headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }, method="POST")

        from agents.base import create_opener
        opener = create_opener()

        try:
            with opener.open(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                content = data["choices"][0]["message"]["content"]
                finish_reason = data["choices"][0].get("finish_reason", "")
                parsed = _try_parse_world_json(content)
                if parsed and isinstance(parsed, dict) and parsed.get("mode") == "world_package":
                    package = parsed.get("world_package", {}) or {}
                    source_text = "\n\n".join(str(m.get("content", "")) for m in messages if isinstance(m, dict))
                    package["_source_text"] = source_text or package.get("world_summary", "")
                    package["_source_name"] = "world-chat"
                    canon_draft = compile_canon_from_world_package(package, package["_source_text"], "world-chat")
                    package["canon_summary"] = canon_summary(canon_draft)
                    if finish_reason == "length":
                        self._send_json({
                            "mode": "world_package_incomplete",
                            "world_package": package,
                            "warning": "世界包生成不完整，部分数据可能缺失，但不影响使用。",
                            "canon": canon_summary(canon_draft),
                        })
                    else:
                        self._send_json({
                            "mode": "world_package",
                            "world_package": package,
                            "world_summary": package.get("world_summary", ""),
                            "canon": canon_summary(canon_draft),
                        })
                    return
                self._send_json({"reply": content})
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_world_generate_details(self, body):
        api_key, base_url, model = self._get_api_config()
        if not api_key:
            self._send_json({"error": "缺少 API 密钥"}, 400)
            return

        world_package = body.get("world_package", {})
        selected_character_id = body.get("selected_character", "")
        if not world_package or not selected_character_id:
            self._send_json({"error": "缺少世界包或角色选择"}, 400)
            return

        from agents.base import call_deepseek
        from agent_templates import get_preset

        playable_chars = world_package.get("playable_characters", [])
        npc_overview = world_package.get("npcs", [])
        selected_char = next((c for c in playable_chars if (c.get("id") or c.get("name")) == selected_character_id), None)
        if not selected_char:
            self._send_json({"error": "未找到所选角色"}, 400)
            return

        wt = world_package.get("world_type", "xuanhuan")
        preset = get_preset(wt)
        we_cfg = preset.get("world_engine", {})
        narrator_role = preset.get("narrator", {}).get("role", "世界架构师")
        realm_label = we_cfg.get("power_system", "能力等级")

        system_prompt = f"""你是{narrator_role}的详细设定生成器。用户已经通过对话建立了世界框架并选择了主角，现在你需要为选中的主角和所有NPC生成完整的详细设定。

输出严格的 JSON 格式（不要用 markdown 代码块包裹）：
{{
  "selected_character_detail": {{
    "appearance": "外貌描述，至少80字",
    "personality": "性格描述，至少包含2个正面特质和1个缺陷",
    "backstory": "背景故事，至少150字",
    "specialties": ["特长能力"],
    "special_items": ["特殊物品名称和描述"],
    "daily_routine": {{
      "清晨": "日常行为",
      "上午": "日常行为",
      "下午": "日常行为",
      "傍晚": "日常行为"
    }}
  }},
  "npc_details": [
    {{
      "id": "与概要中相同的npc id",
      "name": "NPC名",
      "age": 数字,
      "gender": "男|女",
      "appearance": "外貌描述",
      "personality": "性格描述（至少包含2个正面特质和1个缺陷）",
      "desires": ["至少1个欲望/目标"],
      "fears": ["至少1个恐惧/弱点"],
      "secrets": ["至少1个秘密"],
      "realm": "{realm_label}",
      "specialties": ["特长"],
      "limitations": ["弱点或限制"],
      "speech_style": "说话风格描述",
      "relationship_to_player_characters": "与主角的关系说明",
      "narrative_hooks": [
        {{"hook": "潜在叙事钩子", "trigger": "触发条件", "importance": "minor|moderate|major"}}
      ],
      "daily_routine": {{
        "清晨": "日常行为",
        "上午": "日常行为",
        "下午": "日常行为",
        "傍晚": "日常行为"
      }}
    }}
  ]
}}

关键要求：
1. 每个NPC必须有独立的欲望和秘密——不能是工具人
2. NPC与主角的关系必须具体，不能只写"认识"
3. daily_routine 要符合角色身份和所在地区
4. **realm字段必须使用符合{wt}世界观的术语**（如修为境界/义体等级/魔法阶位/职业等级等），不能统一写"修为"
5. 所有术语、物品名称、力量体系都要符合{wt}类型世界观"""

        user_prompt = json.dumps({
            "instruction": f"用户选择了主角「{selected_char.get('name', '')}」，请为该主角和所有NPC生成详细设定。",
            "world_summary": world_package.get("world_summary", ""),
            "selected_character": selected_char,
            "npc_overview": npc_overview,
            "world_state": {
                "regions": world_package.get("world_state", {}).get("geography", {}).get("regions", {}),
                "factions": world_package.get("world_state", {}).get("factions", []),
            },
        }, ensure_ascii=False)

        try:
            output = call_deepseek(system_prompt, user_prompt, api_key=api_key, base_url=base_url, model=model, max_tokens=8192)
            self._send_json({"mode": "world_details", "details": output})
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_upload_doc(self):
        api_key, base_url, model = self._get_api_config()
        if not api_key:
            self._send_json({"error": "缺少 API 密钥"}, 400)
            return

        content_type = self.headers.get("Content-Type", "")
        file_content = None
        filename = "unknown.txt"

        if "multipart/form-data" in content_type:
            boundary = None
            for part in content_type.split(";"):
                part = part.strip()
                if part.startswith("boundary="):
                    boundary = part[9:].strip('"')
                    break
            if not boundary:
                self._send_json({"error": "无法解析上传文件"}, 400)
                return
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length)

            import email
            from email.parser import BytesParser
            from email.policy import default

            msg_bytes = b"Content-Type: multipart/form-data; boundary=" + boundary.encode() + b"\r\n\r\n" + raw_body
            msg = BytesParser(policy=default).parsebytes(msg_bytes)

            if msg.is_multipart():
                for part in msg.iter_parts():
                    cd = str(part.get('Content-Disposition', ''))
                    if 'filename=' in cd:
                        filename = part.get_filename() or "unknown.txt"
                        file_content = part.get_payload(decode=True)
                        break
            else:
                file_content = raw_body
                filename = "uploaded_file.txt"
        else:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length) if content_length > 0 else b""
            file_content = raw_body
            filename = "uploaded_file.txt"

        if file_content is None:
            self._send_json({"error": "未找到上传文件"}, 400)
            return

        # 统一转为纯文本
        if isinstance(file_content, bytes):
            ext = os.path.splitext(filename)[1].lower()
            text = extract_text(file_content, ext, filename)
        elif isinstance(file_content, str):
            text = file_content
        else:
            text = str(file_content)

        if not text or len(text.strip()) < 50:
            self._send_json({"error": "文件内容过短，无法解析。建议上传至少100字的文档。"}, 400)
            return

        raw_text = text
        if len(text) > 60000:
            text = summarize_long_text(text, api_key, base_url, model)

        world_package = _parse_document_to_world(text, filename, api_key, base_url, model)

        if not world_package:
            self._send_json({"error": "文档解析失败，请重试或切换到对话模式手动创建。"}, 500)
            return

        world_package["_source_text"] = raw_text
        world_package["_source_name"] = filename
        canon_draft = compile_canon_from_world_package(world_package, raw_text, filename)
        world_package["canon_summary"] = canon_summary(canon_draft)

        self._send_json({
            "mode": "world_package",
            "world_package": world_package,
            "world_summary": world_package.get("world_summary", ""),
            "source_document": filename,
            "canon": canon_summary(canon_draft),
        })

    def _require_current_world_path(self):
        world_name = config.current_world_name()
        if not world_name:
            self._send_json({"error": "请先创建或切换世界"}, 404)
            return None, None
        world_path = config.world_dir()
        if not os.path.isdir(world_path):
            self._send_json({"error": "当前世界目录不存在"}, 404)
            return None, None
        return world_name, world_path

    def _handle_canon_status(self):
        world_name, world_path = self._require_current_world_path()
        if not world_path:
            return
        migration_report = {}
        migration_report_path = os.path.join(world_path, "canon", "migration_report.json")
        if os.path.exists(migration_report_path):
            try:
                with open(migration_report_path, "r", encoding="utf-8") as handle:
                    migration_report = json.load(handle)
            except Exception:
                migration_report = {}
        self._send_json({
            "world": world_name,
            **canon_summary(world_path),
            "needs_reset": not canon_exists(world_path),
            "last_migration_report": migration_report,
        })

    def _handle_canon_source(self):
        world_name, world_path = self._require_current_world_path()
        if not world_path:
            return
        canon = load_canon(world_path)
        self._send_json({"world": world_name, "source": canon.get("source_text", ""), "exists": bool(canon.get("source_text"))})

    def _handle_canon_bible(self):
        world_name, world_path = self._require_current_world_path()
        if not world_path:
            return
        canon = load_canon(world_path)
        self._send_json({
            "world": world_name,
            "world_bible": canon.get("world_bible", {}),
            "story_arcs": canon.get("story_arcs", {}),
            "constraints": canon.get("constraints", {}),
            "summary": canon_summary(world_path),
        })

    def _handle_canon_conflicts(self):
        world_name, world_path = self._require_current_world_path()
        if not world_path:
            return
        canon = load_canon(world_path)
        conflicts = canon.get("conflicts", {}).get("items", []) if isinstance(canon.get("conflicts"), dict) else []
        self._send_json({"world": world_name, "conflicts": conflicts})

    def _handle_canon_recompile(self, body):
        world_name, world_path = self._require_current_world_path()
        if not world_path:
            return
        source_text = body.get("source") or load_canon(world_path).get("source_text", "")
        if not source_text.strip():
            fw_path = os.path.join(world_path, "world-framework.md")
            if os.path.exists(fw_path):
                with open(fw_path, "r", encoding="utf-8") as handle:
                    source_text = handle.read()
        if not source_text.strip():
            self._send_json({"error": "未找到可编译的 Canon 原始脚本"}, 400)
            return
        try:
            world_state = read_json(os.path.join(world_path, "state"), "world.json")
        except Exception:
            world_state = {"meta": {"world_name": world_name}, "geography": {"current_region": "", "regions": {}}}
        package = {
            "name": world_name,
            "world_type": world_state.get("meta", {}).get("world_type", "自定义") if isinstance(world_state, dict) else "自定义",
            "world_summary": source_text[:4000],
            "world_state": {
                "world_name": world_state.get("meta", {}).get("world_name", world_name) if isinstance(world_state, dict) else world_name,
                "time": world_state.get("time", {}) if isinstance(world_state, dict) else {},
                "geography": world_state.get("geography", {}) if isinstance(world_state, dict) else {},
                "factions": world_state.get("factions", []) if isinstance(world_state, dict) else [],
                "global_events": (world_state.get("global_events", {}) or {}).get("pending", []) if isinstance(world_state, dict) else [],
            },
        }
        compiled = compile_canon_from_world_package(package, source_text, body.get("source_name", "manual-recompile"))
        write_canon_files(world_path, compiled)
        self._send_json({"status": "ok", "world": world_name, "canon": canon_summary(world_path)})

    def _handle_canon_reset_world(self, body):
        world_name = (body.get("name") or config.current_world_name()).strip()
        if not self._validate_world_name(world_name):
            self._send_json({"error": "世界名称无效"}, 400)
            return
        try:
            report = reset_world_from_canon(
                world_name,
                source_text=body.get("source") or None,
                source_name=body.get("source_name", "api-reset"),
                world_package=body.get("world_package") if isinstance(body.get("world_package"), dict) else None,
            )
            config.switch_world(world_name)
            self._send_json({"status": "ok", "report": report, "canon": canon_summary(config.world_dir())})
        except FileNotFoundError as e:
            self._send_json({"error": str(e)}, 404)
        except ValueError as e:
            self._send_json({"error": str(e)}, 400)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_canon_conflict_resolve(self, body):
        world_name, world_path = self._require_current_world_path()
        if not world_path:
            return
        conflict_id = body.get("id") or body.get("conflict_id")
        if not conflict_id:
            self._send_json({"error": "缺少冲突 id"}, 400)
            return
        data = resolve_conflict(world_path, conflict_id, body.get("status", "resolved"), body.get("note", ""))
        self._send_json({"status": "ok", "world": world_name, "conflicts": data.get("items", [])})

    def _handle_framework_update(self, body):
        """Update or get world framework document."""
        name = (body.get("name") or config.current_world_name()).strip()
        content = body.get("content", "")
        mode = body.get("mode", "get")  # get or save

        if not self._validate_world_name(name):
            self._send_json({"error": "世界名称无效"}, 400)
            return

        world_path = os.path.join(config.WORLDS_DIR, name)
        if not os.path.isdir(world_path):
            self._send_json({"error": "世界不存在"}, 404)
            return

        fw_path = os.path.join(world_path, "world-framework.md")

        if mode == "save" and content:
            with open(fw_path, "w") as f:
                f.write(content)
            if body.get("canon"):
                package = {
                    "name": name,
                    "world_summary": content,
                    "world_state": {"world_name": name, "geography": {"current_region": "", "regions": {}}},
                }
                compiled = compile_canon_from_world_package(package, content, "world-framework.md")
                write_canon_files(world_path, compiled)
            self._send_json({"status": "ok"})
        else:
            framework = ""
            if os.path.exists(fw_path):
                with open(fw_path) as f:
                    framework = f.read()
            self._send_json({"name": name, "framework": framework})

    def _extract_realms_from_framework(self, framework_text):
        import re as _re
        if not framework_text:
            return [], ""
        system_name = ""
        realms = []
        arrow_match = _re.search(r'(?:境界|等级|阶位|修为等级|力量等级|等级体系)[^（\n]*?[：:]\s*([^\n。；;]+(?:→|->)[^\n。；;]+)', framework_text)
        if not arrow_match:
            arrow_match = _re.search(r'[（(]([^（)）\n]{2,200}?(?:→|->)[^（)）\n]{2,200}?)[)）]', framework_text)
        if arrow_match:
            raw = arrow_match.group(1)
            pre_text = framework_text[:arrow_match.start() + 80]
            if "修炼" in pre_text and ("体系" in pre_text or "境界" in pre_text):
                system_name = "境界"
            elif "魔法" in pre_text and ("体系" in pre_text or "等级" in pre_text):
                system_name = "等级"
            elif "武道" in pre_text and ("体系" in pre_text or "境界" in pre_text):
                system_name = "境界"
            elif "力量" in pre_text and ("体系" in pre_text or "等级" in pre_text):
                system_name = "等级"
            elif "境界" in pre_text:
                system_name = "境界"
            elif "等级" in pre_text or "阶位" in pre_text:
                system_name = "等级"
            else:
                system_name = "等级"
            parts = _re.split(r'\s*(?:→|->|／|/)\s*', raw)
            realms = [p.strip() for p in parts if p.strip() and len(p.strip()) <= 10 and not _re.match(r'^[（(]', p.strip())]
        if not realms:
            dun_match = _re.search(r'(?:境界|等级|阶位)[^：:\n]*[：:]\s*([^\n。；;]+(?:、|，)[^\n。；;]+(?:、|，)[^\n。；;]+)', framework_text)
            if dun_match:
                raw = dun_match.group(1)
                parts = _re.split(r'\s*[、，,]\s*', raw)
                realms = [p.strip() for p in parts if p.strip() and len(p.strip()) <= 10]
        if not realms:
            jiu_match = _re.search(r'[九一二三四五六七八九十\d]+大?([境阶][界位]?)[^（\n]*?[（(]([^)）]+)[)）]', framework_text)
            if jiu_match:
                system_name = jiu_match.group(1) or "境界"
                raw = jiu_match.group(2)
                if '→' in raw or '->' in raw:
                    parts = _re.split(r'\s*(?:→|->)\s*', raw)
                else:
                    parts = _re.split(r'\s*[、，,]\s*', raw)
                realms = [p.strip() for p in parts if p.strip() and len(p.strip()) <= 10]
        return realms, system_name

    def _handle_get_world_realms(self):
        name = config.current_world_name()
        if not name:
            self._send_json({"realms": [], "system_name": ""})
            return
        world_path = os.path.join(config.WORLDS_DIR, name)
        realms_json_path = os.path.join(world_path, "state", "realms.json")
        if os.path.exists(realms_json_path):
            try:
                with open(realms_json_path, encoding="utf-8") as f:
                    data = json.load(f)
                self._send_json({"realms": data.get("realms", []), "system_name": data.get("system_name", "")})
                return
            except Exception:
                pass
        fw_path = os.path.join(world_path, "world-framework.md")
        framework = ""
        if os.path.exists(fw_path):
            try:
                with open(fw_path, encoding="utf-8") as f:
                    framework = f.read()
            except Exception:
                pass
        realms, system_name = self._extract_realms_from_framework(framework)
        if realms:
            try:
                os.makedirs(os.path.dirname(realms_json_path), exist_ok=True)
                with open(realms_json_path, "w", encoding="utf-8") as f:
                    json.dump({"realms": realms, "system_name": system_name}, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        self._send_json({"realms": realms, "system_name": system_name})

    def _handle_restart_world(self, body):
        """Clone world framework and start a fresh story."""
        name = (body.get("name") or config.current_world_name()).strip()
        if not self._validate_world_name(name):
            self._send_json({"error": "世界名称无效"}, 400)
            return
        src_path = os.path.join(config.WORLDS_DIR, name)
        if not os.path.isdir(src_path):
            self._send_json({"error": "世界不存在"}, 404)
            return

        # Generate new name
        import re
        base = re.sub(r'-\d+$', '', name)
        existing = [d for d in os.listdir(config.WORLDS_DIR) if d.startswith(base)]
        new_name = f"{base}-{len(existing) + 1}"

        # Create new world from framework
        new_path = os.path.join(config.WORLDS_DIR, new_name)
        for sub in ["state", "chronicle", "npc-cards", "memory", "config", "system"]:
            os.makedirs(os.path.join(new_path, sub), exist_ok=True)

        # Copy framework
        fw_src = os.path.join(src_path, "world-framework.md")
        if os.path.exists(fw_src):
            with open(fw_src) as f:
                framework = f.read()
            with open(os.path.join(new_path, "world-framework.md"), "w") as f:
                f.write(framework)

        # Copy config files
        for cf in ["system-personality.json", "world-setting.json", "agent-constraints.json"]:
            cf_src = os.path.join(src_path, "config", cf)
            if os.path.exists(cf_src):
                shutil.copy(cf_src, os.path.join(new_path, "config", cf))

        # Fresh meta
        with open(os.path.join(new_path, "world.json"), "w") as f:
            json.dump({"name": new_name, "type": "继承", "created": time.strftime("%Y-%m-%d"), "description": f"从「{name}」继承框架的新故事"}, f, ensure_ascii=False, indent=2)

        # Init fresh state
        from state import write_json
        init_world = {
            "meta": {"world_name": new_name, "version": "0.4.0", "total_rounds": 0, "current_round": 0},
            "time": {"year": 1, "month": 1, "day": 1, "hour": 8, "period": "清晨", "era": "元年", "dynasty": ""},
            "geography": {"current_region": "main", "regions": {}},
            "factions": [],
            "global_events": {"active": [], "pending": [], "completed": []}
        }
        write_json(os.path.join(new_path, "state"), "world.json", init_world)
        write_json(os.path.join(new_path, "state"), "protagonist.json", {"name": "", "realm": "凡人", "attributes": {}, "skills": [], "inventory": [], "action_log": [], "_risk": 5})
        write_json(os.path.join(new_path, "state"), "characters.json", {"characters": []})
        write_json(os.path.join(new_path, "state"), "quests.json", {"active": [], "completed": [], "failed": [], "templates": []})
        write_json(os.path.join(new_path, "state"), "relationships.json", {"relations": []})
        write_json(os.path.join(new_path, "memory"), "index.json", {"recent": [], "medium": [], "milestones": []})
        with open(os.path.join(new_path, "chronicle", "volume-01.md"), "w") as f:
            f.write(f"# {new_name} — 第一卷\n\n*（新故事从第1轮开始。）*\n")
        with open(os.path.join(new_path, "chronicle", "timeline.md"), "w") as f:
            f.write("# 叙事时间线\n\n")

        config.switch_world(new_name)
        config.refresh_paths()
        from risk import reset_risk
        reset_risk()

        self._send_json({"status": "ok", "name": new_name})

    def _handle_delete_world(self, body):
        name = body.get("name", "").strip()
        if not self._validate_world_name(name):
            self._send_json({"error": "缺少世界名称"}, 400)
            return
        world_path = os.path.join(config.WORLDS_DIR, name)
        if not os.path.isdir(world_path):
            self._send_json({"error": f"世界 '{name}' 不存在"}, 404)
            return

        was_current = name == config.current_world_name()
        if name == config.current_world_name():
            AUTO_STATE["paused"] = False
            AUTO_STATE["stop"] = True
            config.switch_world("")
            config.refresh_paths()
            try:
                from memory.chroma_store import reset_client
                reset_client()
            except Exception:
                pass

        try:
            shutil.rmtree(world_path)
        except Exception as error:
            self._send_json({"error": f"删除世界失败：{error}"}, 500)
            return

        if was_current:
            try:
                from memory.chroma_store import reset_client
                reset_client()
            except Exception:
                pass

        self._send_json(_world_status_payload(status="ok", deleted=name))

    def _handle_polish(self, body):
        api_key, base_url, model = self._get_api_config()
        if not api_key:
            self._send_json({"error": "缺少 API 密钥"}, 400)
            return

        text = body.get("text", "")
        mode = body.get("mode", "action")
        if not text:
            self._send_json({"polished": text})
            return

        from agents.base import call_deepseek

        if mode == "chapter":
            system_prompt = """你是一个专业的小说编辑润色助手。用户提供一段小说正文，请在保持原有情节、人物性格、对话内容不变的前提下，润色文字表达。

规则：
1. 优化描写的画面感和氛围感，让文字更生动
2. 改善语句流畅度，去除冗余和重复
3. 保持叙事视角、文风和节奏一致
4. 不要大幅改变原文结构和长度，不要添加新的情节
5. 保持段落划分，使用\n\n分隔段落

输出严格JSON格式：{"polished": "润色后的完整正文"}"""
            user_prompt = json.dumps({"text": text}, ensure_ascii=False)
            try:
                output = call_deepseek(system_prompt, user_prompt, api_key=api_key, base_url=base_url, model=model, max_tokens=4096)
                polished = output.get("polished", text) if isinstance(output, dict) else text
                self._send_json({"polished": polished or text})
            except Exception:
                self._send_json({"polished": text})
            return

        from state import get_player_character
        player = get_player_character() or {}
        player_name = player.get("name", "主角")
        player_personality = player.get("personality") or player.get("personality_profile") or "符合当前角色设定"
        player_backstory = player.get("backstory", "")
        context = body.get("context", "")
        system_prompt = f"""你是一个写作润色助手。用户会用口语化的方式描述主角{player_name}的行动，你需要将其润色成小说化的叙述。

规则：
1. 保持用户的原意和方向不变
2. 用第三人称，符合{player_name}的性格：{player_personality}
3. 加入适当的内心活动和环境细节，让行动更有画面感
4. 不要改变用户选择的行动方向（比如用户说战斗，你就写战斗；说逃跑，你就写逃跑）
5. 润色后长度在50-150字之间
6. 角色背景参考：{player_backstory[:200] if player_backstory else "以当前世界设定为准"}

输出JSON: {{"polished": "润色后的文本"}}"""

        user_prompt = json.dumps({
            "instruction": "润色以下主角行动描述，保持原意和方向，加入适当的叙事细节。",
            "original_text": text,
            "recent_context": context or "无",
        }, ensure_ascii=False)

        try:
            output = call_deepseek(system_prompt, user_prompt, api_key=api_key, base_url=base_url, model=model, max_tokens=512)
            self._send_json({"polished": output.get("polished", text)})
        except Exception:
            self._send_json({"polished": text})

    def _handle_inject(self, body):
        text = body.get("text", "").strip()
        if not text:
            self._send_json({"error": "注入内容不能为空"}, 400)
            return
        from state import add_injection
        add_injection(text)
        self._send_json({"status": "ok", "message": f"已注入: {text[:100]}"})

    def _handle_story_checkpoint(self, body):
        world_name = config.current_world_name()
        if not world_name:
            self._send_json({"error": "请先创建或切换世界"}, 404)
            return
        label = (body.get("label") or "").strip()
        try:
            checkpoint = StoryLedger(config.world_dir()).create_checkpoint(
                label,
                chapter_no=int(body.get("chapter_no") or 0),
                metadata={"reason": body.get("reason", "manual")},
            )
            self._send_json({"status": "ok", "checkpoint": checkpoint})
        except ValueError as error:
            self._send_json({"error": str(error)}, 400)

    def _handle_chapter_approve(self, body):
        if not config.current_world_name():
            self._send_json({"error": "请先创建或切换世界"}, 404)
            return
        try:
            chapter = StoryLedger(config.world_dir()).approve_chapter(
                int(body.get("chapter_no") or 0),
                int(body.get("revision_no") or 0),
            )
            self._send_json({"status": "ok", "chapter": chapter})
        except (TypeError, ValueError) as error:
            self._send_json({"error": str(error)}, 400)

    def _handle_chapter_edit(self, body):
        if not config.current_world_name():
            self._send_json({"error": "请先创建或切换世界"}, 404)
            return
        try:
            chapter_no = int(body.get("chapter_no") or 0)
            content = (body.get("content") or "").strip()
            title = (body.get("title") or "").strip()
            if chapter_no < 1:
                self._send_json({"error": "无效的章节号"}, 400)
                return
            if not content:
                self._send_json({"error": "章节内容不能为空"}, 400)
                return
            ledger = StoryLedger(config.world_dir())
            new_revision = ledger.add_chapter_revision(
                chapter_no,
                content,
                title=title,
                status="reviewed",
            )
            self._send_json({"status": "ok", "revision": new_revision})
        except (TypeError, ValueError) as error:
            self._send_json({"error": str(error)}, 400)

    def _handle_chapter_review(self, body):
        if not config.current_world_name():
            self._send_json({"error": "请先创建或切换世界"}, 404)
            return
        try:
            chapter_no = int(body.get("chapter_no") or 0)
            revision_no = int(body.get("revision_no") or 0)
            if chapter_no < 1:
                self._send_json({"error": "无效的章节号"}, 400)
                return
            ledger = StoryLedger(config.world_dir())
            revisions = ledger.list_chapter_revisions()
            target = None
            for rev in revisions:
                if rev.get("chapter_no") == chapter_no and (revision_no == 0 or rev.get("revision_no") == revision_no):
                    target = rev
                    break
            if not target:
                self._send_json({"error": "未找到指定章节修订"}, 404)
                return
            content = target.get("content", "")
            if not content:
                self._send_json({"error": "章节内容为空"}, 400)
                return
            quality_report = review_prose(content)
            self._send_json({
                "chapter_no": chapter_no,
                "revision_no": target.get("revision_no"),
                "title": target.get("title", ""),
                "quality_report": quality_report,
            })
        except Exception as error:
            self._send_json({"error": str(error)}, 500)

    def _handle_foreshadows(self):
        if not config.current_world_name():
            self._send_json({"error": "请先创建或切换世界"}, 404)
            return
        try:
            ledger = StoryLedger(config.world_dir())
            context = ledger.context_for()
            open_foreshadows = context.get("open_foreshadows", [])
            resolved = ledger.list_resolved_foreshadows()
            self._send_json({
                "open": open_foreshadows,
                "resolved": resolved,
                "resolved_count": len(resolved),
            })
        except Exception as error:
            self._send_json({"error": str(error)}, 500)

    def _handle_checkpoint_save(self, body):
        if not config.current_world_name():
            self._send_json({"error": "请先创建或切换世界"}, 404)
            return
        label = (body.get("label") or "自动存档").strip()
        chapter_no = int(body.get("chapter_no") or 0)
        try:
            checkpoint = StoryLedger(config.world_dir()).create_checkpoint(
                label,
                chapter_no=chapter_no,
                metadata={"reason": body.get("reason", "manual"), "current_round": body.get("current_round", 0)},
            )
            self._send_json({"status": "ok", "checkpoint": checkpoint})
        except ValueError as error:
            self._send_json({"error": str(error)}, 400)

    def _handle_checkpoint_list(self):
        if not config.current_world_name():
            self._send_json({"error": "请先创建或切换世界"}, 404)
            return
        try:
            ledger = StoryLedger(config.world_dir())
            checkpoints = ledger.list_checkpoints()
            self._send_json({"checkpoints": checkpoints})
        except Exception as error:
            self._send_json({"error": str(error)}, 500)

    def _handle_chat_history_get(self):
        if not config.current_world_name():
            self._send_json({"error": "请先创建或切换世界"}, 404)
            return
        path = _chat_history_path()
        if not path:
            self._send_json({"events": [], "summary": "", "total_compressed": 0})
            return
        try:
            import json as _json
            try:
                with open(path, "r", encoding="utf-8") as f:
                    history = _json.load(f)
            except (FileNotFoundError, _json.JSONDecodeError):
                history = {"events": [], "summary": "", "total_compressed": 0, "updated_at": ""}
            events = [
                normalized for normalized in (
                    _normalize_history_event(event) for event in history.get("events", [])
                )
                if normalized
            ]
            self._send_json({
                "events": events,
                "summary": history.get("summary", ""),
                "total_compressed": history.get("total_compressed", 0),
                "updated_at": history.get("updated_at", ""),
            })
        except Exception as error:
            self._send_json({"error": str(error)}, 500)

    def _handle_chat_history_clear(self):
        if not config.current_world_name():
            self._send_json({"error": "请先创建或切换世界"}, 404)
            return
        path = _chat_history_path()
        if not path:
            self._send_json({"status": "ok"})
            return
        try:
            import json as _json
            history = {"events": [], "summary": "", "total_compressed": 0, "updated_at": time.time()}
            with open(path, "w", encoding="utf-8") as f:
                _json.dump(history, f, ensure_ascii=False)
            self._send_json({"status": "ok"})
        except Exception as error:
            self._send_json({"error": str(error)}, 500)

    def _handle_book_compile(self, body):
        world_name = config.current_world_name()
        if not world_name:
            self._send_json({"error": "请先创建或切换世界"}, 404)
            return
        try:
            from book_compiler import compile_book
            result = compile_book(config.world_dir(), (body.get("title") or world_name).strip())
            self._send_json({"status": "ok", "book": result})
        except ValueError as error:
            self._send_json({"error": str(error)}, 400)

    def _handle_interact_start(self, body):
        protagonist_action = (body.get("protagonist_action") or "").strip()
        if not protagonist_action:
            self._send_json({"error": "请输入玩家行动"}, 400)
            return

        api_key, base_url, model = self._get_api_config()
        if not api_key:
            self._send_json({"error": "缺少 API 密钥"}, 400)
            return

        try:
            from state import get_player_character
            player = get_player_character()
        except Exception:
            player = None
        if not player or not player.get("id"):
            self._send_json({"error": "当前世界没有可控制角色"}, 409)
            return
        try:
            world = read_json(config.STATE_DIR, "world.json")
            current_round = world.get("meta", {}).get("current_round", 0)
            ledger = StoryLedger(config.world_dir())
            active_chapter = ledger.active_chapter(round_no=current_round + 1)
            player_event = ledger.record_player_action(
                protagonist_action,
                player_id=player["id"],
                chapter_no=active_chapter["chapter_no"],
                round_no=current_round + 1,
            )
        except ValueError as error:
            self._send_json({"error": str(error)}, 400)
            return

        self._send_sse()
        q = queue.Queue()

        def callback(event: RoundEvent):
            _append_chat_event(event.event, event.data)
            q.put(event)

        def pause_check():
            return AUTO_STATE["paused"]

        def runner():
            try:
                from scheduler import run_interactive_rounds
                run_interactive_rounds(
                    protagonist_action, api_key, base_url, model,
                    event_callback=callback, pause_check=pause_check,
                )
            finally:
                q.put(None)

        t = threading.Thread(target=runner)
        t.start()

        try:
            while True:
                event = q.get(timeout=600)
                if event is None:
                    self._write_sse_event("close", "{}")
                    break
                try:
                    self._write_sse_event(event.event, json.dumps(event.data, ensure_ascii=False))
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
        except queue.Empty:
            pass
        finally:
            t.join(timeout=5)

    def _write_sse_event(self, event_type, data):
        msg = f"event: {event_type}\ndata: {data}\n\n"
        try:
            self.wfile.write(msg.encode("utf-8"))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            raise


def _parse_document_to_world(text: str, filename: str, api_key: str, base_url: str, model: str) -> dict:
    from agents.base import call_deepseek

    system_prompt = """你是一个世界设定解析专家。你的任务是从用户提供的文档（小说、设定集、世界观说明等）中提取结构化的世界信息。

你需要像一个专业的"设定考古学家"一样工作——从文本中挖掘出隐藏的世界观骨架，而不是编造文档中没有的内容。

## 提取规则

1. **只提取文档中明确存在或强烈暗示的信息**——文档没提到的，留空或设为默认值，绝对不编造
2. **人名、地名、势力名保持原样**——不要翻译或改写文档中的专有名词
3. **如果文档中信息不足**——用合理的默认值填充，并在 description 中注明"（文档未提及，使用默认值）"
4. **角色提取优先级**——主角 > 重要配角 > 提及的路人。至少提取3个有足够描写的角色作为 playable_characters
5. **世界类型自动推断**——从文档内容判断是东方玄幻、西方奇幻、科幻末世还是现代都市
6. **缺失信息的处理**——如果文档完全没有提到某个必需字段，用以下默认值：
   - time: {"year": 1, "month": 1, "day": 1, "era": "元年", "dynasty": ""}
   - realm for characters: 从文档推断，无法推断则填"凡人"
   - 如果只有一个地区，自动创建一个起始地区

## 特别注意

- **playable_characters 必须提供 3-5 个**——如果文档中主要角色不足3个，可以适当放宽标准，把有名字的角色都列进去
- **至少有一个 playable_character 的 has_system 为 true**——如果文档中有"系统"、"金手指"、"穿越者"等元素，优先标记该角色
- **每个角色需要推断 daily_routine**——如果文档没写，根据角色身份合理推断（守备队长→巡视训练、酒馆老板→开店待客）
- **势力关系必须从文档中提取**——文档没写势力关系的，也不要编造，留空 relationships 数组

## 输出格式

必须输出与 V2 世界创建助手完全相同的 world_package JSON 格式，包含：
- world_state（时间、地理、势力、世界事件）
- playable_characters（3-5个可选角色，含完整角色卡）
- npcs（至少3个NPC，含欲望、秘密、叙事钩子）
- world_summary（给用户看的世界摘要，markdown格式）

输出必须是严格的 JSON，不要用 markdown 代码块包裹。"""

    user_prompt = json.dumps({
        "instruction": f"请从以下文档中提取结构化的世界信息。文档来源：「{filename}」。提取完成后输出完整的 world_package JSON。",
        "document_text": text,
        "output_requirements": {
            "format": "与 V2 世界创建助手相同的 world_package 格式",
            "playable_characters": "至少3个，每个包含完整角色卡（name, age, appearance, personality, backstory, core_motivation, realm, specialties, has_system, daily_routine）",
            "npcs": "至少3个，每个包含 desires, fears, secrets, narrative_hooks",
            "regions": "至少2个地区，每个包含 landmarks",
            "factions": "至少2个势力",
            "world_summary": "markdown格式的世界摘要，包含关键设定和信息来源标注",
        }
    }, ensure_ascii=False)

    try:
        output = call_deepseek(
            system_prompt, user_prompt,
            api_key=api_key, base_url=base_url, model=model,
            max_tokens=8192, temperature=0.5,
        )
        if isinstance(output, dict):
            return output.get("world_package", output)
        return None
    except Exception:
        return None


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), AppHandler)
    print(f"World Project API server running on http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
