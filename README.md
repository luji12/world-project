# World Project — 多 Agent 世界推演与互动小说引擎

World Project 是一个面向长篇互动叙事的本地 Web 工程。它不是固定世界观的小说模板，而是一套可以创建多个世界、让 AI Agent 持续推演剧情、允许玩家介入行动，并把推演结果整理成可阅读小说的系统。

当前版本的目标是：让用户不只是“读”故事，而是“住”进一个会自行演化的世界里。

## 当前版本能力

- **多世界书架**：创建、切换、删除多个独立世界；删除当前世界后不会自动串到其他世界。
- **世界创建流程**：支持从文本设定、文档导入、AI 细化设定、角色代入等路径创建世界。
- **双模式推演**：
  - 自动推演：由世界、系统、主角、NPC、记录员协作推进剧情。
  - 玩家介入：玩家控制指定角色行动，后续剧情根据行动实时推演。
- **剧情驱动 NPC Agent 生命周期**：根据场景和剧情需要生成/激活 NPC Agent；退场后注销活跃 Agent，但角色档案、关系、记忆和事件记录继续保留。
- **玩家视角群聊**：聊天页只展示主角可感知的 NPC 对话/行动；私密行动进入记忆和关系档案，不主动剧透。
- **长期记忆与伏笔管理**：通过 Story Ledger、角色记忆、事实账本、未回收伏笔和滚动上下文包降低长篇推演遗忘。
- **小说阅读器**：将推演出的正文整理为阅读体验更接近成书的界面，使用纸感排版、章节导航和故事线索侧栏。
- **小说整理与导出**：支持章节草稿、章节审核、正文润色、整书编译与 HTML/Markdown 导出。
- **统一事件历史**：自动推演、玩家行动、NPC 消息、系统消息、正文卡片统一进入同一聊天/事件历史。

## 核心 Agent

| Agent | 责任 |
| --- | --- |
| World Engine | 推进世界时间、环境、势力、资源、公开事件和场景状态。 |
| System Agent | 依据世界状态生成任务、奖励、系统提示和主角成长变化。 |
| Protagonist Agent | 自动模式下扮演主角行动；玩家介入模式下让位给玩家输入。 |
| NPC Lifecycle | 根据剧情决定 NPC 的生成、激活、退场与归档。 |
| NPC Agents | 扮演当前活跃、剧情相关的 NPC，输出可见/私密行动。 |
| Chronicler | 将本轮可感知事件整理成小说正文，并沉淀事实、记忆、伏笔。 |

## 项目结构

公开仓库只保留源码、测试、文档和安全模板；真实运行世界、聊天记录、记忆库、SQLite 账本和构建产物不会上传。

```text
world-project/
├── backend/                  # Python 后端：API、Agent 调度、记忆、账本、导出
│   ├── agents/               # world/system/protagonist/chronicler 等 Agent
│   ├── memory/               # ChromaDB 语义记忆封装
│   ├── state/                # JSON 状态读写与关系图谱
│   ├── tests/                # 后端单元测试
│   ├── npc_lifecycle.py      # NPC Agent 生命周期规划
│   ├── npc_orchestrator.py   # NPC 推演与可见性过滤
│   ├── scheduler.py          # 单轮/自动/玩家介入推演编排
│   ├── server.py             # HTTP + SSE API 入口
│   └── story_ledger.py       # SQLite 叙事账本
├── frontend/                 # React + Vite 前端
│   └── src/
│       ├── pages/            # Dashboard / Play / Reader / Relations / Memory 等页面
│       ├── components/       # 纸感 UI 组件与导航
│       ├── api.js            # REST + SSE 客户端
│       └── chatEvents.js     # 统一事件转消息逻辑
├── config/                   # 默认示例配置，可被每个世界覆盖
├── system/                   # 任务、事件、技能模板
├── wiki/                     # 开发文档
├── DESIGN.md                 # 架构设计
└── CODE_WIKI.md              # 代码导览
```

运行后会在本地生成：

```text
worlds/<world-name>/
├── state/                    # 世界、角色、任务、关系等运行态
├── memory/                   # 角色记忆与向量库
├── chronicle/                # 分卷正文、时间线、轮次日志
├── npc-cards/                # NPC 档案
├── story-ledger.sqlite3      # 事实、伏笔、章节、事件总账
└── exports/                  # 小说导出文件
```

这些运行数据默认被 `.gitignore` 排除。

## 快速启动

后端：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 server.py
```

前端：

```bash
cd frontend
npm install
npm run dev
```

默认访问：

- 前端：`http://127.0.0.1:3100`
- 后端：`http://127.0.0.1:3101`

## 模型配置

在应用内的“模型配置”页面填写 API Key、Base URL 和模型名称。不要把 `.env`、真实 API Key、运行世界目录、聊天记录或数据库提交到公开仓库。

## 验证

```bash
cd backend
python3 -m unittest discover -s tests -v

cd ../frontend
npm run build
```

## 文档

- [DESIGN.md](DESIGN.md)：当前架构、数据流和 UI 设计说明。
- [CODE_WIKI.md](CODE_WIKI.md)：代码模块导览。
- [wiki/](wiki/)：按后端、Agent、前端、数据层和运行指南拆分的开发文档。

## 当前状态

当前公开版是一个可运行的本地工程骨架，重点已经从“单一玄幻世界模板”升级为“通用多世界互动小说引擎”。仓库中的玄幻设定仅作为默认示例配置，用户可以创建任意风格的新世界并让推演系统接管后续剧情。
