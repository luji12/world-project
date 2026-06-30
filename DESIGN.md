# World Project — 当前架构设计

## 设计目标

World Project 的目标是构建一个可长期运行的互动小说世界引擎：

- 世界可以自动推演，也可以被玩家随时介入。
- NPC 不是固定列表，而是随剧情生成、激活、退场和归档。
- 用户脚本不是一次性摘要，而是永久 Canon：原文、世界圣经、主线轨道、硬约束和冲突记录会持续约束推演。
- 聊天页遵守玩家视角，不主动暴露背地事件和心理活动。
- 长篇推演需要记住事实、伏笔、关系和关键选择。
- 推演结果最终能整理成“去 AI 味”的完整小说阅读体验。

## 系统分层

```text
React 前端
  ├─ Worlds：世界书架与创建
  ├─ Canon：世界圣经 / 原始脚本 / 主线轨道 / 冲突
  ├─ Dashboard：上帝工作台 / 自动推演
  ├─ Play：玩家介入群聊
  ├─ Reader：小说阅读器
  ├─ Relations / Memory：关系与记忆探查
  └─ Settings / AutoConfig：模型与自动推演配置
        │
        │ REST + SSE
        ▼
Python 后端
  ├─ server.py：HTTP API 与 SSE 入口
  ├─ scheduler.py：回合调度
  ├─ npc_lifecycle.py：NPC Agent 生命周期
  ├─ npc_orchestrator.py：NPC 推演与可见性过滤
  ├─ canon_engine.py：Canon 文件编译与世界初始化
  ├─ canon_context.py：Canon Packet 构建
  ├─ canon_validator.py：玩家行动和 Agent 输出校验
  ├─ canon_migration.py：旧世界备份与按 Canon 重开
  ├─ agents/：World / System / Protagonist / Chronicler
  ├─ story_context.py：预算化长上下文包
  ├─ story_ledger.py：事实、伏笔、章节、检查点账本
  ├─ memory_manager.py：角色记忆生命周期
  └─ book_compiler.py：小说编译导出
        │
        ▼
本地持久化
  ├─ worlds/<name>/state/*.json
  ├─ worlds/<name>/canon/*.json + source.md
  ├─ worlds/<name>/chat_history.json
  ├─ worlds/<name>/memory/*.json + chroma_db/
  ├─ worlds/<name>/chronicle/*.md
  └─ worlds/<name>/story-ledger.sqlite3
```

## 核心推演流程

所有推演入口都会先构建 Canon Packet。上下文优先级固定为：

```text
Canon 硬约束
→ 当前主线阶段
→ 玩家最近行动
→ 当前世界状态
→ 未回收伏笔 / 已确认事实
→ 角色记忆
→ 聊天摘要 / 最近消息
```

### 自动推演

```text
POST /api/auto/start
  → round-start
  → 构建 Canon Packet
  → NPC Lifecycle 规划生成/激活/退场
  → World Engine 推进世界公开状态
  → System Agent 生成任务/奖励/提示
  → Protagonist Agent 自动行动
  → NPC Agents 推演活跃 NPC
  → 可见性过滤：只把玩家可感知信息发到聊天流
  → Canon Validator 轻修复或记录冲突
  → Chronicler 生成正文与记忆/伏笔/事实沉淀
  → round-complete
```

### 玩家介入

```text
POST /api/interact/start { action }
  → Canon Gate 检查玩家行动是否越过主线阶段门槛
  → 玩家行动写入统一事件历史
  → 当前玩家角色替代 Protagonist Agent
  → 后续世界、系统、NPC、记录员根据玩家行动继续推演
  → Play 页面实时显示玩家可见事件
```

## Canon / 世界圣经

每个世界拥有独立 Canon 目录：

```text
worlds/<name>/canon/
├── source.md
├── world_bible.json
├── story_arcs.json
├── constraints.json
├── source_map.json
├── conflicts.json
└── canon_version.json
```

Canon 采用“轨道式自由”：起始地点、核心势力、力量体系、阶段门槛和必达里程碑是硬轨道；玩家的解决方式、支线遭遇、非关键 NPC 日常允许自由变化。旧世界如无 Canon，可在前端“世界圣经”页先备份到 `worlds/_archives/`，再重建 state、记忆、聊天和账本。

