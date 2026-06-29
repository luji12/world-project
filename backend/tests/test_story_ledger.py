import tempfile
import unittest
from pathlib import Path

from story_ledger import StoryLedger


class StoryLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.world_dir = Path(self.temp_dir.name) / "world"
        self.ledger = StoryLedger(self.world_dir)
        self.ledger.bootstrap("测试世界", {"id": "player-1", "name": "林越"})

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_player_action_is_append_only_evidence(self):
        event = self.ledger.record_player_action(
            "去城门打听失踪商队的消息",
            player_id="player-1",
            chapter_no=2,
            round_no=4,
        )

        self.assertEqual(event["event_type"], "player_action")
        self.assertEqual(event["origin"], "player")
        self.assertEqual(event["visibility"], "player")
        self.assertEqual(self.ledger.list_events()[0]["payload"]["action"], "去城门打听失踪商队的消息")

    def test_context_keeps_facts_and_open_foreshadows(self):
        event = self.ledger.record_player_action("留下暗号", player_id="player-1", chapter_no=3)
        self.ledger.upsert_fact(
            subject_id="npc-1",
            predicate="location",
            object_value="落云城北门",
            source_event_id=event["id"],
            valid_from_chapter=3,
        )
        planted = self.ledger.add_foreshadow(
            "染血令牌",
            "令牌背面刻着被磨掉一半的宗门徽记。",
            planted_chapter=3,
            target_chapter_to=5,
            planted_event_id=event["id"],
        )

        context = self.ledger.context_for(player_id="player-1", chapter_no=6)

        location_fact = next(fact for fact in context["facts"] if fact["subject_id"] == "npc-1")
        self.assertEqual(location_fact["object_value"], "落云城北门")
        self.assertEqual(context["open_foreshadows"][0]["id"], planted["id"])
        self.assertTrue(context["open_foreshadows"][0]["overdue"])

    def test_checkpoint_records_last_event_sequence(self):
        self.ledger.record_player_action("先观察四周", player_id="player-1")
        checkpoint = self.ledger.create_checkpoint("进入落云城前")
        self.assertEqual(checkpoint["event_sequence"], 1)

    def test_only_one_revision_can_be_approved_per_chapter(self):
        first = self.ledger.add_chapter_revision(1, "第一版正文。" * 100)
        second = self.ledger.add_chapter_revision(1, "第二版正文。" * 100)

        approved = self.ledger.approve_chapter(1, second["revision_no"])

        self.assertEqual(approved["status"], "approved")
        self.assertEqual(self.ledger.approved_chapters()[0]["id"], second["id"])
        self.assertNotEqual(first["id"], second["id"])

    def test_scenes_accumulate_before_a_chapter_revision_is_created(self):
        first = self.ledger.append_scene("第一幕正文。" * 120, round_no=1, max_scenes=3)
        second = self.ledger.append_scene("第二幕正文。" * 120, round_no=2, max_scenes=3)
        third = self.ledger.append_scene("第三幕正文。" * 120, round_no=3, max_scenes=3)

        self.assertEqual(first["chapter_no"], 1)
        self.assertFalse(first["chapter_closed"])
        self.assertFalse(second["chapter_closed"])
        self.assertTrue(third["chapter_closed"])
        self.assertEqual(third["draft"]["chapter_no"], 1)
        revisions = self.ledger.list_chapter_revisions()
        self.assertEqual(len(revisions), 1)
        self.assertIn("第一幕正文", revisions[0]["content"])
        self.assertIn("第三幕正文", revisions[0]["content"])

    def test_chapter_boundary_starts_a_new_session(self):
        sealed = self.ledger.append_scene("本章唯一场景。" * 120, round_no=1, close_chapter=True)
        next_scene = self.ledger.append_scene("下一章开场。" * 120, round_no=2)

        self.assertTrue(sealed["chapter_closed"])
        self.assertEqual(next_scene["chapter_no"], 2)


if __name__ == "__main__":
    unittest.main()
