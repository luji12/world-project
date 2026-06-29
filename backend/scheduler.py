import time
import threading
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from agents.world_engine import run_world_engine, apply_world_output, run_world_engine_stream
from agents.system_agent import run_system_agent, apply_system_output, run_system_agent_stream
from agents.protagonist import run_protagonist, apply_protagonist_output, run_protagonist_stream
from agents.chronicler import run_chronicler, apply_chronicle_output, run_chronicler_stream
from agents.base import call_deepseek, normalize_agent_output, ensure_list_of_dicts
import config
from state import read_json, write_json, update_json, get_player_character
from risk import get_risk, modify_risk, assess_action_risk, check_death, reset_risk
from agent_templates import get_agent_config
from story_ledger import StoryLedger


def _get_npc_director_prompt():
    try:
        world = read_json(config.STATE_DIR, "world.json")
        meta = world.get("meta", {})
        ac = get_agent_config(meta)
        wt = meta.get("world_type", "xuanhuan")
        nr = ac.get("narrator", {}).get("role", "小说家")
        we = ac.get("world_engine", {}).get("role", "故事世界")
        return f"你是{nr}笔下{we}的场景导演。当前世界类型为{wt}。根据角色设定为NPC生成本轮行为和对话。行为和对话风格必须符合{wt}世界观。输出JSON。"
    except Exception:
        return "你是故事世界的场景导演。根据角色设定为NPC生成本轮行为和对话。输出JSON。"


def _npc_message_payload(action, current_round):
    return {
        "npc_id": action.get("npc_id", ""),
        "npc_name": action.get("npc", ""),
        "dialogue": action.get("dialogue", ""),
        "action_desc": action.get("action", ""),
        "visibility": action.get("visibility", ""),
        "observed_by_player": bool(action.get("observed_by_player")),
        "audience": action.get("audience", []),
        "exposed_to_player": bool(action.get("exposed_to_player")),
        "round": current_round,
        "bubble_type": "dialog",
    }


def _summarize_npc_visibility(total_active, core_count, scene_count, visible_count):
    return f"推演了{total_active}个活跃角色（核心{core_count}，场景{scene_count}），其中{visible_count}条玩家可见"


class RoundEvent:
    def __init__(self, event_type: str, data: dict):
        self.event = event_type
        self.data = data


