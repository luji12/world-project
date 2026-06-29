# World Project Code Wiki

> 当前版本：多世界、多 Agent、玩家可介入的互动小说推演工程。  
> 旧的“玄幻固定世界”只是默认示例配置，不再代表项目边界。

## 1. 项目定位

World Project 是一个本地运行的 AI 叙事系统。它把“世界推演”“玩家行动”“NPC 自主行为”“长期记忆”“小说正文整理”拆成多个协作模块，并通过 React 前端提供可玩的工作台、群聊、阅读器和记忆/关系探查界面。

最重要的当前特性：

- 多世界书架与独立世界目录。
- 自动推演和玩家介入共用同一事件历史。
- NPC Agent 随剧情生成、激活、退场和归档。
- 群聊只展示主角可感知信息。
- Story Ledger 管理事实、伏笔、章节和检查点。
- 长上下文包服务 world/system/protagonist/chronicler。
- 阅读器和主要页面使用统一纸感 UI。

## 2. 目录导览

```text
world-project/
├── backend/
│   ├── server.py             # HTTP/SSE API 入口
│   ├── scheduler.py          # 自动/交互式回合编排
│   ├── npc_lifecycle.py      # NPC Agent 生命周期规划
│   ├── npc_orchestrator.py   # NPC 行动推演、可见性过滤、记忆写入
│   ├── story_context.py      # 长上下文预算包构建
│   ├── story_ledger.py       # SQLite 事实/伏笔/章节/检查点账本
│   ├── book_compiler.py      # 小说编译导出
│   ├── memory_manager.py     # 角色记忆管理
│   ├── state/                # JSON 状态读写与关系图谱
│   ├── memory/               # ChromaDB 封装
│   ├── agents/               # LLM Agent prompt 和调用
│   └── tests/                # 回归测试
├── frontend/
│   ├── src/App.jsx           # 路由、世界上下文、布局守卫
│   ├── src/api.js            # REST + SSE 客户端
│   ├── src/chatEvents.js     # 后端事件到前端消息/叙事条目的统一转换
│   ├── src/worldCache.js     # 世界级 localStorage 缓存清理
│   ├── src/components/       # Sidebar / UI / Atelier
│   └── src/pages/            # Dashboard / Play / Reader / Relations / Memory 等
├── config/                   # 默认示例配置，会复制到新世界
├── system/                   # 默认事件/任务/技能模板
├── wiki/                     # 拆分后的开发文档
└── README.md / DESIGN.md     # 对外说明与架构设计
```

运行时目录：

```text
worlds/<world-name>/
├── world.json
├── world-framework.md
├── chat_history.json
├── state/*.json
├── memory/*.json
├── memory/chroma_db/
├── chronicle/*.md
├── npc-cards/**/*
├── story-ledger.sqlite3
└── exports/
```

运行数据不属于公开仓库。

## 3. 后端核心

### `backend/server.py`

负责：

- 静态文件和 API 路由。
- SSE 流式响应。
- 世界创建/切换/删除。
- 聊天历史读取/清理。
- 章节、正文、导出、存档 API。

关键接口：

- `/api/status`
- `/api/worlds`
- `/api/worlds/create-v2`
- `/api/worlds/delete`
- `/api/auto/start`
- `/api/interact/start`
- `/api/chat/history`
- `/api/memory`
- `/api/story/context`
- `/api/chapters`
- `/api/book/compile`

### `backend/scheduler.py`

回合调度核心。它把自动推演和玩家介入统一成事件流：

1. 读取当前世界与上下文。
2. 规划 NPC 生命周期。
3. 执行世界、系统、主角/NPC、记录员。
4. 将输出归一化，避免模型返回 list/string 时崩溃。
5. 写入状态、记忆、账本和聊天历史。
6. 通过 SSE 返回前端。

### `backend/npc_lifecycle.py`

当前 NPC Agent 生命周期层：

