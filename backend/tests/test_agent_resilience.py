import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
from agents.system_agent import apply_system_output
from agents.world_engine import apply_world_output
from npc_orchestrator import apply_npc_output, is_player_visible_action, normalize_npc_action_visibility
from state import read_json, write_json


class AgentResilienceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_worlds_dir = config.WORLDS_DIR
        config.WORLDS_DIR = str(Path(self.temp_dir.name) / "worlds")
        Path(config.WORLDS_DIR).mkdir(parents=True, exist_ok=True)
        (Path(config.WORLDS_DIR) / "resilience").mkdir(parents=True, exist_ok=True)
        config.switch_world("resilience")
        config.current_world_name()

    def tearDown(self):
        config.WORLDS_DIR = self.old_worlds_dir
        self.temp_dir.cleanup()

    def test_world_engine_ignores_non_dict_triggered_events(self):
        write_json(config.STATE_DIR, "world.json", {
            "meta": {"current_round": 0, "total_rounds": 0},
            "time": {"year": 1, "month": 1, "day": 1},
            "geography": {"current_region": "main", "regions": {}},
            "factions": [],
            "global_events": {
                "pending": [{"id": "storm", "name": "山雨"}],
                "active": [],
                "completed": [],
            },
        })

        result = apply_world_output({"triggered_events": ["bad", ["nested"], {"id": "storm"}]})

        self.assertEqual(result["meta"]["current_round"], 1)
        self.assertEqual(result["global_events"]["active"][0]["id"], "storm")

    def test_world_engine_prompt_accepts_list_regions(self):
        write_json(config.STATE_DIR, "world.json", {
            "meta": {"current_round": 0, "total_rounds": 0},
            "time": {"year": 1, "month": 1, "day": 1},
            "geography": {
                "regions": [
                    {"name": "东大陆", "description": "凡人区域", "landmarks": ["青石镇"]},
                ],
            },
            "factions": [],
            "global_events": {"pending": [], "active": [], "completed": []},
        })

        from agents.world_engine import _build_world_engine_prompt
        _, user_prompt, _ = _build_world_engine_prompt()

        self.assertIn("东大陆", user_prompt)
        self.assertIn("青石镇", user_prompt)

    def test_npc_prompt_accepts_list_regions(self):
        write_json(config.STATE_DIR, "world.json", {
            "meta": {"current_round": 0, "total_rounds": 0},
            "time": {"year": 1, "month": 1, "day": 1},
            "geography": {
                "regions": [
                    {"name": "东大陆", "description": "凡人区域", "landmarks": ["青石镇"]},
                ],
            },
            "factions": [],
            "global_events": {"pending": [], "active": [], "completed": []},
        })

        from npc_orchestrator import build_core_prompt
        prompt = build_core_prompt([
            {"character": {"id": "npc-1", "name": "顾南", "role": "药铺掌柜", "location": "东大陆"}},
        ])

        self.assertIn("东大陆", prompt)

    def test_system_agent_ignores_non_dict_updates_and_rewards(self):
        write_json(config.STATE_DIR, "quests.json", {
            "active": [{"id": "q1", "name": "旧任务"}],
            "completed": [],
            "failed": [],
            "templates": [],
        })
        write_json(config.STATE_DIR, "protagonist.json", {"name": "林越", "inventory": [], "exp": 0})
        write_json(config.STATE_DIR, "characters.json", {"characters": [{"id": "p1", "name": "林越", "player_controlled": True}]})

        apply_system_output({
            "quest_updates": ["bad", {"action": "complete", "quest_id": "q1"}, ["nested"]],
            "rewards": ["bad", {"type": "exp", "value": 7}, {"type": "item", "name": "铜钱"}],
        })

        quests = read_json(config.STATE_DIR, "quests.json")
        protagonist = read_json(config.STATE_DIR, "protagonist.json")
        self.assertEqual(quests["completed"][0]["id"], "q1")
        self.assertEqual(protagonist["exp"], 7)
        self.assertEqual(protagonist["inventory"][0]["name"], "铜钱")

    def test_npc_output_filters_non_dict_actions(self):
        write_json(config.STATE_DIR, "characters.json", {
            "characters": [{"id": "npc-1", "name": "顾南", "status": "活跃"}],
        })
        write_json(config.STATE_DIR, "world.json", {
            "meta": {"current_round": 1},
            "time": {},
            "geography": {"current_region": "main", "regions": {}},
            "factions": [],
            "global_events": {"active": [], "pending": []},
        })

        apply_npc_output({
            "npc_actions": ["bad", {"npc": "顾南", "action": "抬头看向山门", "dialogue": "有人来了。"}],
            "scene_atmosphere": "山雨欲来",
        }, [])

        chars = read_json(config.STATE_DIR, "characters.json")
        self.assertEqual(chars["characters"][0]["_last_action"], "抬头看向山门")

    def test_npc_visibility_marks_private_actions_hidden(self):
        visible = normalize_npc_action_visibility({
            "npc": "顾南",
            "action": "顾南走到叶然榻前递药。",
            "dialogue": "叶公子，先喝药。",
        }, [])
        private = normalize_npc_action_visibility({
            "npc": "鬼婆",
            "action": "鬼婆暗中窥视窗内。",
            "dialogue": "小娃娃，老身等到你了。",
        }, [])

        self.assertTrue(is_player_visible_action(visible))
        self.assertFalse(is_player_visible_action(private))
        self.assertFalse(private["exposed_to_player"])

    def test_private_npc_action_is_written_to_memory(self):
        write_json(config.STATE_DIR, "characters.json", {
            "characters": [{"id": "npc-private", "name": "鬼婆", "status": "活跃"}],
        })
        write_json(config.STATE_DIR, "world.json", {
            "meta": {"current_round": 2},
            "time": {},
            "geography": {"current_region": "main", "regions": {}},
            "factions": [],
            "global_events": {"active": [], "pending": []},
        })

        apply_npc_output({
            "npc_actions": [{
                "npc": "鬼婆",
                "action": "鬼婆暗中窥视窗内，记下叶然伤势。",
                "dialogue": "",
                "visibility": "private",
                "observed_by_player": False,
            }],
        }, [{"character": {"id": "npc-private", "name": "鬼婆"}}])

        memory = read_json(config.MEMORY_DIR, "npc-private.json")
        contents = [entry.get("content", "") for entry in memory.get("recent", []) + memory.get("milestones", [])]
        self.assertTrue(any("暗中窥视" in content for content in contents))

    def test_interactive_round_only_emits_visible_npc_messages(self):
        import scheduler

        write_json(config.STATE_DIR, "world.json", {
            "meta": {"current_round": 0, "total_rounds": 0},
            "time": {"year": 1, "month": 1, "day": 1},
            "geography": {"current_region": "main", "regions": {"main": {"name": "回春堂"}}},
            "factions": [],
            "global_events": {"active": [], "pending": [], "completed": []},
        })
        write_json(config.STATE_DIR, "characters.json", {
            "characters": [
                {"id": "npc-visible", "name": "顾南", "role": "店主", "location": "main"},
                {"id": "npc-private", "name": "鬼婆", "role": "长老", "location": "main"},
                {"id": "player", "name": "叶然", "player_controlled": True},
            ],
        })
        write_json(config.STATE_DIR, "protagonist.json", {"id": "player", "name": "叶然", "action_log": []})

        events = []
        captured = {}
        npc_payload = {
            "npc_actions": [
                {"npc": "顾南", "action": "顾南走到叶然榻前递药。", "dialogue": "叶公子，先喝药。", "visibility": "direct", "observed_by_player": True},
                {"npc": "鬼婆", "action": "鬼婆暗中窥视窗内。", "dialogue": "", "visibility": "private", "observed_by_player": False},
            ],
        }

        def chronicler_stream(agent_outputs, *_args, **_kwargs):
            captured["agent_outputs"] = agent_outputs
            return iter([("done", {"narrative_passage": "顾南把药递给叶然。"})])

        with patch("scheduler.run_world_engine_stream", return_value=iter([("done", {"reasoning": "平稳", "scene_description": "药香浮动。"})])), \
             patch("scheduler.run_system_agent_stream", return_value=iter([])), \
             patch("scheduler.call_deepseek", return_value=npc_payload), \
             patch("scheduler.run_chronicler_stream", side_effect=chronicler_stream), \
             patch("scheduler.apply_chronicle_output", return_value={}), \
             patch("scheduler.assess_action_risk", return_value=0), \
             patch("scheduler.modify_risk"), \
             patch("scheduler._save_round_log"):
            scheduler._run_round_with_action(
                "向顾南要药",
                "key",
                "https://example.invalid",
                "model",
                event_callback=lambda event: events.append(event),
            )

        npc_messages = [event.data for event in events if event.event == "npc-message"]
        self.assertEqual(len(npc_messages), 1)
        self.assertEqual(npc_messages[0]["npc_name"], "顾南")
        self.assertNotIn("鬼婆", str(npc_messages))
        npc_summary = captured["agent_outputs"]["output-npc-agents"]["summary"]
        self.assertIn("其中1条玩家可见", npc_summary)
        self.assertNotIn("暗中窥视", str(captured["agent_outputs"]))

    def test_lifecycle_generates_agent_on_story_trigger(self):
        from npc_lifecycle import plan_npc_lifecycle

        write_json(config.STATE_DIR, "world.json", {
            "meta": {"current_round": 3, "total_rounds": 3},
            "time": {"year": 1, "month": 1, "day": 1},
            "geography": {"current_region": "main", "regions": {"main": {"name": "回春堂"}}},
            "factions": [],
            "global_events": {"active": [], "pending": [], "completed": []},
        })
        write_json(config.STATE_DIR, "characters.json", {
            "characters": [{"id": "player", "name": "叶然", "player_controlled": True}],
        })
        write_json(config.STATE_DIR, "protagonist.json", {
            "id": "player",
            "name": "叶然",
            "action_log": [{"round": 3, "action": "进入药铺问路，看看有没有疗伤药。"}],
        })

        with patch("npc_lifecycle.call_deepseek", return_value={
            "characters": [{
                "name": "顾南",
                "role": "药铺掌柜",
                "personality": "谨慎",
                "location": "main",
                "realm": "凡人",
                "secret": "认识旧伤病人",
                "desires": ["卖药并试探来客"],
                "daily_routine": {"上午": "看店"},
                "current_goal": "判断叶然来意",
                "story_importance": "core",
            }],
        }):
            plan = plan_npc_lifecycle("key", "https://example.invalid", "model")

        self.assertEqual(len(plan["new_characters"]), 1)
        agents = read_json(config.STATE_DIR, "npc_agents.json")["agents"]
        self.assertEqual(len(agents), 1)
        chars = read_json(config.STATE_DIR, "characters.json")["characters"]
        generated = next(c for c in chars if c.get("name") == "顾南")
        self.assertEqual(generated["agent_status"], "active")
        self.assertTrue(read_json(config.MEMORY_DIR, f"{generated['id']}.json"))

    def test_lifecycle_does_not_generate_without_story_trigger(self):
        from npc_lifecycle import plan_npc_lifecycle

        write_json(config.STATE_DIR, "world.json", {
            "meta": {"current_round": 5, "total_rounds": 5},
            "time": {},
            "geography": {"current_region": "main", "regions": {}},
            "factions": [],
            "global_events": {"active": [], "pending": [], "completed": []},
        })
        write_json(config.STATE_DIR, "characters.json", {
            "characters": [{"id": "player", "name": "叶然", "player_controlled": True}],
        })
        write_json(config.STATE_DIR, "protagonist.json", {
            "id": "player",
            "name": "叶然",
            "action_log": [{"round": 5, "action": "原地休息，检查伤势。"}],
        })

        with patch("npc_lifecycle.call_deepseek") as generator:
            plan = plan_npc_lifecycle("key", "https://example.invalid", "model")

        generator.assert_not_called()
        self.assertEqual(plan["new_characters"], [])
        self.assertEqual(read_json(config.STATE_DIR, "npc_agents.json")["agents"], [])

    def test_empty_lifecycle_registry_prevents_legacy_npc_fallback(self):
        from npc_orchestrator import get_active_npcs

        write_json(config.STATE_DIR, "world.json", {
            "meta": {"current_round": 6, "total_rounds": 6},
            "time": {},
            "geography": {"current_region": "main", "regions": {}},
            "factions": [],
            "global_events": {"active": [], "pending": [], "completed": []},
        })
        write_json(config.STATE_DIR, "characters.json", {
            "characters": [
                {"id": "player", "name": "叶然", "player_controlled": True},
                {"id": "npc-001", "name": "顾南", "role": "药铺掌柜", "location": "main", "status": "活跃"},
            ],
        })
        write_json(config.STATE_DIR, "protagonist.json", {
            "id": "player",
            "name": "叶然",
            "action_log": [{"round": 6, "action": "原地休息。"}],
        })
        write_json(config.STATE_DIR, "npc_agents.json", {
            "version": "0.1",
            "updated_round": 6,
            "agents": [],
        })

        self.assertEqual(get_active_npcs(), {"core": [], "scene": []})

    def test_lifecycle_retires_agent_but_keeps_archive(self):
        from npc_lifecycle import plan_npc_lifecycle

        write_json(config.STATE_DIR, "world.json", {
            "meta": {"current_round": 7, "total_rounds": 7},
            "time": {},
            "geography": {"current_region": "main", "regions": {}},
            "factions": [],
            "global_events": {"active": [], "pending": [], "completed": []},
        })
        write_json(config.STATE_DIR, "characters.json", {
            "characters": [
                {"id": "player", "name": "叶然", "player_controlled": True},
                {"id": "npc-001", "name": "顾南", "role": "药铺掌柜", "agent_status": "active", "status": "活跃"},
            ],
        })
        write_json(config.STATE_DIR, "protagonist.json", {
            "id": "player",
            "name": "叶然",
            "action_log": [{"round": 7, "action": "告别顾南，离开药铺。"}],
        })
        write_json(config.STATE_DIR, "npc_agents.json", {
            "version": "0.1",
            "updated_round": 3,
            "agents": [{"npc_id": "npc-001", "name": "顾南", "last_tick_round": 3}],
        })

        plan = plan_npc_lifecycle()

        self.assertIn("npc-001", plan["retire_ids"])
        self.assertEqual(read_json(config.STATE_DIR, "npc_agents.json")["agents"], [])
        chars = read_json(config.STATE_DIR, "characters.json")["characters"]
        archived = next(c for c in chars if c.get("id") == "npc-001")
        self.assertEqual(archived["agent_status"], "dormant")
        memory = read_json(config.MEMORY_DIR, "npc-001.json")
        self.assertTrue(any("退出当前活跃剧情" in entry.get("content", "") for entry in memory.get("milestones", [])))

    def test_lifecycle_recalls_archived_npc_without_duplicate(self):
        from npc_lifecycle import plan_npc_lifecycle

        write_json(config.STATE_DIR, "world.json", {
            "meta": {"current_round": 8, "total_rounds": 8},
            "time": {},
            "geography": {"current_region": "main", "regions": {}},
            "factions": [],
            "global_events": {"active": [], "pending": [], "completed": []},
        })
        write_json(config.STATE_DIR, "characters.json", {
            "characters": [
                {"id": "player", "name": "叶然", "player_controlled": True},
                {"id": "npc-001", "name": "顾南", "role": "药铺掌柜", "agent_status": "dormant", "status": "活跃"},
            ],
        })
        write_json(config.STATE_DIR, "protagonist.json", {
            "id": "player",
            "name": "叶然",
            "action_log": [{"round": 8, "action": "拜访顾南，请他帮忙辨认丹药。"}],
        })

        with patch("npc_lifecycle.call_deepseek") as generator:
            plan = plan_npc_lifecycle("key", "https://example.invalid", "model")

        generator.assert_not_called()
        self.assertEqual(plan["new_characters"], [])
        self.assertIn("npc-001", plan["activate_ids"])
        names = [c.get("name") for c in read_json(config.STATE_DIR, "characters.json")["characters"]]
        self.assertEqual(names.count("顾南"), 1)


if __name__ == "__main__":
    unittest.main()
