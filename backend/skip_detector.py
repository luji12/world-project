SKIP_KEYWORDS = ["休息", "睡觉", "修炼", "打坐", "养伤", "等待", "发呆", "整理", "收拾"]
FORCE_RUN_KEYWORDS = ["战斗", "攻击", "逃跑", "发现", "遇到", "对话", "交易", "探索", "进入"]


def should_skip_full_round(protagonist_output: dict, world: dict) -> bool:
    action = protagonist_output.get("action", "")
    thoughts = protagonist_output.get("thoughts", "")

    has_active_events = bool(world.get("global_events", {}).get("active", []))
    if has_active_events:
        return False

    is_skip_action = any(kw in action for kw in SKIP_KEYWORDS)
    is_force_action = any(kw in action for kw in FORCE_RUN_KEYWORDS)

    return is_skip_action and not is_force_action