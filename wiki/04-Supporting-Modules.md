# 支撑模块

## 1. state/ — 状态读写模块

**文件**: `backend/state/__init__.py:1-185`

### 概述

文件库读写封装层，提供线程安全的 JSON/Markdown 文件操作 + 玩家角色管理 + 注入系统。

### 核心函数

| 函数 | 签名 | 说明 |
|------|------|------|
| `read_json` | `(dir_path, filename) → dict` | 读取 JSON 文件 |
| `write_json` | `(dir_path, filename, data)` | 写入 JSON (线程安全) |
| `update_json` | `(dir_path, filename, updater, default) → dict` | 原子读-改-写 (单锁) |
| `read_text` | `(dir_path, filename) → str` | 读取文本文件 |
| `append_text` | `(dir_path, filename, text)` | 追加文本 (线程安全) |
| `write_text` | `(dir_path, filename, text)` | 写入文本 (线程安全) |

### 锁机制 (line 5-12)

```python
_locks = {}  # 全局锁注册表
_lock_registry = threading.Lock()  # 注册表自身锁

def _get_lock(path: str) -> threading.Lock:
    # 每个文件一个锁，线程安全地创建
```

### 玩家角色 (`get_player_character`, line 108)

从 `characters.json` 中查找 `player_controlled: true` 的角色，与 `protagonist.json` 合并返回。支持多个字段的合并：
`name, realm, attributes, skills, inventory, action_log, _risk, has_system, system_name, backstory, personality, personality_profile, _current_location`

### 辅助函数

- `get_player_memory_id()` → `str` — 获取玩家角色的记忆 ID
- `get_player_name(default)` → `str` — 获取玩家名字
- `sync_player_character_state(protagonist_state)` — 将 protagonist.json 变更同步回 characters.json

### 注入系统 (line 76-103)

- `get_pending_injections()` → `list` — 获取未应用的注入
- `add_injection(text)` — 添加外部事件注入
- `clear_applied_injections()` — 清理已应用的注入

---

## 2. memory_manager.py — 记忆管理

**文件**: `backend/memory_manager.py:1-235`

### 概述

角色记忆的全生命周期管理：初始化、添加、压缩、检索、关系更新。

### 关键函数

#### `init_character_memory(char_id, char_name, char_type)` (line 7)
初始化角色记忆文件结构：
```json
{
  "char_id": "...",
  "char_name": "...",
  "char_type": "protagonist|npc|system",
  "recent": [],
  "milestones": [],
  "compressed": [],
  "relationships": {}
}
```

#### `add_memory(char_id, entry, api_key, ...)` (line 29)
添加记忆条目，自动分类：
- `importance >= 4` → milestones (里程碑，保留最近 20 条)
- `importance < 4` → recent (近期，保留最近 10 条)
- recent > 15 条时触发 `_compress_memories` LLM 压缩
- 同时写入 ChromaDB 向量存储

#### `get_memory_context(char_id, max_items, context)` (line 94)
层级检索策略：
1. **语义检索优先**: ChromaDB 向量搜索 (如果可用)
2. **Fallback**: 里程碑 (5条) → 近期 (max_items) → 压缩 (3条) → 人际关系

#### `_compress_memories(entries, api_key, ...)` (line 160)
LLM 压缩方法 (有 API key 时) 或结构化拼接 (fallback)。

#### `sync_all_characters()` (line 212)
确保所有角色都有记忆文件。从 `characters.json` 读取角色列表并初始化。

---

## 3. story_ledger.py — 叙事账本

**文件**: `backend/story_ledger.py:1-738`

### 概述

持久化叙事状态的可查询 SQLite 数据库。作为 append-only 的证据源，所有玩家行动、世界事实、伏笔都不可被静默覆盖。

### 数据表

| 表名 | 用途 |
|------|------|
| `ledger_meta` | 元数据 (schema 版本、世界名、玩家 ID) |
| `story_events` | 故事事件 (append-only，含 actor/chapter/round/visibility) |
| `canon_facts` | 世界正史事实 (subject-predicate-object, 支持版本化) |
| `foreshadows` | 伏笔管理 (plant / resolve, 含逾期检测) |
| `chapter_revisions` | 章节修订 (多版本, 支持 draft/reviewed/approved) |
| `chapter_sessions` | 章节会话 (场景收集容器) |
| `chapter_scenes` | 场景正文 (按 chapter_no + scene_no 排序) |
| `checkpoints` | 叙事检查点 |

### 关键类: `StoryLedger` (line 41)

#### 核心方法

| 方法 | 说明 |
|------|------|
| `bootstrap(world_name, player)` | 初始化账本元数据 |
| `append_event(event_type, ...)` | 追加事件 (永不删除) |
| `record_player_action(action, player_id, ...)` | 记录玩家行动 |
| `upsert_fact(subject_id, predicate, object_value, ...)` | 更新/插入世界事实 |
| `add_foreshadow(title, detail, ...)` | 植入伏笔 |
| `resolve_foreshadow(id)` | 回收伏笔 |
| `create_checkpoint(label, ...)` | 创建检查点 |
| `active_chapter(round_no)` | 获取/创建当前活跃章节 |
| `append_scene(content, round_no, ...)` | 追加场景 + 自动封口 |
| `close_active_chapter(...)` | 封口章节 → 生成 revision |
| `add_chapter_revision(chapter_no, content, ...)` | 创建章节修订版本 |
| `approve_chapter(chapter_no, revision_no)` | 批准章节 (同一章节只能有一个 approved) |
| `context_for(player_id, chapter_no, ...)` | 获取叙事上下文 (事件+事实+伏笔) |
| `list_events(limit)` | 列出最近事件 |

