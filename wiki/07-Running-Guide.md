# 运行指南

## 1. 环境

- Python 3.12+
- Node.js 18+
- npm

## 2. 后端

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 server.py
```

默认地址：`http://127.0.0.1:3101`

## 3. 前端

```bash
cd frontend
npm install
npm run dev
```

默认地址：`http://127.0.0.1:3100`

## 4. 模型配置

进入前端“模型配置”页面填写：

- API Key
- Base URL
- 主模型
- NPC 批量模型（可选）

不要把真实 API Key 写入公开仓库。

## 5. 常用验证

后端测试：

```bash
python3 -m unittest discover -s backend/tests -v
```

前端构建：

```bash
cd frontend
npm run build
```

Python 编译检查：

```bash
python3 -m py_compile \
  backend/agents/base.py \
  backend/agents/world_engine.py \
  backend/agents/system_agent.py \
  backend/agents/protagonist.py \
  backend/agents/chronicler.py \
  backend/npc_orchestrator.py \
  backend/npc_lifecycle.py \
  backend/scheduler.py \
  backend/server.py
```

## 6. 典型工作流

### 创建世界

1. 打开 `/worlds`。
2. 输入世界设定或导入文档。
3. 选择玩家控制角色。
4. 生成世界。

### 自动推演

1. 打开 `/`。
2. 选择自动推演。
3. 观察叙事流和状态卡片。
4. 需要时暂停或注入世界事实。

### 玩家介入

1. 打开 `/play`。
2. 输入角色行动。
3. 系统根据行动推进世界。
4. 群聊只显示角色可感知内容。

### 阅读与整理

1. 打开 `/reader` 阅读正文。
2. 在章节管理中审核、编辑、润色。
3. 使用整书编译导出 HTML/Markdown。

## 7. 发布前检查

```bash
git status --short
rg -n --hidden "(sk-|ghp_|github_pat_|Bearer |apiKey|password|token|secret)" .
find . -maxdepth 2 \( -name ".env" -o -name "*.sqlite3" -o -name "chat_history.json" \) -print
```

确认不要上传：

- `worlds/`
- `.env*`
- `chat_history.json`
- `story-ledger.sqlite3`
- `chroma_db/`
- `frontend/dist/`
- `node_modules/`

## 8. 故障排查

- 页面显示旧世界信息：检查当前世界是否为空、localStorage 是否清理。
- 群聊出现全知视角：检查 NPC 事件的 `visibility` 与 `exposed_to_player`。
- Agent 报 `.get` 错误：检查模型输出是否先经过归一化。
- 长对话遗忘：检查 Story Ledger、foreshadows、recent events 是否进入 `story_context`。
