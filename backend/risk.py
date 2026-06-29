"""
风险系统：驱动世界的不确定性和主角命运。
每个角色有一个风险值(0-100)，影响负面事件概率和严重程度。
"""
import random
from state import read_json, update_json, sync_player_character_state
import config

# Action risk modifiers
ACTION_RISK = {
    "战斗": 8, "逃跑": 2, "探索": 5, "修炼": 2, "突破": 6,
    "交易": 0, "休息": -2, "社交": 1, "冒险": 7, "潜入": 6,
    "谈判": 2, "求助": 0, "炼丹": 4, "锻器": 3, "猎杀": 9,
    "挑战": 7, "偷窃": 8, "救人": 6, "背叛": 10, "投靠": 3,
    "日常": -1, "学习": -1, "观察": 0, "等待": -1,
}

LUCK_WEIGHT = 1.2  # Luck is slightly weighted positive (survival bias)


def get_risk(character_id="protagonist"):
    try:
        p = read_json(config.STATE_DIR, "protagonist.json")
        return p.get("_risk", 0)
    except:
        return 0


def set_risk(value, character_id="protagonist"):
    def apply(p):
        p["_risk"] = max(0, min(100, value))
        return p
    p = update_json(config.STATE_DIR, "protagonist.json", apply)
    sync_player_character_state(p)


def modify_risk(delta, character_id="protagonist"):
    current = get_risk(character_id)
    set_risk(current + delta, character_id)


def assess_action_risk(action_text):
    """Determine risk modifier from protagonist's action description."""
    total = 0
    matched = 0
    for keyword, modifier in ACTION_RISK.items():
        if keyword in action_text:
            total += modifier
            matched += 1
    if matched > 0:
        return total / matched  # Average of matched keywords
    return 1  # Default slight risk increase for any action


def roll_fate(risk_level):
    """
    Roll for a fate event based on current risk.
    Returns: (event_type, severity, description)
    event_type: 'positive', 'negative', 'neutral', 'critical'
    severity: 0.0-1.0
    """
    # Base probability from risk
    event_chance = min(risk_level / 100.0, 0.75)

    if random.random() > event_chance:
        return ("neutral", 0.0, None)

    # Severity depends on risk, with some randomness
    base_severity = 0.2 + (risk_level / 100.0) * 0.6
    severity = base_severity + random.uniform(-0.15, 0.15)
    severity = max(0.05, min(1.0, severity))

    # Determine event type with luck bias
    roll = random.random() * LUCK_WEIGHT  # Slightly favored toward positive

    if severity > 0.85:
        return ("critical", severity, None)
    elif roll < 0.3:
        return ("negative", severity, None)
    elif roll < 0.6:
        return ("neutral", severity, None)
    else:
        return ("positive", severity, None)


def check_death(risk_level, hp_ratio=1.0):
    """
    Check if protagonist dies.
    Death chance = risk_level * (1.0 - hp_ratio) * 0.01
    At 100 risk and 0 HP: 100% death
    At 50 risk and full HP: 0% death
    """
    if hp_ratio <= 0:
        return True
    death_chance = (risk_level / 100.0) * (1.0 - hp_ratio) * 0.8
    return random.random() < death_chance


def get_fate_prompt_context():
    """Build context about current risk for world engine prompt."""
    risk = get_risk()
    level_desc = (
        "安全" if risk < 15 else
        "低风险" if risk < 30 else
        "中等风险" if risk < 50 else
        "高风险" if risk < 70 else
        "极度危险" if risk < 90 else
        "命悬一线"
    )
    return f"当前风险等级: {risk}/100 ({level_desc})"


def reset_risk():
    set_risk(5)  # Start with slight uncertainty
