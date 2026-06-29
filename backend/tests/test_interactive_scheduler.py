import unittest
from unittest.mock import patch

import scheduler


class InteractiveSchedulerTests(unittest.TestCase):
    @patch("scheduler.read_json")
    @patch("scheduler._run_round_with_action")
    def test_interactive_mode_returns_after_one_player_action(self, run_action, read_json):
        read_json.return_value = {"meta": {"current_round": 7}}
        events = []

        scheduler.run_interactive_rounds(
            "先观察城门的守卫",
            "key",
            "https://example.invalid",
            "model",
            event_callback=lambda event: events.append(event),
        )

        run_action.assert_called_once()
        self.assertEqual(events[-1].event, "intervention-required")
        self.assertEqual(events[-1].data["round"], 7)
        self.assertIn("等待你的下一步行动", events[-1].data["reason"])

    @patch("scheduler._save_round_log")
    @patch("scheduler.run_chronicler_stream")
    @patch("scheduler.run_system_agent_stream")
    @patch("scheduler.run_world_engine_stream")
    @patch("scheduler.apply_protagonist_output")
    @patch("scheduler.modify_risk")
    @patch("scheduler.assess_action_risk", return_value=0)
    @patch("scheduler.read_json")
    def test_player_action_is_applied_before_world_agent_runs(
        self, read_json, assess_risk, modify_risk, apply_action, world_stream,
        system_stream, chronicler_stream, save_log,
    ):
        read_json.return_value = {"meta": {"current_round": 4}}
        ordering = []

        apply_action.side_effect = lambda payload: ordering.append(("action", payload["action"]))
        world_stream.side_effect = lambda *args: (ordering.append(("world", "started")) or iter(()))
        system_stream.return_value = iter(())
        chronicler_stream.return_value = iter(())

        scheduler._run_round_with_action("先把密信藏进靴底", "key", "https://example.invalid", "model")

        self.assertEqual(ordering[0], ("action", "先把密信藏进靴底"))
        self.assertEqual(ordering[1], ("world", "started"))


if __name__ == "__main__":
    unittest.main()
