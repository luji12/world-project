# Backend 核心模块

## 1. server.py — HTTP API 服务

**文件**: `backend/server.py:1-1693`
**类**: `ThreadingHTTPServer`, `AppHandler`
**端口**: `3101`

### 概述

基于 Python 标准库 `http.server` 的自定义 HTTP 服务器。支持 CORS、SSE 流、文件上传、多世界管理。

### 关键类

#### `ThreadingHTTPServer` (line 18)
```
继承: ThreadingMixIn + HTTPServer
```
多线程 HTTP 服务器，每个请求在独立线程中处理。

#### `AppHandler` (line 67)
```
继承: BaseHTTPRequestHandler
```
核心请求处理器，包含所有 API 路由逻辑。

### API 端点一览

| 方法 | 路径 | 处理函数 | 说明 |
|------|------|----------|------|
| `GET` | `/api/health` | - | 健康检查 |
| `GET` | `/api/status` | - | 获取世界状态 |
| `GET` | `/api/state/{file}` | - | 读取状态文件 |
| `GET` | `/api/characters` | - | 获取角色列表 |
| `GET` | `/api/chronicle/{volume}` | - | 读取叙事卷 |
| `GET` | `/api/timeline` | - | 读取时间线 |
| `GET` | `/api/rounds-log` | - | 读取轮次日志 |
| `GET` | `/api/memory` | - | 读取记忆数据 |
| `GET` | `/api/worlds` | `_handle_list_worlds` | 世界列表 |
| `GET` | `/api/worlds/current` | - | 当前世界名 |
| `GET` | `/api/story/context` | - | 叙事上下文 |
| `GET` | `/api/story/events` | - | 叙事事件列表 |
| `GET` | `/api/chapters` | - | 章节修订列表 |
| `GET` | `/api/book/export` | - | 导出小说文件 |
| `POST` | `/api/round/start` | `_handle_single_round` | 启动单轮推演 (SSE) |
| `POST` | `/api/auto/start` | `_handle_auto_start` | 启动自动推演 (SSE) |
| `POST` | `/api/auto/pause` | - | 暂停自动推演 |
| `POST` | `/api/auto/resume` | - | 恢复自动推演 |
| `POST` | `/api/npc/generate` | `_handle_npc_generate` | 自动生成 NPC |
| `POST` | `/api/worlds/switch` | `_handle_switch_world` | 切换世界 |
| `POST` | `/api/worlds/create` | `_handle_create_world` | 创建世界 V1 |
| `POST` | `/api/worlds/create-v2` | `_handle_create_world_v2` | 创建世界 V2 (结构化) |
| `POST` | `/api/worlds/generate-details` | `_handle_world_generate_details` | 生成角色详情 |
| `POST` | `/api/worlds/chat` | `_handle_world_chat` | 世界创建对话 |
| `POST` | `/api/worlds/upload-doc` | `_handle_upload_doc` | 文档导入创建世界 |
| `POST` | `/api/worlds/framework` | `_handle_framework_update` | 世界框架读写 |
| `POST` | `/api/worlds/restart` | `_handle_restart_world` | 重启世界 |
| `POST` | `/api/worlds/delete` | `_handle_delete_world` | 删除世界 |
| `POST` | `/api/polish` | `_handle_polish` | 润色主角行动 |
| `POST` | `/api/interact/start` | `_handle_interact_start` | 交互式游玩 |
| `POST` | `/api/inject` | `_handle_inject` | 注入外部事件 |
| `POST` | `/api/story/checkpoint` | `_handle_story_checkpoint` | 创建叙事检查点 |
| `POST` | `/api/chapters/approve` | `_handle_chapter_approve` | 批准章节修订 |
| `POST` | `/api/book/compile` | `_handle_book_compile` | 编译小说 |

### 辅助函数

