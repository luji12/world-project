# Frontend 前端架构

## 概述

React 18 + Vite + Tailwind CSS 单页应用，通过 SSE (Server-Sent Events) 与后端实时通信。

- **路由**: React Router v6
- **可视化**: D3.js (关系图)
- **图标**: Lucide React
- **样式**: Tailwind CSS + 自定义 Atelier 设计系统

## 项目结构

```
frontend/
├── index.html              # 入口 HTML
├── src/
│   ├── main.jsx            # React 挂载点
│   ├── App.jsx             # 根组件 + 路由 + WorldContext
│   ├── api.js              # API 客户端 + SSE 流处理
│   ├── SettingsContext.jsx  # 全局设置 Context
│   ├── autoConfig.js       # 自动推演配置管理
│   ├── index.css           # Tailwind + 全局样式
│   ├── components/
│   │   ├── Sidebar.jsx     # 侧边导航栏
│   │   ├── Atelier.jsx     # Atelier 工作区通用组件
│   │   └── UI.jsx          # 通用 UI 组件 (Button, Input, Card 等)
│   └── pages/
│       ├── Dashboard.jsx   # 工作台首页
│       ├── Canon.jsx       # 世界圣经 / 原始脚本 / 约束冲突
│       ├── Play.jsx        # 交互式游玩
│       ├── Reader.jsx      # 叙事阅读器
│       ├── Manager.jsx     # 世界管理器
│       ├── Relations.jsx   # D3.js 关系图谱
│       ├── Memory.jsx      # 三层记忆浏览
│       ├── AutoConfig.jsx  # 自动推演配置
│       ├── WorldPanel.jsx  # 世界管理面板
│       └── Settings.jsx    # 模型配置
└── dist/                    # Vite 构建产物
```

---

## 路由表

| 路径 | 页面组件 | 说明 |
|------|----------|------|
| `/` | `Dashboard` | 工作台 + 自动推演控制 + 最近叙事 |
| `/play` | `Play` | 交互式游玩 (输入行动 → 观看推演) |
| `/canon` | `Canon` | 世界圣经、主线轨道、约束冲突、重编译/重开 |
| `/reader/:volume` | `Reader` | Markdown 叙事阅读 |
| `/reader` | `Reader` | 默认阅读器 (重定向到最新卷) |
| `/manager` | `Manager` | 世界状态、NPC、任务、手动推演 SSE |
| `/relations` | `Relations` | D3 力导向关系图 |
| `/memory` | `Memory` | 三层记忆浏览 + 遗忘曲线 |
| `/auto-config` | `AutoConfig` | 停止条件 + 干预节点配置 |
| `/worlds` | `WorldPanel` | 世界管理面板 (创建/切换/删除/导入) |
| `/settings` | `Settings` | 模型配置 (API Key、Base URL、Model) |

---

## 关键组件

### App.jsx (根组件)

**文件**: `frontend/src/App.jsx:1-149`

#### `WorldContext` (line 19)
```jsx
export const WorldContext = createContext({
  hasWorld: false,
  currentWorld: '',
  refresh: () => {}
})
```
全局世界状态 Context，所有页面通过 `useWorld()` 获取当前是否有活跃世界。

#### `AppShell` 组件 (line 32)
- 管理全局 UI 状态：导航开关、运行状态、进度
- 启动时调用 `fetchStatus()` 检查是否有世界
- 无世界时自动重定向到 `/worlds`
- 未就绪时显示加载动画

#### 条件渲染逻辑 (line 123-141)
```jsx
{hasWorld ? <Dashboard ... /> : <Navigate to="/worlds" replace />}
```
所有功能页面都需要 `hasWorld === true`，否则重定向。

---

### api.js — API 客户端

**文件**: `frontend/src/api.js:1-262`

#### 基础配置
- `BASE` = `VITE_API_BASE` 或 `http://localhost:3101`
- `getHeaders()` — 从 localStorage 读取 API Key / Base URL / Model 并注入请求头

#### REST API 封装
`apiJson(path, options, fallback)` + `postJson(path, body, options, fallback)` 统一错误处理。

#### SSE 流处理 (`streamSSE`, line 238)
```javascript
async function streamSSE(res, onEvent) {
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  // 逐行解析 event: <type>\ndata: <json>
  // 调用 onEvent({ event, data })
}
```

