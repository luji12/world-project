import os
import shutil
import tempfile
import unittest
from pathlib import Path

import config
from canon_context import build_canon_packet
from canon_engine import canonicalize_world_package, canon_exists, compile_canon_from_world_package, load_canon, write_canon_files
from canon_migration import reset_world_from_canon
from canon_validator import validate_agent_output, validate_player_action
from state import write_json
from story_context import build_agent_context


class CanonEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_worlds_dir = config.WORLDS_DIR
        config.WORLDS_DIR = str(Path(self.temp_dir.name) / "worlds")
        os.makedirs(config.WORLDS_DIR, exist_ok=True)
        self.world = "测试世界"
        self.world_path = Path(config.WORLDS_DIR) / self.world
        self.world_path.mkdir(parents=True, exist_ok=True)
        config.switch_world(self.world)

    def tearDown(self):
        config.WORLDS_DIR = self.old_worlds_dir
        self.temp_dir.cleanup()

    def _package(self):
        return {
            "name": self.world,
            "world_type": "xuanhuan",
            "world_summary": "主线第一阶段：青石镇入世。第二阶段：进入云岚宗。",
            "world_state": {
                "world_name": "苍玄界",
                "time": {"year": 1, "month": 1, "day": 1, "hour": 8},
                "geography": {"current_region": "", "regions": {}},
                "factions": [{"id": "yunlan", "name": "云岚宗"}],
                "global_events": [{"name": "青石镇异动"}],
            },
            "playable_characters": [{"id": "ye-ran", "name": "叶然", "region": "青石镇"}],
            "npcs": [{"id": "old-li", "name": "李伯", "role": "药铺掌柜", "region": "青石镇"}],
        }

    def test_compile_preserves_source_and_initializes_starting_region(self):
        source = "开局地点：青石镇。主线第一阶段：青石镇入世。修炼体系：凡骨、淬体、开脉。"
        compiled = compile_canon_from_world_package(self._package(), source, "source.md")
        write_canon_files(str(self.world_path), compiled)
        canon = load_canon(str(self.world_path))
        self.assertIn("青石镇", canon["source_text"])
        self.assertTrue(canon_exists(str(self.world_path)))
        package = canonicalize_world_package(self._package(), compiled)
        geography = package["world_state"]["geography"]
        self.assertTrue(geography["current_region"])
        self.assertNotEqual(geography["current_region"], "main")

    def test_player_gate_blocks_late_story_jump(self):
        source = "开局地点：青石镇。主线第一阶段：青石镇入世。"
        write_canon_files(str(self.world_path), compile_canon_from_world_package(self._package(), source, "source.md"))
        packet = build_canon_packet("test")
        result = validate_player_action("我直接飞升并统一天下", packet)
        self.assertFalse(result["allowed"])
        self.assertIn("阶段", result["reason"])

    def test_agent_output_repairs_canon_external_location(self):
        source = "开局地点：青石镇。主线第一阶段：青石镇入世。"
        write_canon_files(str(self.world_path), compile_canon_from_world_package(self._package(), source, "source.md"))
        packet = build_canon_packet("world-engine")
        repaired, report = validate_agent_output("world-engine", {"scene_description": "黑风村的晨雾散开。"}, packet, world_path=str(self.world_path))
        self.assertIn("青石镇", repaired["scene_description"])
        self.assertTrue(report["conflicts"])
        self.assertTrue(load_canon(str(self.world_path))["conflicts"]["items"])

    def test_reset_world_backs_up_and_clears_runtime(self):
        for sub in ["state", "memory", "chronicle", "npc-cards"]:
            (self.world_path / sub).mkdir(exist_ok=True)
        write_json(str(self.world_path / "state"), "world.json", {"meta": {"current_round": 9}, "geography": {"current_region": "old", "regions": {}}})
        (self.world_path / "chat_history.json").write_text('{"events":[{"type":"narration"}]}', encoding="utf-8")
        report = reset_world_from_canon(self.world, source_text="开局地点：青石镇。主线第一阶段：青石镇入世。", source_name="test")
        self.assertTrue(Path(report["backup_path"]).exists())
        self.assertFalse((self.world_path / "chat_history.json").exists())
        world = load_canon(str(self.world_path))
        self.assertIn("青石镇", world["source_text"])

    def test_story_context_prioritizes_canon_packet(self):
        source = "开局地点：青石镇。主线第一阶段：青石镇入世。"
        compiled = compile_canon_from_world_package(self._package(), source, "source.md")
        write_canon_files(str(self.world_path), compiled)
        package = canonicalize_world_package(self._package(), compiled)
        (self.world_path / "state").mkdir(exist_ok=True)
        (self.world_path / "memory").mkdir(exist_ok=True)
        write_json(str(self.world_path / "state"), "world.json", {"meta": {"current_round": 0}, **package["world_state"]})
        write_json(str(self.world_path / "state"), "protagonist.json", {"id": "ye-ran", "name": "叶然", "action_log": []})
        write_json(str(self.world_path / "memory"), "index.json", {})
        ctx = build_agent_context("world-engine")
        self.assertEqual(ctx["priority_order"][0], "canon_packet.hard_facts")
        self.assertTrue(ctx["canon_packet"]["exists"])


if __name__ == "__main__":
    unittest.main()