- `spawn`：剧情需要新角色。
- `activate`：角色进入当前活跃推演窗口。
- `retire`：角色离开当前场景。
- `archive`：角色不再活跃但档案和记忆保留。

### `backend/npc_orchestrator.py`

负责活跃 NPC 推演与可见性处理：

- `direct`
- `overheard`
- `public_observed`
- `private`
- `secret`
- `internal`
- `background`

只有玩家可感知行动会进入群聊；私密行动继续写入角色记忆和后续推演上下文。

### `backend/story_context.py`

构建预算化上下文包，避免超长对话后直接丢关键线索。优先级是：

1. 玩家最近行动。
2. 当前世界状态。
3. 未回收伏笔。
4. 已确认事实。
5. 角色重要记忆。
6. 压缩摘要。
7. 最近事件窗口。

### `backend/story_ledger.py`

SQLite 账本用于保存比 JSON 更可靠的叙事证据链：

- events
- facts
- foreshadows
- chapter revisions
- checkpoints
- compiled book metadata

## 4. Agent 层

| 文件 | 责任 |
| --- | --- |
| `agents/base.py` | LLM 调用、流式解析、JSON 归一化、异常结构 fallback。 |
| `agents/world_engine.py` | 世界状态、公开事件、势力、环境变化。 |
| `agents/system_agent.py` | 任务、奖励、系统提示、玩家成长。 |
| `agents/protagonist.py` | 自动模式主角行动；玩家介入模式下让位。 |
| `agents/chronicler.py` | 小说正文、记忆条目、事实、伏笔、章节建议。 |

重要约束：

- Agent 输出必须经过归一化再 `.get()`。
- Chronicler 只接收玩家可感知摘要和账本上下文，避免正文泄露私密 NPC 行动。
- NPC 行动要带可见性字段，否则前端和后端都做保守过滤。

## 5. 前端核心

| 文件 | 责任 |
| --- | --- |
| `src/App.jsx` | 全局布局、当前世界状态、路由守卫。 |
| `src/api.js` | HTTP 请求、SSE 客户端、模型配置 header。 |
| `src/chatEvents.js` | 后端事件转 Play 消息和 Dashboard 叙事流。 |
| `src/worldCache.js` | 删除世界后清理该世界 localStorage 缓存。 |
| `src/pages/Dashboard.jsx` | 上帝工作台：自动推演、玩家行动、世界干预。 |
| `src/pages/Play.jsx` | 玩家视角群聊，底部输入固定。 |
| `src/pages/Reader.jsx` | 小说阅读器和故事线索侧栏。 |
| `src/pages/Relations.jsx` | 关系图谱与 NPC 档案/记忆探查。 |
| `src/pages/Memory.jsx` | 记忆浏览。 |
| `src/pages/WorldPanel.jsx` | 世界书架、创建、切换、删除。 |

UI 规范：

- 全局纸感：米白底、墨色文字、朱砂强调。
- 长列表独立滚动。
- 高频操作固定可见。
- 群聊不是彩色 IM，而是玩家视角叙事流。

## 6. 数据策略

### 公开仓库

只保存：

- 源码。
- 测试。
- 文档。
- 安全默认模板。

### 本地运行

保存：

- 真实世界目录。
- 聊天历史。
- 角色记忆。
- SQLite 账本。
- ChromaDB 向量库。
- 编译导出。

这些内容默认被 `.gitignore` 排除。

## 7. 常用验证

后端：

```bash
cd backend
python3 -m unittest discover -s tests -v
```

前端：

```bash
cd frontend
npm run build
```

公开发布前：

```bash
rg -n --hidden "(sk-|ghp_|github_pat_|Bearer |apiKey|password|token|secret)" .
```

## 8. 文档入口

- `README.md`：面向用户和 GitHub 访客。
- `DESIGN.md`：架构与设计原则。
- `wiki/00-Index.md`：详细开发文档入口。