#### 关键 API 函数

| 函数 | 对应端点 |
|------|----------|
| `startRound(onEvent)` | `POST /api/round/start` |
| `startAuto(stopConditions, interventionNodes, interactiveMode, onEvent)` | `POST /api/auto/start` |
| `startInteractive(protagonistAction, onEvent)` | `POST /api/interact/start` |
| `pauseAuto()` / `resumeAuto()` | `POST /api/auto/pause` / `resume` |
| `createWorld(name, summary, type)` | `POST /api/worlds/create` |
| `createWorldV2(name, worldPackage, selectedCharacter)` | `POST /api/worlds/create-v2` |
| `chatWorld(messages)` | `POST /api/worlds/chat` |
| `uploadDocument(file)` | `POST /api/worlds/upload-doc` (multipart) |
| `fetchCanonStatus()` | `GET /api/canon/status` |
| `fetchCanonBible()` | `GET /api/canon/bible` |
| `recompileCanon()` | `POST /api/canon/recompile` |
| `resetCanonWorld()` | `POST /api/canon/reset-world` |
| `polishAction(text, context)` | `POST /api/polish` |
| `fetchState(filename)` | `GET /api/state/{file}` |
| `fetchChronicle(volume)` | `GET /api/chronicle/{volume}` |
| `fetchMemory(type, charId)` | `GET /api/memory` |
| `approveChapter(chapterNo, revisionNo)` | `POST /api/chapters/approve` |
| `compileBook(title)` | `POST /api/book/compile` |

---

### SettingsContext.jsx — 全局设置

**文件**: `frontend/src/SettingsContext.jsx`

管理 `world-project-settings` localStorage 键，并兼容读取旧版 `xuanhuang-settings`：
- `apiKey` — DeepSeek API Key
- `baseUrl` — API Base URL
- `model` — 模型选择

---

### 页面组件概要

#### Dashboard.jsx
自动推演核心控制界面。顶部控制栏：[暂停] [继续] + 进度条 + 当前轮次/时间/修为 + 最近事件流。右侧展示当前 Canon 阶段、起始地区和开放冲突数。

#### Canon.jsx
世界圣经面板。展示 `source.md`、结构化世界圣经、当前主线阶段、必达里程碑、硬约束和冲突列表，并提供重新编译与按 Canon 备份重开的操作。

#### Play.jsx
交互式游玩入口。输入主角行动 → 提交推演 (`startInteractive`) → SSE 流式展示推演过程。顶部显示当前 Canon 主线阶段；若行动越过阶段门槛，会显示 Canon gate 的原因。

#### Reader.jsx
Markdown 叙事阅读器。支持分卷切换。加载 `chronicle/volume-XX.md` 渲染。

#### Manager.jsx
世界管理仪表盘：手动推演 SSE 进度条 + 5 个 Agent 执行状态实时展示 + 角色列表 + 任务列表。

#### Relations.jsx
D3 力导向关系图。可视化角色、势力、地点之间的关系网络。

#### Memory.jsx
三层记忆浏览：Recent (近期)、Compressed (压缩)、Milestones (里程碑)。支持遗忘曲线可视化。

#### WorldPanel.jsx
世界管理面板。支持三种创建方式：
1. **快速创建** — 输入名称和摘要
2. **对话创建** — 与 AI 世界架构师对话构建 (7 阶段引导)
3. **文档导入** — 上传小说/设定集自动提取世界

#### Settings.jsx
模型配置：API Key、Base URL、Model 选择。存储在 localStorage 中。

---

## UI 设计系统

### Atelier 设计风格
暖色纸质风格，灵感来自印刷工作室：
- 背景: `#f7f3eb` (暖白纸色)
- 文字: `#2f2b25` (深棕黑)
- 主色: `#a94334` (朱砂红)
- 边框: `#d6ccba` (浅驼色)
- 字体: `font-serif` (正文) / `font-sans` (界面)

### UI 组件 (`components/UI.jsx`)
- `Button` — 支持 `tone` (primary/secondary/ghost/danger) 和 `size` 变体
- `Input`, `Textarea`, `Select`
- `Card`, `Badge`, `Spinner`, `Progress`
- `Tabs`, `Modal`, `Toast`