- `_send_json(data, status)` — 发送 JSON 响应 + CORS 头
- `_send_sse()` — 设置 SSE 响应头
- `_write_sse_event(event_type, data)` — 写入 SSE 事件
- `_get_api_config()` — 从请求头提取 API Key / Base URL / Model
- `_validate_world_name(name)` — 安全校验世界名 (防路径穿越)
- `_try_parse_world_json(content)` — 多种策略尝试解析 LLM 输出的 JSON

### 全局常量

- `AUTO_STATE = {"paused": False, "stop": False}` — 自动推演状态
- `ALLOWED_STATE_FILES` — 允许通过 API 读取的状态文件名白名单
- `SAFE_WORLD_RE = re.compile(r"^[^/\\._][^/\\]*$")` — 安全世界名正则

---

## 2. scheduler.py — 智能体编排器

**文件**: `backend/scheduler.py:1-686`

### 概述

世界推演的核心编排模块。管理 6 个 Agent 的调度顺序、并行执行、SSE 事件流推送。

### 关键类

#### `RoundEvent` (line 16)
```python
class RoundEvent:
    def __init__(self, event_type: str, data: dict):
        self.event = event_type
        self.data = data
```
SSE 事件的数据载体。

### 核心函数

#### `run_round(api_key, base_url, model, event_callback, pause_check)` (line 22)
执行单轮完整推演。流程：

1. **World Engine** (串行) — 流式推进世界状态
2. **System Agent + Protagonist + NPC Designer + NPC Agents** (并行 `ThreadPoolExecutor(max_workers=4)`)
3. **Skip Detection** — 如果主角在休息且无活跃事件，跳过 NPC 和 Chronicler
4. **Chronicler** (串行) — 流式生成叙事文本
5. 保存 `rounds-log.json` 和 `round-NNNN.json`

#### `run_rounds_auto(stop_conditions, intervention_nodes, ...)` (line 340)
自动多轮推演循环。支持：
- 最大轮数
- 目标修为 (到达即停)
- 目标日期
- 境界突破干预节点
- 世界事件触发干预节点
- 交互模式 (每3轮暂停)
- 故事结束检测 (`_check_story_end`)

#### `run_interactive_rounds(protagonist_action, ...)` (line 429)
交互式游玩：玩家输入行动 → 执行一回合后暂停等待下一步。

#### `_run_round_with_action(action_text, ...)` (line 444)
以预定的玩家行动替代主角 Agent 输出，然后执行标准的 World Engine → System Agent → NPC → Chronicler 流程。

#### `_check_and_generate_npcs(api_key, ...)` (line 583)
惰性 NPC 生成检查：
- 少于 3 个 NPC → 立即生成
- 每 8 轮 (少于 10 个 NPC 时)
- 每 15 轮
- 主角动作包含"遇到/来到/进入/拜访"等词

#### `_check_story_end(protagonist, event_callback)` (line 655)
故事结束检测：
- 风险 >= 90 时掷死亡骰
- 世界事件含 `story_ending` 标记

---

## 3. config.py — 全局配置

**文件**: `backend/config.py:1-172`

### 概述

项目路径管理 + 多世界切换机制。

### 关键变量

- `PROJECT_ROOT` — 项目根目录
- `WORLDS_DIR` — 世界数据目录 (`worlds/`)

### 懒加载路径 (line 154-161)

```python
_LAZY_PATHS = {
    "STATE_DIR": state_dir,
    "NPC_DIR": npc_dir,
    "MEMORY_DIR": memory_dir,
    "CHRONICLE_DIR": chronicle_dir,
    "CONFIG_DIR": config_dir,
    "SYSTEM_DIR": system_dir,
}
```
通过 `__getattr__` 实现懒加载，每次访问都从当前世界路径计算。

### 关键函数

- `current_world_name()` → `str` — 读取 `_current` 文件，自动 fallback 到第一个存在的世界
- `switch_world(name)` — 切换活跃世界
- `world_dir()` → `str` — 当前世界的根路径
- `refresh_paths()` — 兼容性空操作 (路径已懒加载)
- `_ensure_world_scaffold(name)` — 自动补全世界缺失的目录和文件
