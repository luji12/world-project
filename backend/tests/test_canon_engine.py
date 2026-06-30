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
from outline_engine import advance_beat_if_satisfied, build_round_contract, load_beat_ledger, load_story_outline
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
        self.assertTrue((self.world_path / "canon" / "migration_report.json").exists())
        self.assertFalse((self.world_path / "chat_history.json").exists())
        world = load_canon(str(self.world_path))
        self.assertIn("青石镇", world["source_text"])

    def test_reset_world_without_source_fails_before_backup(self):
        with self.assertRaises(ValueError):
            reset_world_from_canon(self.world)
        archives = Path(config.WORLDS_DIR) / "_archives"
        self.assertFalse(archives.exists())

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
        self.assertIn("canon_packet.round_contract", ctx["priority_order"])
        self.assertTrue(ctx["canon_packet"]["exists"])

    def test_detailed_outline_compiles_to_executable_beats_not_power_rows(self):
        source = """
世界名称：苍玄界
主角出生地：青石镇

| 境界 | 描述 |
| --- | --- |
| 第一境·启明 | 只是能力等级，不是剧情阶段 |
| 第二境·观微 | 仍然不是剧情阶段 |

| 阶段 | 对应剧情 |
| --- | --- |
| 第一阶段 | 青石镇商业起家，先解决凡人世界的现实问题 |
| 第二阶段 | 京城见国师，获得灵石线索 |
| 第三阶段 | 进入天剑宗，正式接触修仙世界 |
"""
        compiled = compile_canon_from_world_package(self._package(), source, "outline.md")
        write_canon_files(str(self.world_path), compiled)
        outline = load_story_outline(str(self.world_path))
        titles = [beat["title"] for beat in outline["beats"]]
        self.assertEqual(outline["world_name"], "苍玄界")
        self.assertIn("青石镇", outline["start_location"])
        self.assertTrue(any("青石镇" in title or "青石镇" in beat["summary"] for title, beat in zip(titles, outline["beats"])))
        self.assertFalse(any("启明" in title or "观微" in title for title in titles))
        contract = build_round_contract(str(self.world_path))
        self.assertTrue(contract["exists"])
        self.assertIn("青石镇", contract["active_beat"].get("summary", "") + contract["active_beat"].get("location", ""))

    def test_round_contract_blocks_locked_future_terms(self):
        source = "世界名称：苍玄界\n主角出生地：青石镇\n第一阶段：青石镇商业起家。\n第二阶段：进入天剑宗修仙。"
        write_canon_files(str(self.world_path), compile_canon_from_world_package(self._package(), source, "source.md"))
        packet = build_canon_packet("test")
        result = validate_player_action("我立刻去天剑宗拜入仙门", packet)
        self.assertFalse(result["allowed"])
        self.assertIn("当前大纲节点", result["reason"])

    def test_agent_output_future_leak_is_blocked_by_contract(self):
        source = "世界名称：苍玄界\n主角出生地：青石镇\n第一阶段：青石镇商业起家。\n第二阶段：进入天剑宗修仙。"
        write_canon_files(str(self.world_path), compile_canon_from_world_package(self._package(), source, "source.md"))
        packet = build_canon_packet("world-engine")
        output = {"scene_description": "叶然忽然来到天剑宗，拜入仙门。"}
        repaired, report = validate_agent_output("world-engine", output, packet, world_path=str(self.world_path))
        self.assertTrue(report["blocked"])
        self.assertTrue(report["conflicts"])
        self.assertIn("青石镇", repaired["scene_description"])

    def test_beat_ledger_advances_after_satisfying_current_beat(self):
        source = "世界名称：苍玄界\n主角出生地：青石镇\n第一阶段：青石镇商业起家。\n第二阶段：京城见国师，获得灵石线索。"
        write_canon_files(str(self.world_path), compile_canon_from_world_package(self._package(), source, "source.md"))
        before = load_beat_ledger(str(self.world_path), load_story_outline(str(self.world_path)))
        report = advance_beat_if_satisfied(str(self.world_path), "叶然在青石镇完成商业起家，解决了凡人世界的现实问题。", 1)
        after = load_beat_ledger(str(self.world_path), load_story_outline(str(self.world_path)))
        self.assertNotEqual(before["active_beat_id"], after["active_beat_id"])
        self.assertTrue(report["advanced"])


if __name__ == "__main__":
    unittest.main()
