# 数据层与持久化

## 1. 公开源码 vs 本地运行数据

公开仓库只保存源码、测试、文档和模板。本地运行后生成的世界数据包含用户剧情、聊天记录、模型输出和记忆，默认不上传。

## 2. 世界目录

```text
worlds/<world-name>/
├── world.json                    # 世界元信息
├── world-framework.md            # 世界设定文档
├── canon/                        # 原始脚本、世界圣经、主线轨道、约束与冲突
│   ├── source.md
│   ├── world_bible.json
│   ├── story_arcs.json
│   ├── constraints.json
│   ├── source_map.json
│   ├── conflicts.json
│   └── canon_version.json
├── chat_history.json             # 统一事件历史
├── story-ledger.sqlite3          # 事实/伏笔/章节/检查点账本
├── state/
│   ├── world.json                # 世界运行态
│   ├── protagonist.json          # 玩家/主角状态
│   ├── characters.json           # 全部角色档案索引
│   ├── npc_agents.json           # 当前活跃 NPC Agent 注册表
│   ├── quests.json               # 任务状态
│   ├── relationships.json        # 关系图谱
│   └── _pending_injections.json  # 世界干预队列
├── memory/
│   ├── index.json                # 记忆索引
│   ├── <char-id>.json            # 每个角色的记忆
│   └── chroma_db/                # 向量检索库
├── chronicle/
│   ├── volume-XX.md              # 分卷正文
│   ├── timeline.md               # 时间线
│   ├── rounds-log.json           # 最近轮次日志
│   └── round-NNNN.json           # 单轮详细记录
├── npc-cards/                    # NPC 详细档案
├── config/                       # 世界级配置
├── system/                       # 世界级事件/任务/技能模板
└── exports/                      # 小说导出
```

## 3. `chat_history.json`

聊天历史是自动推演和玩家介入的统一事件源。事件项保持兼容，但会尽量规范化为：

```json
{
  "type": "npc-message",
  "round": 12,
  "ts": 1780000000000,
  "source": "npc-agent",
  "actor": "角色名",
  "text": "玩家可见内容",
  "data": {
    "npc_id": "npc-id",
    "visibility": "direct",
    "observed_by_player": true,
    "exposed_to_player": true
  }
}
```

私密事件可以进入 round log、记忆和账本，但不应作为群聊消息渲染。

`canon-violation` 和 `canon-conflict` 事件也会进入历史流，用于向玩家解释阶段门槛拦截或设定轻修复。

## 4. `canon/`

Canon 是所有推演的最高优先级设定来源：

| 文件 | 用途 |
| --- | --- |
| `source.md` | 用户导入或对话创建时保留下来的完整原始脚本。 |
| `world_bible.json` | 世界名、起始地区、地理、势力、角色、力量体系和世界法则。 |
| `story_arcs.json` | 主线阶段、阶段顺序、进入/退出条件、必达/可选里程碑。 |
| `constraints.json` | 硬约束、软约束、阶段门槛、禁行事件、可自由推演区。 |
| `source_map.json` | Canon 设定来源、原文 hash、编译时间。 |
| `conflicts.json` | 推演输出或玩家行动造成的 Canon 冲突记录。 |

旧世界按 Canon 重开前会先备份到 `worlds/_archives/<world>-pre-canon-<timestamp>/`。

## 5. `characters.json`

角色库保存所有历史角色，不只保存当前活跃角色。

```json
{
  "characters": [
    {
      "id": "npc-id",
      "name": "角色名",
      "role": "场景身份",
      "agent_status": "active",
      "spawn_round": 1,
      "last_active_round": 3,
      "exit_reason": "",
      "current_goal": "当前目标",
      "story_importance": 5,
      "player_controlled": false
    }
  ]
}
```

## 6. `npc_agents.json`

活跃 Agent 注册表只保存当前推演窗口，不是角色总表。

```json
{
  "agents": [
    {
      "npc_id": "npc-id",
      "role_in_scene": "掌柜",
      "activation_reason": "玩家进入客栈并询问消息",
      "scene_goal": "试探玩家意图",
      "visibility_scope": "direct",
      "last_tick_round": 8
    }
  ]
}
```

## 7. 记忆系统

每个角色都有独立记忆文件：

```json
{
  "char_id": "npc-id",
  "char_name": "角色名",
  "recent": [],
  "compressed": [],
  "milestones": [],
  "relationships": {}
}
```

记忆分层：

| 层级 | 用途 |
| --- | --- |
| recent | 最近完整事件窗口。 |
| compressed | 滚动摘要，降低上下文成本。 |
| milestones | 长期关键事件、秘密、承诺、伏笔。 |

## 8. Story Ledger

`story-ledger.sqlite3` 是长篇推演的事实来源，主要保存：

- events：事件流。
- facts：已确认事实。
- foreshadows：未回收/已回收伏笔。
- chapter revisions：章节草稿与审核状态。
- checkpoints：检查点。

Chronicler 和上下文构建层都会读取账本，避免长篇剧情忘记旧决定。

## 9. 删除世界

删除当前世界时：

1. 后端删除目标世界目录。
2. 清空 `_current`。
3. 前端清理该世界 localStorage 缓存。
4. 功能页回到 `/worlds`。
5. 不自动切换到其他世界。

删除非当前世界时，不影响当前世界。

## 10. 公开发布忽略项

必须忽略：

```text
/worlds/
/state/
/memory/
/chronicle/
/npc-cards/
/chroma_db/
/story-ledger.sqlite3
*.sqlite3
/chat_history.json
/_pending_injections.json
.env*
frontend/dist/
node_modules/
```