def run_round(api_key, base_url, model, event_callback=None, pause_check=None, player_controlled=True):
    """Execute one full round. Calls event_callback(event) for SSE streaming.

    player_controlled=True: protagonist agent may request player decision (intervention-required)
    player_controlled=False: fully autonomous, protagonist acts independently (auto mode)
    """
    # Register API credentials so apply_* and memory functions can call LLM
    import session_config
    session_config.set_session(api_key, base_url, model)

    results = {}

    def emit(event_type, data):
        # Use agent-specific key for results to avoid overwrites
        if isinstance(data, dict) and "agent" in data and event_type == "agent-output":
            results[f"output-{data['agent']}"] = data
        elif isinstance(data, dict) and "agent" in data and event_type == "agent-error":
            results[f"error-{data['agent']}"] = data
        else:
            results[event_type] = data
        if event_callback:
            event_callback(RoundEvent(event_type, data))

    world = read_json(config.STATE_DIR, "world.json")
    current_round = world["meta"]["current_round"] + 1

    emit("round-start", {"round": current_round})

    while pause_check and pause_check():
        time.sleep(0.3)

    # 1. World Engine (streaming)
    emit("agent-start", {"agent": "world-engine", "round": current_round})
    try:
        we_buffer = ""
        for output_type, data in run_world_engine_stream(api_key, base_url, model):
            if output_type == "token":
                we_buffer += data
                emit("agent-stream", {"agent": "world-engine", "delta": data})
            elif output_type == "done":
                world_output = normalize_agent_output(data, fallback_key="reasoning")
                world_state = apply_world_output(world_output)
                
                # Emit narration for group chat
                if world_output.get("scene_description"):
                    emit("narration", {
                        "text": world_output.get("scene_description", ""),
                        "round": current_round,
                        "bubble_type": "narration",
                    })

                emit("agent-output", {
                    "agent": "world-engine",
                    "summary": world_output.get("reasoning", "")[:300],
                })
    except Exception as e:
        emit("agent-error", {"agent": "world-engine", "error": str(e)})

    while pause_check and pause_check():
        time.sleep(0.3)

    # 2-5. System Agent, Protagonist, NPC — 并行流式执行
    def _run_system_agent():
        emit("agent-start", {"agent": "system-agent", "round": current_round})
        try:
            sys_buffer = ""
            system_output = None
            for output_type, data in run_system_agent_stream(api_key, base_url, model):
                if output_type == "token":
                    sys_buffer += data
                    emit("agent-stream", {"agent": "system-agent", "delta": data})
                elif output_type == "done":
                    system_output = normalize_agent_output(data, fallback_key="system_dialogue")
                    apply_system_output(system_output)
                    
                    if system_output.get("system_dialogue"):
                        emit("system-message", {
                            "dialogue": system_output.get("system_dialogue", ""),
                            "quest_hint": system_output.get("quest_generation", {}).get("name", ""),
                            "round": current_round,
                            "bubble_type": "system",
                        })

                    emit("agent-output", {
                        "agent": "system-agent",
                        "summary": system_output.get("system_dialogue", system_output.get("reasoning", ""))[:300],
                        "system_dialogue": system_output.get("system_dialogue", ""),
                    })
                    break
            return ("system-agent", system_output, None)
        except Exception as e:
            emit("agent-error", {"agent": "system-agent", "error": str(e)})
            return ("system-agent", None, str(e))

    def _run_protagonist():
        emit("agent-start", {"agent": "protagonist", "round": current_round})
        try:
            pc_buffer = ""
            protagonist_output = None
            for output_type, data in run_protagonist_stream(api_key, base_url, model):
                if output_type == "token":
                    pc_buffer += data
                    emit("agent-stream", {"agent": "protagonist", "delta": data})
                elif output_type == "done":
                    protagonist_output = normalize_agent_output(data, fallback_key="action")
                    apply_protagonist_output(protagonist_output)
                    
                    # This path is the automatic scheduler.  Player-controlled
                    # actions are settled by _run_round_with_action instead.
                    emit("protagonist-auto", {
                        "action": protagonist_output.get("action", ""),
                        "thoughts": protagonist_output.get("thoughts", ""),
                        "round": current_round,
                        "bubble_type": "action",
                    })

                    modify_risk(assess_action_risk(protagonist_output.get("action", "")))
                    emit("agent-output", {
                        "agent": "protagonist",
                        "summary": protagonist_output.get("action", "")[:200],
                        "thoughts": protagonist_output.get("thoughts", "")[:200],
                        "needs_decision": protagonist_output.get("needs_decision", False) and player_controlled,
                        "decision_prompt": protagonist_output.get("decision_prompt", ""),
                    })
                    if player_controlled and protagonist_output.get("needs_decision"):
                        emit("intervention-required", {
                            "reason": protagonist_output.get("decision_prompt", "主角需要做出选择"),
                            "summary": protagonist_output.get("action", "")[:200],
                            "thoughts": protagonist_output.get("thoughts", "")[:150],
                        })
                    break
            return ("protagonist", protagonist_output, None)
        except Exception as e:
            emit("agent-error", {"agent": "protagonist", "error": str(e)})
            return ("protagonist", None, str(e))

    def _run_npc_designer():
        emit("agent-start", {"agent": "npc-designer", "round": current_round})
        try:
            from npc_lifecycle import plan_npc_lifecycle
            npc_plan = plan_npc_lifecycle(api_key, base_url, model)
            if npc_plan:
                summary = (
                    f"NPC生命周期：新增{len(npc_plan.get('new_characters', []))}，"
                    f"激活{len(npc_plan.get('activate_ids', []))}，退场{len(npc_plan.get('retire_ids', []))}。"
                    f"{npc_plan.get('reason', '')}"
                )
                emit("agent-output", {"agent": "npc-designer", "summary": summary, "lifecycle": npc_plan})
            else:
                emit("agent-output", {"agent": "npc-designer", "summary": "当前无需新角色"})
            return ("npc-designer", npc_plan, None)
        except Exception as e:
            emit("agent-error", {"agent": "npc-designer", "error": str(e)})
            return ("npc-designer", None, str(e))

    def _run_npc_agents():
        emit("agent-start", {"agent": "npc-agents", "round": current_round})
        try:
            from npc_orchestrator import (get_active_npcs, build_core_prompt,
                                           build_scene_batch_prompt,
                                           apply_npc_output, get_background_npc_routines,
                                           normalize_npc_action_visibility, is_player_visible_action)
            layered = get_active_npcs()
            core_npcs = layered.get("core", [])
            scene_npcs = layered.get("scene", [])
            bg_routines = get_background_npc_routines()

            lite_model = model.replace("chat", "lite") if "deepseek" in model and "lite" not in model else model
            all_actions = []

            def _run_batches(npc_items, prompt_fn, use_model, max_tok, batch_size=4):
                if not npc_items:
                    return []
                batches = [npc_items[i:i+batch_size] for i in range(0, len(npc_items), batch_size)]
                batch_results = []
                with ThreadPoolExecutor(max_workers=len(batches)) as be:
                    futures = []
                    for batch in batches:
                        prompt = prompt_fn(batch)
                        futures.append(be.submit(call_deepseek, _get_npc_director_prompt(), prompt, api_key=api_key, base_url=base_url, model=use_model, max_tokens=max_tok))
                    for f in futures:
                        try:
                            out = f.result()
                            if out:
                                batch_results.append(normalize_agent_output(out, fallback_key="npc_actions"))
                        except Exception:
                            pass
                return batch_results

            core_results = _run_batches(core_npcs, build_core_prompt, model, 3072, 4)
            scene_results = _run_batches(scene_npcs, build_scene_batch_prompt, lite_model, 2048, 5)

            for out in core_results:
                apply_npc_output(out, core_npcs)
                all_actions.extend(normalize_npc_action_visibility(action, core_npcs) for action in ensure_list_of_dicts(out.get("npc_actions")))
            for out in scene_results:
                apply_npc_output(out, scene_npcs)
                all_actions.extend(normalize_npc_action_visibility(action, scene_npcs) for action in ensure_list_of_dicts(out.get("npc_actions")))

            visible_actions = [action for action in all_actions if is_player_visible_action(action)]
            for i, action in enumerate(visible_actions):
                if not isinstance(action, dict):
                    continue
                if i > 0:
                    time.sleep(0.15)
                emit("npc-message", _npc_message_payload(action, current_round))

            total_active = len(core_npcs) + len(scene_npcs)
            emit("agent-output", {
                "agent": "npc-agents",
                "summary": _summarize_npc_visibility(total_active, len(core_npcs), len(scene_npcs), len(visible_actions)),
                "background_npcs": bg_routines,
            })
            return ("npc-agents", None, None)
        except ImportError:
            emit("agent-output", {"agent": "npc-agents", "summary": "无活跃角色需要推演"})
            return ("npc-agents", None, None)
        except Exception as e:
            emit("agent-error", {"agent": "npc-agents", "error": str(e)})
            return ("npc-agents", None, str(e))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(_run_system_agent): "system-agent",
            executor.submit(_run_protagonist): "protagonist",
        }
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                pass

    _run_npc_designer()
    _run_npc_agents()

    while pause_check and pause_check():
        time.sleep(0.3)

    # Skip detection: if protagonist is resting and no active events, skip NPC + Chronicler
    from skip_detector import should_skip_full_round
    world_snapshot = read_json(config.STATE_DIR, "world.json")
    protagonist_action_text = results.get("output-protagonist", {}).get("summary", "")
    if should_skip_full_round({"action": protagonist_action_text}, world_snapshot):
        emit("agent-output", {"agent": "npc-designer", "summary": "（休息轮，跳过NPC推演）"})
        emit("agent-output", {"agent": "npc-agents", "summary": "（休息轮，跳过）"})
        from state import append_text as _append_text
        skip_narrative = f"\n\n---\n\n### 第{current_round}轮\n\n{protagonist_action_text}\n\n"
        _append_text(config.CHRONICLE_DIR, f"volume-{max(1, (current_round // 30) + 1):02d}.md", skip_narrative)
        emit("agent-output", {"agent": "chronicler", "summary": f"（休息轮）{protagonist_action_text[:200]}"})
        emit("round-complete", {
            "round": current_round,
            "narrative_preview": protagonist_action_text[:200],
        })
        _save_round_log(current_round, results)
        return results

    while pause_check and pause_check():
        time.sleep(0.3)

    try:
        from state import clear_applied_injections
        clear_applied_injections()
    except Exception:
        pass

    # 6. Chronicler (streaming)
    emit("agent-start", {"agent": "chronicler", "round": current_round})
    chronicle_text_buffer = ""
    last_sent_len = 0
    chronicle_output = {}
    try:
        for output_type, data in run_chronicler_stream(results, api_key, base_url, model):
            if output_type == "token":
                chronicle_text_buffer += data
                if len(chronicle_text_buffer) - last_sent_len >= 50:
                    emit("agent-stream", {
                        "agent": "chronicler",
                        "delta": chronicle_text_buffer[last_sent_len:],
                    })
                    last_sent_len = len(chronicle_text_buffer)
            elif output_type == "done":
                chronicle_output = normalize_agent_output(data, fallback_key="narrative_passage")
                applied = apply_chronicle_output(chronicle_output)
                emit("agent-output", {
                    "agent": "chronicler",
                    "summary": chronicle_output.get("narrative_passage", ""),
                    "bubble_type": "chapter",
                })
                break
        if chronicle_output:
            try:
                ledger = StoryLedger(config.world_dir())
                active_chapter = ledger.active_chapter(round_no=current_round)
                ledger.create_checkpoint(
                    f"第{current_round}轮自动存档",
                    chapter_no=active_chapter["chapter_no"],
                    metadata={"round": current_round, "reason": "auto"},
                )
            except Exception:
                pass
    except Exception as e:
        emit("agent-error", {"agent": "chronicler", "error": str(e)})

    emit("round-complete", {
        "round": current_round,
        "narrative_preview": results.get("output-chronicler", {}).get("summary", "")[:200],
    })

    # Emit turn-start for player-controlled modes to signal it's user's turn
    if player_controlled:
        suggested = []
        if isinstance(chronicle_output, dict):
            raw_suggested = chronicle_output.get("suggested_actions", [])
            if isinstance(raw_suggested, list):
                suggested = raw_suggested[:3]
        emit("turn-start", {
            "round": current_round,
            "suggested_actions": suggested,
            "summary": chronicle_output.get("narrative_passage", "") if isinstance(chronicle_output, dict) else "",
        })

    # Save all agent outputs to rounds log
    _save_round_log(current_round, results)

    return results


