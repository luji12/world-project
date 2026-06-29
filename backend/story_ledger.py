"""Durable, queryable story state for long-running interactive novels.

The existing JSON files remain the runtime projection used by the first version of
the simulator.  This module is the append-only source of narrative evidence: a
player action, a confirmed fact, or a planted foreshadow is never silently
overwritten by an agent response.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


LEDGER_FILENAME = "story-ledger.sqlite3"
_schema_lock = threading.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def _decode(value: str | None) -> dict[str, Any]:
    try:
        return json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}


class StoryLedger:
    """Small SQLite ledger with explicit provenance and checkpoint support."""

    def __init__(self, world_dir: str | os.PathLike[str]):
        self.world_dir = Path(world_dir)
        self.path = self.world_dir / LEDGER_FILENAME
        self.world_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with _schema_lock, self._connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;

                CREATE TABLE IF NOT EXISTS ledger_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS story_events (
                    id TEXT NOT NULL UNIQUE,
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor_id TEXT,
                    chapter_no INTEGER NOT NULL DEFAULT 0,
                    round_no INTEGER NOT NULL DEFAULT 0,
                    origin TEXT NOT NULL,
                    visibility TEXT NOT NULL DEFAULT 'world',
                    payload TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_story_events_actor
                    ON story_events(actor_id, sequence DESC);
                CREATE INDEX IF NOT EXISTS idx_story_events_chapter
                    ON story_events(chapter_no, sequence DESC);

                CREATE TABLE IF NOT EXISTS canon_facts (
                    id TEXT PRIMARY KEY,
                    subject_id TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object_value TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    source_event_id TEXT,
                    valid_from_chapter INTEGER NOT NULL DEFAULT 0,
                    valid_to_chapter INTEGER,
                    visibility TEXT NOT NULL DEFAULT 'world',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_canon_facts_subject
                    ON canon_facts(subject_id, predicate, status);

                CREATE TABLE IF NOT EXISTS foreshadows (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    planted_chapter INTEGER NOT NULL DEFAULT 0,
                    target_chapter_from INTEGER,
                    target_chapter_to INTEGER,
                    importance TEXT NOT NULL DEFAULT 'moderate',
                    status TEXT NOT NULL DEFAULT 'open',
                    planted_event_id TEXT,
                    payoff_event_id TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_foreshadows_status
                    ON foreshadows(status, target_chapter_to);

                CREATE TABLE IF NOT EXISTS chapter_revisions (
                    id TEXT PRIMARY KEY,
                    chapter_no INTEGER NOT NULL,
                    revision_no INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',
                    title TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    scene_blueprint TEXT NOT NULL DEFAULT '{}',
                    quality_report TEXT NOT NULL DEFAULT '{}',
                    word_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    UNIQUE(chapter_no, revision_no)
                );

                CREATE TABLE IF NOT EXISTS chapter_sessions (
                    chapter_no INTEGER PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'open',
                    title TEXT NOT NULL DEFAULT '',
                    word_count INTEGER NOT NULL DEFAULT 0,
                    started_round INTEGER NOT NULL DEFAULT 0,
                    closed_round INTEGER,
                    blueprint TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chapter_scenes (
                    id TEXT PRIMARY KEY,
                    chapter_no INTEGER NOT NULL,
                    scene_no INTEGER NOT NULL,
                    round_no INTEGER NOT NULL DEFAULT 0,
                    content TEXT NOT NULL,
                    char_count INTEGER NOT NULL DEFAULT 0,
                    timeline_update TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '{}',
                    quality_report TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    UNIQUE(chapter_no, scene_no),
                    FOREIGN KEY(chapter_no) REFERENCES chapter_sessions(chapter_no)
                );

                CREATE INDEX IF NOT EXISTS idx_chapter_scenes_chapter
                    ON chapter_scenes(chapter_no, scene_no ASC);

                CREATE TABLE IF NOT EXISTS checkpoints (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    chapter_no INTEGER NOT NULL DEFAULT 0,
                    event_sequence INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );
                """
            )
            # Migrations for existing databases
            existing_cols = {row["name"] for row in connection.execute("PRAGMA table_info(chapter_sessions)")}
            if "title" not in existing_cols:
                connection.execute("ALTER TABLE chapter_sessions ADD COLUMN title TEXT NOT NULL DEFAULT ''")
            if "word_count" not in existing_cols:
                connection.execute("ALTER TABLE chapter_sessions ADD COLUMN word_count INTEGER NOT NULL DEFAULT 0")
            existing_cols_rev = {row["name"] for row in connection.execute("PRAGMA table_info(chapter_revisions)")}
            if "title" not in existing_cols_rev:
                connection.execute("ALTER TABLE chapter_revisions ADD COLUMN title TEXT NOT NULL DEFAULT ''")
            if "word_count" not in existing_cols_rev:
                connection.execute("ALTER TABLE chapter_revisions ADD COLUMN word_count INTEGER NOT NULL DEFAULT 0")
            existing_cols_scene = {row["name"] for row in connection.execute("PRAGMA table_info(chapter_scenes)")}
            if "char_count" not in existing_cols_scene:
                connection.execute("ALTER TABLE chapter_scenes ADD COLUMN char_count INTEGER NOT NULL DEFAULT 0")

    def bootstrap(self, world_name: str, player: dict[str, Any] | None = None) -> None:
        with self._connection() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO ledger_meta(key, value) VALUES (?, ?)",
                ("schema_version", "2"),
            )
            connection.execute(
                "INSERT OR IGNORE INTO ledger_meta(key, value) VALUES (?, ?)",
                ("world_name", world_name),
            )
            if player and player.get("id"):
                connection.execute(
                    "INSERT OR REPLACE INTO ledger_meta(key, value) VALUES (?, ?)",
                    ("player_character_id", player["id"]),
                )
                self._upsert_fact_in_connection(
                    connection,
                    subject_id=player["id"],
                    predicate="player_controlled",
                    object_value="true",
                    visibility="player",
                    metadata={"name": player.get("name", "")},
                )

    def append_event(
        self,
        event_type: str,
        *,
        actor_id: str | None = None,
        payload: dict[str, Any] | None = None,
        chapter_no: int = 0,
        round_no: int = 0,
        origin: str = "system",
        visibility: str = "world",
    ) -> dict[str, Any]:
        if not event_type.strip():
            raise ValueError("event_type 不能为空")
        if visibility not in {"world", "player", "private"}:
            raise ValueError("visibility 无效")
        event_id = str(uuid.uuid4())
        created_at = utc_now()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO story_events(
                    id, created_at, event_type, actor_id, chapter_no, round_no,
                    origin, visibility, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    created_at,
                    event_type,
                    actor_id,
                    chapter_no,
                    round_no,
                    origin,
                    visibility,
                    _json(payload),
                ),
            )
            sequence = cursor.lastrowid
        return {
            "id": event_id,
            "sequence": sequence,
            "created_at": created_at,
            "event_type": event_type,
            "actor_id": actor_id,
            "chapter_no": chapter_no,
            "round_no": round_no,
            "origin": origin,
            "visibility": visibility,
            "payload": payload or {},
        }

    def record_player_action(
        self,
        action: str,
        *,
        player_id: str,
        chapter_no: int = 0,
        round_no: int = 0,
        known_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        action = action.strip()
        if not action:
            raise ValueError("玩家行动不能为空")
        if not player_id:
            raise ValueError("当前世界没有可控制角色")
        return self.append_event(
            "player_action",
            actor_id=player_id,
            chapter_no=chapter_no,
            round_no=round_no,
            origin="player",
            visibility="player",
            payload={"action": action, "known_context": known_context or {}},
        )

    def _upsert_fact_in_connection(
        self,
        connection: sqlite3.Connection,
        *,
        subject_id: str,
        predicate: str,
        object_value: str,
        source_event_id: str | None = None,
        valid_from_chapter: int = 0,
        visibility: str = "world",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        existing = connection.execute(
            """
            SELECT id FROM canon_facts
            WHERE subject_id = ? AND predicate = ? AND status = 'active'
            ORDER BY updated_at DESC LIMIT 1
            """,
            (subject_id, predicate),
        ).fetchone()
        if existing:
            fact_id = existing["id"]
            connection.execute(
                """
                UPDATE canon_facts SET object_value = ?, source_event_id = ?,
                    valid_from_chapter = ?, visibility = ?, metadata = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    object_value,
                    source_event_id,
                    valid_from_chapter,
                    visibility,
                    _json(metadata),
                    now,
                    fact_id,
                ),
            )
        else:
            fact_id = str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO canon_facts(
                    id, subject_id, predicate, object_value, source_event_id,
                    valid_from_chapter, visibility, metadata, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fact_id,
                    subject_id,
                    predicate,
                    object_value,
                    source_event_id,
                    valid_from_chapter,
                    visibility,
                    _json(metadata),
                    now,
                    now,
                ),
            )
        return {"id": fact_id, "subject_id": subject_id, "predicate": predicate, "object_value": object_value}

    def upsert_fact(self, **kwargs: Any) -> dict[str, Any]:
        required = ("subject_id", "predicate", "object_value")
        missing = [field for field in required if not kwargs.get(field)]
        if missing:
            raise ValueError(f"事实缺少字段: {', '.join(missing)}")
        with self._connection() as connection:
            return self._upsert_fact_in_connection(connection, **kwargs)

    def add_foreshadow(
        self,
        title: str,
        detail: str,
        *,
        planted_chapter: int = 0,
        target_chapter_from: int | None = None,
        target_chapter_to: int | None = None,
        importance: str = "moderate",
        planted_event_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not title.strip() or not detail.strip():
            raise ValueError("伏笔需要标题和说明")
        foreshadow_id = str(uuid.uuid4())
        now = utc_now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO foreshadows(
                    id, title, detail, planted_chapter, target_chapter_from,
                    target_chapter_to, importance, planted_event_id, metadata,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    foreshadow_id,
                    title.strip(),
                    detail.strip(),
                    planted_chapter,
                    target_chapter_from,
                    target_chapter_to,
                    importance,
                    planted_event_id,
                    _json(metadata),
                    now,
                    now,
                ),
            )
        return {"id": foreshadow_id, "title": title.strip(), "detail": detail.strip(), "status": "open"}

    def resolve_foreshadow(self, foreshadow_id: str, payoff_event_id: str | None = None) -> None:
        with self._connection() as connection:
            updated = connection.execute(
                """
                UPDATE foreshadows SET status = 'resolved', payoff_event_id = ?, updated_at = ?
                WHERE id = ? AND status = 'open'
                """,
                (payoff_event_id, utc_now(), foreshadow_id),
            ).rowcount
        if not updated:
            raise ValueError("未找到可回收的伏笔")

    def create_checkpoint(self, label: str, *, chapter_no: int = 0, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        label = label.strip()
        if not label:
            raise ValueError("检查点需要名称")
        with self._connection() as connection:
            row = connection.execute("SELECT COALESCE(MAX(sequence), 0) AS sequence FROM story_events").fetchone()
            checkpoint_id = str(uuid.uuid4())
            created_at = utc_now()
            connection.execute(
                """
                INSERT INTO checkpoints(id, label, chapter_no, event_sequence, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (checkpoint_id, label, chapter_no, row["sequence"], created_at, _json(metadata)),
            )
        return {"id": checkpoint_id, "label": label, "chapter_no": chapter_no, "event_sequence": row["sequence"]}

    def add_chapter_revision(
        self,
        chapter_no: int,
        content: str,
        *,
        title: str = "",
        scene_blueprint: dict[str, Any] | None = None,
        quality_report: dict[str, Any] | None = None,
        status: str = "draft",
    ) -> dict[str, Any]:
        if chapter_no < 1:
            raise ValueError("章节号必须大于 0")
        if not content.strip():
            raise ValueError("章节正文不能为空")
        if status not in {"draft", "reviewed", "approved", "rejected"}:
            raise ValueError("章节状态无效")
        word_count = len(content)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(revision_no), 0) AS revision_no FROM chapter_revisions WHERE chapter_no = ?",
                (chapter_no,),
            ).fetchone()
            revision_no = row["revision_no"] + 1
            revision_id = str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO chapter_revisions(
                    id, chapter_no, revision_no, status, title, content, scene_blueprint,
                    quality_report, word_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    chapter_no,
                    revision_no,
                    status,
                    title,
                    content.strip(),
                    _json(scene_blueprint),
                    _json(quality_report),
                    word_count,
                    utc_now(),
                ),
            )
        return {
            "id": revision_id,
            "chapter_no": chapter_no,
            "revision_no": revision_no,
            "status": status,
            "title": title,
            "word_count": word_count,
        }

    def active_chapter(self, *, round_no: int = 0) -> dict[str, Any]:
        """Return the chapter currently collecting scenes, creating it if needed."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM chapter_sessions WHERE status = 'open' ORDER BY chapter_no DESC LIMIT 1"
            ).fetchone()
            if row is None:
                row = connection.execute(
                    "SELECT COALESCE(MAX(chapter_no), 0) AS chapter_no FROM chapter_sessions"
                ).fetchone()
                revision_row = connection.execute(
                    "SELECT COALESCE(MAX(chapter_no), 0) AS chapter_no FROM chapter_revisions"
                ).fetchone()
                chapter_no = max(row["chapter_no"], revision_row["chapter_no"]) + 1
                now = utc_now()
                connection.execute(
                    """
                    INSERT OR IGNORE INTO chapter_sessions(chapter_no, started_round, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (chapter_no, round_no, now, now),
                )
                row = connection.execute(
                    "SELECT * FROM chapter_sessions WHERE chapter_no = ?", (chapter_no,)
                ).fetchone()
        return self._row_to_session(row)

    def list_resolved_foreshadows(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Return resolved foreshadows, most recently updated first."""
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM foreshadows WHERE status = 'resolved' ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item.get("metadata", "{}"))
            result.append(item)
        return result

    def list_checkpoints(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Return checkpoints, most recently created first."""
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM checkpoints ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item.get("metadata", "{}"))
            result.append(item)
        return result

    def append_scene(
        self,
        content: str,
        *,
        round_no: int = 0,
        timeline_update: str = "",
        summary: dict[str, Any] | None = None,
        quality_report: dict[str, Any] | None = None,
        close_chapter: bool = False,
        chapter_title: str = "",
        min_word_count: int = 6000,
        max_word_count: int = 10000,
        max_scenes: int | None = None,
    ) -> dict[str, Any]:
        """Append a scene and optionally seal its chapter into a revision.

        Chapters auto-close when word count reaches 6000-10000 range,
        or when the model explicitly requests a new chapter.
        """
        content = content.strip()
        if not content:
            raise ValueError("场景正文不能为空")

        session = self.active_chapter(round_no=round_no)
        chapter_no = session["chapter_no"]
        char_count = len(content)
        now = utc_now()
        with self._connection() as connection:
            scene_row = connection.execute(
                "SELECT COALESCE(MAX(scene_no), 0) AS scene_no FROM chapter_scenes WHERE chapter_no = ?",
                (chapter_no,),
            ).fetchone()
            scene_no = scene_row["scene_no"] + 1
            scene_id = str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO chapter_scenes(
                    id, chapter_no, scene_no, round_no, content, char_count, timeline_update,
                    summary, quality_report, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scene_id,
                    chapter_no,
                    scene_no,
                    round_no,
                    content,
                    char_count,
                    timeline_update.strip(),
                    _json(summary),
                    _json(quality_report),
                    now,
                ),
            )
            if chapter_title:
                connection.execute(
                    "UPDATE chapter_sessions SET title = ?, word_count = word_count + ?, updated_at = ? WHERE chapter_no = ?",
                    (chapter_title, char_count, now, chapter_no),
                )
            else:
                connection.execute(
                    "UPDATE chapter_sessions SET word_count = word_count + ?, updated_at = ? WHERE chapter_no = ?",
                    (char_count, now, chapter_no),
                )
            current_word_count = connection.execute(
                "SELECT word_count FROM chapter_sessions WHERE chapter_no = ?",
                (chapter_no,),
            ).fetchone()["word_count"]

        scene = {
            "id": scene_id,
            "chapter_no": chapter_no,
            "scene_no": scene_no,
            "round_no": round_no,
            "char_count": char_count,
        }
        # Close chapter if:
        # 1. Explicitly requested by LLM (close_chapter=True) with at least some content, OR
        # 2. Word count reached max threshold (10000 chars)
        explicit_close = close_chapter and char_count > 100
        auto_close = current_word_count >= max_word_count and current_word_count >= min_word_count
        scene_limit_close = bool(max_scenes and scene_no >= max_scenes)
        should_close = explicit_close or auto_close or scene_limit_close
        if should_close:
            draft = self.close_active_chapter(
                round_no=round_no,
                title=chapter_title or (summary or {}).get("title", ""),
                blueprint={"chapter_summary": summary or {}, "scene_count": scene_no},
            )
            scene["chapter_closed"] = True
            scene["draft"] = draft
        else:
            scene["chapter_closed"] = False
        return scene

    def close_active_chapter(
        self,
        *,
        round_no: int = 0,
        title: str = "",
        blueprint: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Seal the active chapter and create one reviewable manuscript draft."""
        session = self.active_chapter(round_no=round_no)
        chapter_no = session["chapter_no"]
        with self._connection() as connection:
            scenes = connection.execute(
                "SELECT * FROM chapter_scenes WHERE chapter_no = ? ORDER BY scene_no ASC",
                (chapter_no,),
            ).fetchall()
            if not scenes:
                raise ValueError("当前章节还没有可封口的场景")
            if session["status"] != "open":
                raise ValueError("当前章节已封口")
            content = "\n\n".join(row["content"] for row in scenes)
            word_count = len(content)
            summaries = [_decode(row["summary"]) for row in scenes]
            scene_reports = [_decode(row["quality_report"]) for row in scenes]
            final_blueprint = {
                **(blueprint or {}),
                "scene_summaries": summaries,
                "rounds": [row["round_no"] for row in scenes],
            }
            chapter_title = title or session.get("title") or ""
            if not chapter_title:
                key_events = []
                for s in summaries:
                    key_events.extend(s.get("key_events", []))
                if key_events:
                    chapter_title = key_events[0][:20]
                else:
                    chapter_title = f"第{chapter_no}章"
            connection.execute(
                """
                UPDATE chapter_sessions
                SET status = 'closed', closed_round = ?, title = ?, word_count = ?, blueprint = ?, updated_at = ?
                WHERE chapter_no = ?
                """,
                (round_no, chapter_title, word_count, _json(final_blueprint), utc_now(), chapter_no),
            )

        # Imported lazily to keep the durable storage layer dependency-light.
        from prose_quality import review_prose
        quality_report = review_prose(content)
        quality_report["scene_reports"] = scene_reports
        draft = self.add_chapter_revision(
            chapter_no,
            content,
            title=chapter_title,
            status="reviewed" if quality_report["score"] >= 76 else "draft",
            scene_blueprint=final_blueprint,
            quality_report=quality_report,
        )
        self.append_event(
            "chapter_drafted",
            chapter_no=chapter_no,
            round_no=round_no,
            origin="chronicler",
            payload={"revision_id": draft["id"], "quality_score": quality_report["score"], "scene_count": len(scenes), "word_count": word_count, "title": chapter_title},
        )
        return {**draft, "quality_report": quality_report, "scene_count": len(scenes)}

    def approve_chapter(self, chapter_no: int, revision_no: int) -> dict[str, Any]:
        with self._connection() as connection:
            target = connection.execute(
                "SELECT id FROM chapter_revisions WHERE chapter_no = ? AND revision_no = ?",
                (chapter_no, revision_no),
            ).fetchone()
            if not target:
                raise ValueError("未找到章节修订")
            connection.execute(
                "UPDATE chapter_revisions SET status = 'reviewed' WHERE chapter_no = ? AND status = 'approved'",
                (chapter_no,),
            )
            connection.execute("UPDATE chapter_revisions SET status = 'approved' WHERE id = ?", (target["id"],))
            row = connection.execute("SELECT * FROM chapter_revisions WHERE id = ?", (target["id"],)).fetchone()
        return self._row_to_chapter(row)

    def approved_chapters(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM chapter_revisions WHERE status = 'approved' ORDER BY chapter_no ASC"
            ).fetchall()
        return [self._row_to_chapter(row) for row in rows]

    def list_chapter_revisions(self, status: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM chapter_revisions"
        params: tuple[Any, ...] = ()
        if status:
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY chapter_no ASC, revision_no DESC"
        with self._connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._row_to_chapter(row) for row in rows]

    def context_for(
        self,
        *,
        player_id: str | None = None,
        chapter_no: int = 0,
        event_limit: int = 12,
    ) -> dict[str, Any]:
        with self._connection() as connection:
            event_rows = connection.execute(
                """
                SELECT * FROM story_events
                WHERE visibility != 'private' OR actor_id = ?
                ORDER BY sequence DESC LIMIT ?
                """,
                (player_id or "", event_limit),
            ).fetchall()
            facts = connection.execute(
                """
                SELECT * FROM canon_facts
                WHERE status = 'active' AND (visibility != 'private' OR subject_id = ?)
                ORDER BY updated_at DESC LIMIT 30
                """,
                (player_id or "",),
            ).fetchall()
            open_foreshadows = connection.execute(
                """
                SELECT * FROM foreshadows
                WHERE status = 'open'
                ORDER BY CASE WHEN target_chapter_to IS NULL THEN 1 ELSE 0 END,
                         target_chapter_to ASC, planted_chapter ASC
                LIMIT 20
                """
            ).fetchall()

        return {
            "recent_events": [self._row_to_event(row) for row in reversed(event_rows)],
            "facts": [self._row_to_fact(row) for row in facts],
            "open_foreshadows": [self._row_to_foreshadow(row, chapter_no) for row in open_foreshadows],
        }

    def list_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM story_events ORDER BY sequence DESC LIMIT ?", (limit,)).fetchall()
        return [self._row_to_event(row) for row in reversed(rows)]

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["payload"] = _decode(item.pop("payload", "{}"))
        return item

    @staticmethod
    def _row_to_fact(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["metadata"] = _decode(item.pop("metadata", "{}"))
        return item

    @staticmethod
    def _row_to_foreshadow(row: sqlite3.Row, chapter_no: int) -> dict[str, Any]:
        item = dict(row)
        item["metadata"] = _decode(item.pop("metadata", "{}"))
        deadline = item.get("target_chapter_to")
        item["overdue"] = bool(deadline is not None and chapter_no > deadline)
        return item

    @staticmethod
    def _row_to_chapter(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["scene_blueprint"] = _decode(item.pop("scene_blueprint", "{}"))
        item["quality_report"] = _decode(item.pop("quality_report", "{}"))
        return item

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["blueprint"] = _decode(item.pop("blueprint", "{}"))
        return item


def ledger_for_world(world_dir: str | os.PathLike[str]) -> StoryLedger:
    return StoryLedger(world_dir)
