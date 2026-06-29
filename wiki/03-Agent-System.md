# Agent 系统

## 1. 总览

当前版本的 Agent 系统由“核心 Agent + NPC 生命周期层 + 长上下文层”组成。Agent 不直接共享无限历史，而是通过 `story_context.py` 获取预算化上下文。

```text
World Engine
System Agent
Protagonist Agent / Player Action
NPC Lifecycle
NPC Agents
Chronicler
```

## 2. World Engine

文件：`backend/agents/world_engine.py`

职责：

- 推进时间、地点、环境、资源。
- 维护公开世界事件。
- 推演势力变化。
- 产出可被玩家感知的场景变化。

限制：

- 不替玩家做决定。
- 不直接泄露私密 NPC 行动。
- 输出必须被归一化后再进入调度器。

## 3. System Agent

文件：`backend/agents/system_agent.py`

职责：

- 根据世界状态和玩家行动生成任务。
- 更新奖励、成长、提示。
- 在玩家介入模式下作为角色可感知的信息源。

系统人格来自每个世界的 `config/system-personality.json`。默认模板可以是陪伴型系统，但项目不限定为该风格。

## 4. Protagonist Agent

文件：`backend/agents/protagonist.py`

职责：

- 自动推演模式下为主角选择行动。
- 玩家介入模式下不抢控制权，只读取玩家行动进入后续推演。

## 5. NPC Lifecycle

文件：`backend/npc_lifecycle.py`

职责：

- 根据剧情触发创建新 NPC。
- 激活与当前场景相关的 NPC Agent。
- 让离开剧情焦点的 NPC 退场。
- 保留所有历史档案、记忆、关系和伏笔。

生命周期状态：

| 状态 | 含义 |
| --- | --- |
| active | 当前参与推演窗口。 |
| dormant | 暂不推演，但可被剧情召回。 |
| retired | 已离开主要剧情，档案仍保留。 |
| dead | 死亡或不可再行动，记录仍保留。 |

## 6. NPC Agents

文件：`backend/npc_orchestrator.py`

每个活跃 NPC 的 prompt 应包含：

- 人设。
- 欲望。
- 秘密。
- 近期记忆。
- 与玩家/其他角色关系。
- 当前场景目标。
- 可见性要求。

NPC 输出需要标记：

- `visibility`
- `observed_by_player`
- `audience`
- `memory_note`
- `exposed_to_player`

可见行动进入群聊；私密行动只进入记忆和后续上下文。

## 7. Chronicler

文件：`backend/agents/chronicler.py`

职责：

- 把玩家可感知事件整理成小说正文。
- 写入章节草稿、事实、记忆、伏笔。
- 维护正文连续性和阅读体验。

Chronicler 不应该获得未经处理的私密 NPC 行动摘要，否则正文会泄露玩家不该知道的信息。

## 8. 输出稳定性

模型输出可能是 dict、list、string 或混合结构。调度层必须先使用归一化工具，再读取嵌套字段。重点字段包括：

- `triggered_events`
- `relationship_changes`
- `quest_updates`
- `rewards`
- `npc_actions`
- `memory_entries`
- `chapter_summary`

非预期结构进入 fallback，不应中断整轮推演。