def _save_round_log(round_num, results):
    """Append all agent outputs to rounds-log.json for the Reader."""
    from state import write_json, _get_lock
    log_path = config.CHRONICLE_DIR
    log_file = os.path.join(log_path, "rounds-log.json")

    # Lock the entire read-modify-write to prevent race conditions
    lock = _get_lock(log_file)
    with lock:
        log = {"rounds": []}
        if os.path.exists(log_file):
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    log = json.loads(f.read())
            except:
                pass

        round_entry = {"round": round_num}
        for key, data in results.items():
            if not isinstance(data, dict):
                continue
            if key.startswith("output-"):
                agent = key[7:]
            elif key.startswith("error-"):
                agent = key[6:]
            elif "agent" in data:
                agent = data["agent"]
            else:
                continue
            round_entry[agent] = {
                "summary": str(data.get("summary", data.get("reasoning", "")))[:500],
                "error": str(data.get("error", ""))[:200],
                "thoughts": str(data.get("thoughts", ""))[:200],
                "system_dialogue": str(data.get("system_dialogue", ""))[:200],
            }

        if len(round_entry) > 1:
            log["rounds"].append(round_entry)
            log["rounds"] = log["rounds"][-50:]
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(log, f, ensure_ascii=False, indent=2)

        # Also archive per-round
        archive_file = os.path.join(log_path, f"round-{round_num:04d}.json")
        with open(archive_file, "w", encoding="utf-8") as f:
            json.dump(round_entry, f, ensure_ascii=False, indent=2)