## NPC Agent 生命周期

当前版本不再使用“每隔几轮补 NPC”的固定策略，而是剧情驱动：

- **spawn**：进入新地点、询问陌生人、任务需要配角、关系链引出人物时创建角色档案。
- **activate**：角色与当前场景、玩家行动、世界事件或关系网络强相关时进入活跃窗口。
- **retire**：角色离开当前剧情后从活跃 Agent 注册表移除。
- **archive**：档案、记忆、关系、事件和伏笔永久保留，后续可被剧情召回。

活跃 Agent 只代表“当前需要参与推演的角色”，不是历史 NPC 总量上限。

## 玩家视角规则

聊天页不是上帝视角，只显示：

- 主角直接听到的对话。
- 主角可观察到的动作。
- 场景中公开发生的事件。
- 系统明确告诉主角的信息。
- 记录员基于玩家可感知事件整理出的正文片段。

以下内容不主动显示在聊天页：

- NPC 私密行动。
- 远处角色的自言自语。
- 背地密谋。
- 纯心理活动。
- 还没有被主角发现的线索。

隐藏事件仍然进入 NPC 记忆、关系档案、Story Ledger 和后续推演上下文。

## 长上下文策略

每个 Agent 获得的是预算化上下文包，而不是无限拼接历史：

1. Canon 硬约束与当前主线阶段。
2. 玩家最近行动。
3. 当前世界状态。
4. 未回收伏笔。
5. 已确认事实。
6. 角色重要记忆。
7. 聊天滚动摘要。
8. 最近事件窗口。

Chronicler 必带 Story Ledger 的 facts、open foreshadows 和 recent events，避免正文忘记已确认事实。

## 前端交互与视觉

当前 UI 采用“阅读器纸感”作为全局视觉基调：

- 米白纸面背景。
- 墨色正文。
- 朱砂点缀。
- 细边框与低饱和层级。
- 关键操作固定可见。

布局原则：

- Dashboard：顶部状态固定，中间叙事流独立滚动，底部玩家行动/世界干预固定。
- Play：顶部角色状态固定，消息区独立滚动，底部输入区固定。
- Reader：以沉浸式阅读为主，故事线索在侧栏辅助而不抢正文。

## API 摘要

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/status` | 当前世界、自动推演和模型状态 |
| GET | `/api/canon/status` | Canon 是否存在、当前阶段和冲突数 |
| GET | `/api/canon/source` | 当前世界原始脚本 |
| GET | `/api/canon/bible` | 世界圣经、主线轨道和约束摘要 |
| POST | `/api/canon/recompile` | 从原文或传入文本重新编译 Canon |
| POST | `/api/canon/reset-world` | 备份并按 Canon 强制重开当前世界 |
| GET | `/api/canon/conflicts` | Canon 冲突列表 |
| POST | `/api/canon/conflicts/resolve` | 标记冲突处理状态 |
| GET | `/api/worlds` | 世界列表 |
| POST | `/api/worlds/create-v2` | 创建世界 |
| POST | `/api/worlds/delete` | 删除世界并清理当前世界指针 |
| GET | `/api/chat/history` | 统一事件历史 |
| POST | `/api/chat/history/clear` | 清空聊天历史 |
| POST | `/api/auto/start` | 自动推演 SSE |
| POST | `/api/interact/start` | 玩家行动推演 SSE |
| GET | `/api/memory` | 记忆和关系数据 |
| GET | `/api/story/context` | 长上下文/叙事上下文 |
| GET | `/api/chapters` | 章节草稿与审核 |
| POST | `/api/book/compile` | 编译小说 |

## 公开发布策略

公开仓库只包含源码、测试、文档和安全模板。以下内容必须留在本地：

- `worlds/`
- 根目录运行态 `state/`、`memory/`、`chronicle/`、`npc-cards/`
- `chat_history.json`
- `story-ledger.sqlite3`
- `chroma_db/`
- `.env*`
- `frontend/dist/`
- `node_modules/`
