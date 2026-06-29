import json
import tempfile
import unittest
from pathlib import Path

import config
from server import _append_chat_event
from story_context import build_agent_context
from story_ledger import StoryLedger


class StoryContextTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_worlds_dir = config.WORLDS_DIR
        config.WORLDS_DIR = str(Path(self.temp_dir.name) / "worlds")
        world_dir = Path(config.WORLDS_DIR) / "context"
        world_dir.mkdir(parents=True, exist_ok=True)
        config.switch_world("context")
        config.current_world_name()
        self.world_dir = Path(config.world_dir())

    def tearDown(self):
        config.WORLDS_DIR = self.old_worlds_dir
        self.temp_dir.cleanup()

    def test_chat_event_append_adds_projection_fields(self):
        _append_chat_event("npc-message", {
            "npc_name": "顾南",
            "dialogue": "山门外有人。",
            "round": 3,
        })

        history = json.loads((self.world_dir / "chat_history.json").read_text(encoding="utf-8"))
        event = history["events"][0]
        self.assertEqual(event["type"], "npc-message")
        self.assertEqual(event["round"], 3)
        self.assertEqual(event["actor"], "顾南")
        self.assertEqual(event["source"], "npc-agents")
        self.assertIn("山门外有人", event["text"])

    def test_long_context_keeps_summary_recent_events_and_foreshadows(self):
        history = {
            "summary": "第1-40轮概要：玩家发现染血令牌，并决定隐瞒真相。",
            "events": [
                {"type": "player-action-recorded", "data": {"action": f"行动{i}", "round": i}, "ts": i}
                for i in range(60)
            ],
            "total_compressed": 40,
            "updated_at": 60,
        }
        (self.world_dir / "chat_history.json").write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")

        ledger = StoryLedger(self.world_dir)
        ledger.bootstrap("context", {"id": "p1", "name": "林越"})
        ledger.add_foreshadow("染血令牌", "背面有被磨掉的宗门徽记。", planted_chapter=1, target_chapter_to=5)
        ledger.upsert_fact(subject_id="p1", predicate="identity", object_value="外门弟子", visibility="player")

        packet = build_agent_context("chronicler", event_limit=8)

        self.assertIn("染血令牌", packet["chat_summary"])
        self.assertLessEqual(len(packet["recent_chat_events"]), 8)
        self.assertEqual(packet["story_ledger"]["open_foreshadows"][0]["title"], "染血令牌")
        self.assertTrue(any(fact.get("object_value") == "外门弟子" for fact in packet["story_ledger"]["facts"]))


if __name__ == "__main__":
    unittest.main()