def run_rounds_auto(stop_conditions, intervention_nodes, api_key, base_url, model, event_callback=None, pause_check=None, interactive_mode=False, player_controlled=None):
    """Run rounds automatically. Returns number of rounds executed.

    player_controlled: If None, defaults to interactive_mode value.
        True = protagonist can request player decisions (guided mode)
        False = fully autonomous, ignore protagonist needs_decision (auto mode)
    """
    if player_controlled is None:
        player_controlled = interactive_mode
    max_rounds = stop_conditions.get("max_rounds", 100)
    target_realm = stop_conditions.get("target_realm", "")
    target_date = stop_conditions.get("target_date", "")
    round_count = 0

    while round_count < max_rounds:
        # Check pause
        while pause_check and pause_check():
            time.sleep(0.5)

        # Capture pre-round state for intervention detection
        pre_protagonist = get_player_character() or {}
        pre_world = read_json(config.STATE_DIR, "world.json")
        pre_realm = pre_protagonist.get("realm") or pre_protagonist.get("cultivation", {}).get("realm")
        pre_active_event_ids = {
            evt.get("id") or evt.get("name")
            for evt in pre_world.get("global_events", {}).get("active", [])
        }

        round_count += 1
        results = run_round(api_key, base_url, model, event_callback, pause_check, player_controlled=player_controlled)
        if "intervention-required" in results:
            break

        # Check stop conditions
        world = read_json(config.STATE_DIR, "world.json")
        protagonist = get_player_character() or {}

        # Check story end conditions
        if _check_story_end(protagonist, event_callback):
            break

        # Interactive mode: pause every 2-3 rounds
        if interactive_mode and round_count % 3 == 0:
            if event_callback:
                event_callback(RoundEvent("intervention-required", {
                    "reason": "需要你的决策——接下来该做什么？探索、行动、还是冒险？",
                    "round": round_count
                }))
            break

        post_realm = protagonist.get("realm") or protagonist.get("cultivation", {}).get("realm", "")
        if target_realm and (post_realm == target_realm or target_realm in post_realm):
            if event_callback:
                event_callback(RoundEvent("auto-stop", {
                    "reason": f"主角已达到目标等级：{post_realm}",
                    "round": round_count
                }))
            break

        if target_date:
            date_str = f"{world['time']['year']}年{world['time']['month']}月"
            if target_date in date_str:
                if event_callback:
                    event_callback(RoundEvent("auto-stop", {
                        "reason": f"已达到目标日期：{target_date}",
                        "round": round_count
                    }))
                break

        # Check intervention nodes only in interactive/guided mode
        if player_controlled:
            if intervention_nodes.get("on_realm_breakthrough"):
                if pre_realm and post_realm and pre_realm != post_realm:
                    if event_callback:
                        event_callback(RoundEvent("intervention-required", {
                            "reason": f"能力突破：{pre_realm} → {post_realm}",
                            "round": round_count
                        }))
                    break

            if intervention_nodes.get("on_world_event"):
                active_events = world.get("global_events", {}).get("active", [])
                new_events = [
                    evt for evt in active_events
                    if (evt.get("id") or evt.get("name")) not in pre_active_event_ids
                ]
                if new_events:
                    if event_callback:
                        event_callback(RoundEvent("intervention-required", {
                            "reason": f"世界事件激活：{new_events[-1].get('name', '')}",
                            "round": round_count
                        }))
                    break

    return round_count


