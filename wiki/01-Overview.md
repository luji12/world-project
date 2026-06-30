# World Project — 项目概览

## 1. 项目定位

World Project 是一个本地运行的 AI 互动小说引擎。它围绕“世界会自行推演，玩家可以介入，最终生成可阅读小说”这个目标搭建。

它不是单一世界观项目。用户可以创建不同题材、不同主角、不同规则的世界；系统会为每个世界维护独立状态、记忆、关系、章节和导出内容。

## 2. 当前核心能力

- 多世界创建、切换、删除。
- Canon Engine：保存原始脚本，编译世界圣经、主线轨道、硬约束和冲突记录。
- 自动推演与玩家介入双模式。
- 剧情驱动的 NPC Agent 生命周期。
- 玩家视角群聊和私密 NPC 行动过滤。
- 长上下文包、事实账本、伏笔账本。
- 章节草稿、审核、润色、整书导出。
- 阅读器同款纸感 UI。

## 3. 架构图

```text
┌──────────────────────────────────────────────────────┐
│ Frontend: React + Vite                               │
│ Worlds | Canon | Dashboard | Play | Reader | ...      │
└───────────────────────┬──────────────────────────────┘
                        │ REST / SSE
┌───────────────────────▼──────────────────────────────┐
│ Backend: Python HTTP Server                           │
│ server.py                                             │
│ scheduler.py                                          │
│ canon_engine.py + canon_context.py + validator        │
│ npc_lifecycle.py + npc_orchestrator.py                │
│ agents/* + story_context.py                           │
│ story_ledger.py + memory_manager.py                   │
└───────────────────────┬──────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────┐
│ Local Persistence                                     │
│ worlds/<name>/state JSON                              │
│ chat_history.json                                     │
│ memory JSON + ChromaDB                                │
│ chronicle Markdown                                    │
│ story-ledger.sqlite3                                  │
└──────────────────────────────────────────────────────┘
```

## 4. 源码目录

```text
backend/
  agents/                 # Agent prompt 与调用
  memory/                 # ChromaDB 封装
  state/                  # JSON 状态与关系图谱
  tests/                  # 单元测试
  server.py               # API 入口
  scheduler.py            # 回合编排
  canon_engine.py         # Canon 文件编译
  canon_context.py        # Canon Packet 构建
  canon_validator.py      # Canon 校验与冲突记录
  canon_migration.py      # 旧世界备份重开
  npc_lifecycle.py        # NPC 生命周期
  npc_orchestrator.py     # NPC 推演
  story_context.py        # 长上下文
  story_ledger.py         # SQLite 账本
  book_compiler.py        # 小说导出

frontend/src/
  pages/                  # 业务页面
  components/             # 组件
  api.js                  # API + SSE
  chatEvents.js           # 事件转换
  worldCache.js           # 世界缓存清理

config/                   # 默认示例配置
system/                   # 默认任务/事件/技能模板
wiki/                     # 开发文档
```

## 5. 运行时目录

```text
worlds/<world-name>/
  world.json
  world-framework.md
  canon/
  chat_history.json
  state/
  memory/
  chronicle/
  npc-cards/
  story-ledger.sqlite3
  exports/
```

运行时目录会包含用户创作内容、模型输出、聊天记录和记忆，不进入公开仓库。

## 6. 回合生命周期

```text
读取当前世界
  → 构建 Canon Packet + 预算上下文包
  → 检查玩家行动是否越过当前主线门槛
  → 规划 NPC 生命周期
  → 执行 World Engine
  → 执行 System Agent
  → 自动主角或玩家行动进入回合
  → 执行活跃 NPC Agents
  → 过滤玩家不可见信息
  → Canon Validator 校验/轻修复/记录冲突
  → Chronicler 生成正文与账本更新
  → 写入事件历史并推送前端
```

## 7. 题材与模板

仓库中的 `config/` 和 `system/` 提供的是默认示例模板。创建世界时可以替换为其它题材、世界规则、主角设定和系统人格。
