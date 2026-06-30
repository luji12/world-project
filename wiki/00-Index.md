# World Project Wiki — 索引

> 多世界、多 Agent、玩家可介入的互动小说推演系统。

## 文档目录

| 文档 | 内容 |
| --- | --- |
| [01-Overview](01-Overview.md) | 项目定位、当前架构、目录结构、核心工作流 |
| [02-Backend-Core](02-Backend-Core.md) | 后端 API、server.py、scheduler.py、config.py |
| [03-Agent-System](03-Agent-System.md) | World/System/Protagonist/NPC/Chronicler 与生命周期 |
| [04-Supporting-Modules](04-Supporting-Modules.md) | 记忆、账本、NPC、风险、文笔、导入导出等支撑模块 |
| [05-Frontend](05-Frontend.md) | React 路由、页面、SSE、纸感 UI |
| [06-Data-Layer](06-Data-Layer.md) | 世界目录、状态 JSON、聊天历史、记忆、Story Ledger |
| [07-Running-Guide](07-Running-Guide.md) | 安装、启动、测试、发布前检查 |

## 快速导航

- **推演引擎**：`backend/scheduler.py` → `backend/agents/*` → `backend/story_context.py`
- **Canon 约束**：`backend/canon_engine.py` → `backend/canon_context.py` → `backend/canon_validator.py` → `frontend/src/pages/Canon.jsx`
- **玩家介入**：`frontend/src/pages/Play.jsx` → `/api/interact/start` → 统一事件历史
- **自动推演**：`frontend/src/pages/Dashboard.jsx` → `/api/auto/start`
- **NPC 生命周期**：`backend/npc_lifecycle.py` → `backend/npc_orchestrator.py`
- **玩家视角过滤**：`backend/npc_orchestrator.py` + `frontend/src/chatEvents.js`
- **长期记忆**：`backend/memory_manager.py` + `backend/memory/chroma_store.py`
- **叙事账本**：`backend/story_ledger.py` + `backend/book_compiler.py`
- **世界管理**：`frontend/src/pages/WorldPanel.jsx` + `/api/worlds/*`

## 当前数据流

```text
玩家行动 / 自动推演
  → Canon Packet / 主线阶段门槛
  → scheduler 规划回合
  → NPC 生命周期生成/激活/退场
  → World/System/Protagonist/NPC/Chronicler 协作
  → 统一事件历史 chat_history.json
  → state JSON + memory + Story Ledger
  → Play / Dashboard / Reader 同步展示
```

## 公开仓库注意事项

公开仓库只包含源码、测试、文档和模板。以下内容属于本地运行数据，不应进入 GitHub：

- `worlds/`
- `state/`
- `memory/`
- `chronicle/`
- `npc-cards/`
- `chat_history.json`
- `story-ledger.sqlite3`
- `chroma_db/`
- `.env*`
- `frontend/dist/`
- `node_modules/`

## 版本说明

当前公开版已经从“固定玄幻世界 Demo”升级为“通用多世界互动小说引擎”。仓库内的东方玄幻配置是示例模板，不代表系统只能运行该题材。