def run_interactive_rounds(protagonist_action, api_key, base_url, model, event_callback=None, pause_check=None):
    """Settle exactly one player action, then return control to that player.

    Auto mode may keep advancing an observer story.  A player-controlled role
    must never be advanced for dozens of hidden turns after one action.
    """
    _run_round_with_action(protagonist_action, api_key, base_url, model, event_callback, pause_check)
    world = read_json(config.STATE_DIR, "world.json")
    if event_callback:
        event_callback(RoundEvent("intervention-required", {
            "reason": "本回合已结算，等待你的下一步行动。",
            "round": world["meta"]["current_round"],
        }))


def _run_round_with_action(action_text, api_key, base_url, model, event_callback=None, pause_check=None):
    """Run a round with the protagonist's action pre-determined (player-controlled mode)."""
    import session_config
    session_config.set_session(api_key, base_url, model)

    emit = lambda t, d: event_callback and event_callback(RoundEvent(t, d))
    results = {}

    def record(event_type, data):
        if isinstance(data, dict) and "agent" in data and event_type == "agent-output":
            results[f"output-{data['agent']}"] = data
        elif isinstance(data, dict) and "agent" in data and event_type == "agent-error":
            results[f"error-{data['agent']}"] = data
        emit(event_type, data)

    world = read_json(config.STATE_DIR, "world.json")
    current_round = world["meta"]["current_round"] + 1
    emit("round-start", {"round": current_round})

    emit("agent-start", {"agent": "protagonist", "round": current_round})
    try:
        apply_protagonist_output({
            "action": action_text,
            "thoughts": "",
            "location": "",
            "emotional_state": "由玩家决定",
        })
        modify_risk(assess_action_risk(action_text))
        record("agent-output", {"agent": "protagonist", "summary": action_text[:300], "player_controlled": True})
        emit("player-action-recorded", {"action": action_text, "round": current_round, "bubble_type": "player"})
    except Exception as e:
        record("agent-error", {"agent": "protagonist", "error": str(e)})

    wo_output, so_output, npc_output = {}, {}, {}

    while pause_check and pause_check():
        time.sleep(0.3)

    # 1. World Engine (streaming)
    emit("agent-start", {"agent": "world-engine", "round": current_round})
    pending_narration = None
    try:
        for output_type, data in run_world_engine_stream(api_key, base_url, model):
            if output_type == "token":
                emit("agent-stream", {"agent": "world-engine", "delta": data})
            elif output_type == "done":
                wo_output = normalize_agent_output(data, fallback_key="reasoning")
                apply_world_output(wo_output)
                if wo_output.get("scene_description"):
                    pending_narration = {
                        "text": wo_output.get("scene_description", ""),
                        "round": current_round,
                        "bubble_type": "narration",
                    }
                record("agent-output", {"agent": "world-engine", "summary": wo_output.get("reasoning", "")[:300]})
    except Exception as e:
        record("agent-error", {"agent": "world-engine", "error": str(e)})

    while pause_check and pause_check():
        time.sleep(0.3)

    # 2. System, NPC Designer, NPC Agents — 并行执行
    def _run_so():
        nonlocal so_output
        emit("agent-start", {"agent": "system-agent", "round": current_round})
        try:
            for output_type, data in run_system_agent_stream(api_key, base_url, model):
                if output_type == "token":
                    emit("agent-stream", {"agent": "system-agent", "delta": data})
                elif output_type == "done":
                    so_output = normalize_agent_output(data, fallback_key="system_dialogue")
                    apply_system_output(so_output)
                    if so_output.get("system_dialogue"):
                        emit("system-message", {
                            "dialogue": so_output.get("system_dialogue", ""),
                            "quest_hint": so_output.get("quest_generation", {}).get("name", ""),
                            "round": current_round,
                            "bubble_type": "system",
                        })
                    record("agent-output", {"agent": "system-agent", "summary": so_output.get("system_dialogue", so_output.get("reasoning", ""))[:300]})
                    break
        except Exception as e:
            record("agent-error", {"agent": "system-agent", "error": str(e)})

    def _run_npc_designer():
        emit("agent-start", {"agent": "npc-designer", "round": current_round})
        try:
            from npc_lifecycle import plan_npc_lifecycle
            npc_plan = plan_npc_lifecycle(api_key, base_url, model)
            if npc_plan:
                summary = (
                    f"NPC生命周期：新增{len(npc_plan.get('new_characters', []))}，"
                    f"激活{len(npc_plan.get('activate_ids', []))}，退场{len(npc_plan.get('retire_ids', []))}。"
                    f"{npc_plan.get('reason', '')}"
                )
                record("agent-output", {"agent": "npc-designer", "summary": summary, "lifecycle": npc_plan})
            else:
                record("agent-output", {"agent": "npc-designer", "summary": "当前无需新角色"})
        except Exception as e:
            record("agent-error", {"agent": "npc-designer", "error": str(e)})

    def _run_npcs():
        nonlocal npc_output
        emit("agent-start", {"agent": "npc-agents", "round": current_round})
        try:
            from npc_orchestrator import (get_active_npcs, build_core_prompt,
                                           build_scene_batch_prompt,
                                           apply_npc_output, get_background_npc_routines,
                                           normalize_npc_action_visibility, is_player_visible_action)
            layered = get_active_npcs()
            core_npcs = layered.get("core", [])
            scene_npcs = layered.get("scene", [])
            bg_routines = get_background_npc_routines()

            lite_model = model.replace("chat", "lite") if "deepseek" in model and "lite" not in model else model
            all_actions = []

            def _run_batches(npc_items, prompt_fn, use_model, max_tok, batch_size=4):
                if not npc_items:
                    return []
                batches = [npc_items[i:i+batch_size] for i in range(0, len(npc_items), batch_size)]
                batch_results = []
                with ThreadPoolExecutor(max_workers=len(batches)) as be:
                    futures = []
                    for batch in batches:
                        prompt = prompt_fn(batch)
                        futures.append(be.submit(call_deepseek, _get_npc_director_prompt(), prompt, api_key=api_key, base_url=base_url, model=use_model, max_tokens=max_tok))
                    for f in futures:
                        try:
                            out = f.result()
                            if out:
                                batch_results.append(normalize_agent_output(out, fallback_key="npc_actions"))
                        except Exception:
                            pass
                return batch_results

            core_results = _run_batches(core_npcs, build_core_prompt, model, 3072, 4)
            scene_results = _run_batches(scene_npcs, build_scene_batch_prompt, lite_model, 2048, 5)

            for out in core_results:
                apply_npc_output(out, core_npcs)
                all_actions.extend(normalize_npc_action_visibility(action, core_npcs) for action in ensure_list_of_dicts(out.get("npc_actions")))
            for out in scene_results:
                apply_npc_output(out, scene_npcs)
                all_actions.extend(normalize_npc_action_visibility(action, scene_npcs) for action in ensure_list_of_dicts(out.get("npc_actions")))

            visible_actions = [action for action in all_actions if is_player_visible_action(action)]
            for i, action in enumerate(visible_actions):
                if not isinstance(action, dict):
                    continue
                if i > 0:
                    time.sleep(0.15)
                emit("npc-message", _npc_message_payload(action, current_round))

            total_active = len(core_npcs) + len(scene_npcs)
            npc_output = {"npc_actions": visible_actions}
            record("agent-output", {"agent": "npc-agents", "summary": _summarize_npc_visibility(total_active, len(core_npcs), len(scene_npcs), len(visible_actions)), "background_npcs": bg_routines})
        except ImportError:
            record("agent-output", {"agent": "npc-agents", "summary": "无活跃角色需要推演"})
        except Exception as e:
            record("agent-error", {"agent": "npc-agents", "error": str(e)})

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(_run_so): "system-agent",
            executor.submit(_run_npc_designer): "npc-designer",
        }
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                pass

    _run_npcs()

    if pending_narration:
        emit("narration", pending_narration)

    while pause_check and pause_check():
        time.sleep(0.3)

    try:
        from state import clear_applied_injections
        clear_applied_injections()
    except Exception:
        pass

    # 6. Chronicler (streaming)
    emit("agent-start", {"agent": "chronicler", "round": current_round})
    chronicle_text_buffer = ""
    last_sent_len = 0
    chronicler_output = {}
    try:
        for output_type, data in run_chronicler_stream(results, api_key, base_url, model):
            if output_type == "token":
                chronicle_text_buffer += data
                if len(chronicle_text_buffer) - last_sent_len >= 50:
                    emit("agent-stream", {
                        "agent": "chronicler",
                        "delta": chronicle_text_buffer[last_sent_len:],
                    })
                    last_sent_len = len(chronicle_text_buffer)
            elif output_type == "done":
                chronicler_output = normalize_agent_output(data, fallback_key="narrative_passage")
                apply_chronicle_output(chronicler_output)
                try:
                    ledger = StoryLedger(config.world_dir())
                    active_chapter = ledger.active_chapter(round_no=current_round)
                    ledger.create_checkpoint(
                        f"第{current_round}轮自动存档",
                        chapter_no=active_chapter["chapter_no"],
                        metadata={"round": current_round, "reason": "auto"},
                    )
                except Exception:
                    pass
                record("agent-output", {
                    "agent": "chronicler",
                    "summary": chronicler_output.get("narrative_passage", ""),
                    "round": current_round,
                    "bubble_type": "chapter",
                })
                break
    except Exception as e:
        record("agent-error", {"agent": "chronicler", "error": str(e)})

    emit("round-complete", {
        "round": current_round,
        "narrative_preview": chronicler_output.get("narrative_passage", "")[:200],
    })

    # Emit turn-start for chat mode
    suggested = chronicler_output.get("suggested_actions", [])
    if not isinstance(suggested, list):
        suggested = []
    emit("turn-start", {
        "round": current_round,
        "suggested_actions": suggested[:3],
        "summary": chronicler_output.get("narrative_passage", ""),
    })

    _save_round_log(current_round, results)