---

## 4. npc_orchestrator.py — NPC 编排器

**文件**: `backend/npc_orchestrator.py:1-185`

### 概述

管理 NPC 的活跃度计算、批量推演 prompt 构建、输出应用。

### 核心函数

#### `get_active_npcs() → list` (line 5)
活跃度评分系统 (取 Top 5):
- 位置重合 → +3
- 事件相关 → +2
- 上一轮与主角互动 → +2

#### `build_batch_prompt(active_npcs) → str` (line 52)
构建批量 NPC 推演 prompt。用 `deepseek-lite` 模型降低成本。

#### `apply_npc_output(output, active_npcs)` (line 102)
- 记录每个 NPC 的 `_last_action` / `_last_dialogue`
- 保存场景氛围到 world.json

#### `get_background_npc_routines() → str` (line 131)
不在当前场景的 NPC 基于 `daily_routine` 字段生成纯文本行为描述，**不调 LLM，零 API 消耗**。

#### `get_npc_summary_for_chronicler() → str` (line 165)
合并远景 (背景 NPC) 和近景 (活跃 NPC) 的行为摘要。

---

## 5. risk.py — 风险系统

**文件**: `backend/risk.py:1-115`

### 概述

驱动世界的不确定性。风险值 0-100，影响负面事件概率和严重程度。

### 关键函数

| 函数 | 说明 |
|------|------|
| `get_risk(char_id) → int` | 获取当前风险值 |
| `set_risk(value)` | 设置风险值 (clamped 0-100) |
| `modify_risk(delta)` | 修改风险值 |
| `assess_action_risk(action_text) → float` | 根据行动关键词评估风险 modifier |
| `roll_fate(risk_level) → (event_type, severity, description)` | 掷命运骰子 |
| `check_death(risk_level, hp_ratio) → bool` | 死亡判定 |
| `get_fate_prompt_context() → str` | 风险 prompt 上下文 |
| `reset_risk()` | 重置风险 (设为 5) |

### 行动风险映射 (`ACTION_RISK`, line 11-16)
```
战斗: +8, 逃跑: +2, 探索: +5, 修炼: +2, 突破: +6,
交易: 0, 休息: -2, 社交: +1, 冒险: +7, 潜入: +6,
谈判: +2, 求助: 0, 炼丹: +4, 锻器: +3, 猎杀: +9,
挑战: +7, 偷窃: +8, 救人: +6, 背叛: +10, 投靠: +3,
日常: -1, 学习: -1, 观察: 0, 等待: -1
```

---

## 6. prose_quality.py — 文本质检

**文件**: `backend/prose_quality.py:1-62`

### 概述

确定性的写作质量信号检测。**不是 AI 评判文学价值**，而是捕捉机械性 AI 写作模式。

### 核心函数: `review_prose(content) → dict` (line 29)

检测项:
- **篇幅**: < 400 字 → 警告
- **段落**: < 3 段 → 警告
- **AI 套话**: 检测"一切如常"、"不由得"、"嘴角微微上扬" 等 9 种 cliche
- **重复句式**: 长度 > 8 字的重复句
- **句末节奏**: > 92% 句号结尾且 > 8 句 → 节奏单调

评分公式: `100 - flags×12 - excess_cliches×4`

---

## 7. skip_detector.py — 跳过检测

**文件**: `backend/skip_detector.py:1-16`

### 核心函数: `should_skip_full_round(protagonist_output, world) → bool` (line 5)

- SKIP_KEYWORDS: 休息、睡觉、修炼、打坐、养伤、等待、发呆、整理
- FORCE_RUN_KEYWORDS: 战斗、攻击、逃跑、发现、遇到、对话、交易、探索
- 有活跃世界事件 → 不跳过
- 动作含跳关键词但不含强制关键词 → 跳过

---

## 8. 其他辅助模块

### session_config.py (line 1-35)
会话级 API 凭证注册表。`set_session()` / `get_all()`。调度器在每轮开始时调用 set，后续 apply_* 和 memory_manager 可从 session 获取凭证。

### doc_parser.py (line 1-82)
文档导入解析：
- `extract_text(bytes, extension, filename)` → 支持 .txt/.md/.pdf (PyMuPDF)
- `summarize_long_text(text, api_key, ...)` → 超长文本分块 AI 摘要 (chunk_size=15000, overlap=500)

### book_compiler.py (line 1-53)
`compile_book(world_dir, title)` → 将已批准章节编译为 Markdown + HTML 文件，内置阅读器 CSS。

### memory/chroma_store.py (line 1-82)
ChromaDB 向量存储封装：
- `get_client()` → PersistentClient (路径: `<world>/memory/chroma_db`)
- `add_memory_embedding(char_id, memory_id, content, metadata)` → 添加向量
- `search_memories(char_id, query, top_k)` → 语义搜索
- `reset_client()` → 切换世界时重置

### state/graph.py (line 1-113)
NetworkX 关系图谱。支持 `add_entity`, `add_relation`, `get_related`, `get_entities_in_region`, `build_initial_graph`。