def _check_and_generate_npcs(api_key, base_url, model):
    """Check if new NPCs should be generated based on story context."""
    chars = read_json(config.STATE_DIR, "characters.json")
    protagonist = get_player_character() or {}
    world = read_json(config.STATE_DIR, "world.json")

    current_round = world["meta"]["current_round"]
    existing_count = len(chars.get("characters", []))
    max_npcs = 50

    should_generate = False
    num_to_create = 1

    if existing_count < 5:
        should_generate = True
        num_to_create = 2
    elif existing_count < 15 and current_round % 5 == 0:
        should_generate = True
        num_to_create = 2
    elif existing_count < max_npcs and current_round % 8 == 0:
        should_generate = True
        num_to_create = 1

    action_log = protagonist.get("action_log", [])
    if action_log:
        last_action = action_log[-1].get("action", "")
        encounter_words = ["遇到", "遇见", "碰到", "看到", "发现", "来到", "进入", "拜访", "问路", "打听", "进城", "上山", "入店", "集市"]
        if any(w in last_action for w in encounter_words):
            should_generate = True
            num_to_create = max(num_to_create, 2)

    if not should_generate or existing_count >= max_npcs:
        return None

    system_prompt = f"你是角色设计师。根据当前世界背景创建{num_to_create}个新角色。角色必须有独立动机、秘密和故事线。输出JSON：{{\"characters\": [{{name, role, personality, location, realm, secret, desires:[], daily_routine:{{\"上午\":\"...\",\"下午\":\"...\",\"晚上\":\"...\"}}, status:\"活跃\"}}]}}"

    user_prompt = json.dumps({
        "instruction": f"根据世界背景创建{num_to_create}个新角色。当前已有{existing_count}个角色，不要重复。为每个角色设置daily_routine和desires。",
        "world_info": {
            "time": world.get("time"),
            "current_region": world.get("geography", {}).get("current_region"),
            "factions": [f.get("name") for f in world.get("factions", [])],
        },
        "existing_names": [c.get("name") for c in chars.get("characters", [])],
        "protagonist_recent": action_log[-3:] if action_log else [],
    }, ensure_ascii=False)

    try:
        output = normalize_agent_output(
            call_deepseek(system_prompt, user_prompt, api_key=api_key, base_url=base_url, model=model, max_tokens=1024),
            fallback_key="characters",
        )
        new_chars = ensure_list_of_dicts(output.get("characters"))
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
        # Init memory for new NPCs
        from memory_manager import init_character_memory
        for nc in new_chars:
            init_character_memory(nc["id"], nc.get("name", nc["id"]), "npc")
        return f"创建了{len(new_chars)}个新角色：{', '.join(c['name'] for c in new_chars)}"
    except Exception as e:
        return f"角色生成跳过：{str(e)[:50]}"


def _check_story_end(protagonist, event_callback=None):
    """Check if story should end. Returns True if ended."""
    risk = get_risk()
    player = get_player_character()
    player_name = player.get("name", "主角") if player else "主角"

    # Check death
    if risk >= 90:
        died = check_death(risk, 0.3)  # High risk, low effective HP
        if died:
            if event_callback:
                event_callback(RoundEvent("story-end", {
                    "reason": "death",
                    "message": f"{player_name}在风险等级{risk}的情况下没有挺过去。故事到此为止。",
                    "round": protagonist.get("action_log", [{}])[-1].get("round", "?") if protagonist.get("action_log") else "?",
                }))
            return True

    # Check story-ending critical events from world engine
    world = read_json(config.STATE_DIR, "world.json")
    critical_events = world.get("global_events", {}).get("active", [])
    for evt in critical_events:
        if evt.get("story_ending"):
            if event_callback:
                event_callback(RoundEvent("story-end", {
                    "reason": "critical_event",
                    "message": f"世界事件「{evt.get('name', '未知')}」触发了故事的终结。{evt.get('description', '')}",
                }))
            return True

    return False
