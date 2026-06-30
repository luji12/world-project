# 工作日志：Canon 2.0 大纲约束工程

日期：2026-07-01

## 背景

用户的大纲已经足够详细，但推演仍会偏离脚本。根因不是“大纲信息不够”，而是旧 Canon 只把大纲当作普通上下文和轻量校验；模型可以读到设定，但调度层没有强制它每轮沿着具体剧情节点推进。

## 本次完成

1. 新增 `outline_engine`
   - 将原始脚本编译为 `story_outline.json`。
   - 维护 `beat_ledger.json`，记录当前 active beat、已完成节点、尝试次数和推进历史。
   - 每轮生成 `round_contract`，明确当前节点目标、完成信号、未解锁未来节点关键词。

2. 升级 Canon 数据层
   - Canon 版本升级到 v2。
   - `world_bible.json`、`story_arcs.json` 之外新增可执行大纲与节点账本。
   - 修复起始地点提取误把世界名当地点的问题。
   - 避免把修炼等级表误识别为剧情阶段。

3. 接入推演调度
   - `scheduler` 在自动推演和玩家行动推演前都构建 `round_contract`。
   - 玩家行动如果提前跳到 locked future beat，会被 Canon gate 拦截并给出当前节点目标。
   - World/System/Chronicler 输出若提前触碰未来节点，会记录 Canon 冲突并降级为安全输出，避免写入关键状态。
   - 节点完成后自动推进 `beat_ledger`。

4. 前端可视化与叙事流修复
   - `/canon` 页面展示剧情节点轨道、active/locked/satisfied 状态、节点目标和完成信号。
   - Dashboard 增加当前 active beat 与节点目标展示。
   - 叙事流颜色恢复为纸面可读的墨色文字。
   - `outline-contract` / `outline-progress` 事件进入统一历史流，用户能看到本轮 Canon Director 的目标。

5. API
   - 新增 `GET /api/canon/outline`。
   - 新增 `GET /api/canon/beat-ledger`。
   - `/api/canon/bible` 返回 outline 与 ledger 摘要。

## 验证

- 后端编译检查通过：
  - `python3 -m py_compile agents/base.py agents/world_engine.py agents/system_agent.py agents/protagonist.py agents/chronicler.py outline_engine.py canon_engine.py canon_context.py canon_validator.py canon_migration.py npc_orchestrator.py npc_lifecycle.py scheduler.py server.py story_context.py`
- 后端全量单测通过：
  - `python3 -m unittest discover -s tests -v`
  - 结果：39 tests OK
- 前端构建通过：
  - `npm run build`
- 本地运行验证通过：
  - 重启后端 `http://localhost:3101` 与前端 `http://127.0.0.1:3100`。
  - `GET /api/canon/status` 返回 Canon v2、`outline_version=2`。
  - 当前世界重新编译后识别为：世界名“苍玄界”、起始地“青石镇”、active beat“青石镇开局”。
  - 浏览器验证 `/canon` 能显示“青石镇开局”、节点目标和 13 个剧情节点。
  - 浏览器验证 Dashboard 能显示“清除记录”按钮、Canon 当前阶段与节点目标。

## 已知边界

- 当前大纲编译是确定性规则，不依赖 LLM，因此安全、可重复；但非常特殊的文档格式仍可能需要后续增强解析规则。
- 节点完成判断使用完成信号命中，不会强行替代作者判断；未来可以在 Canon 页面增加手动标记节点完成/回退节点。
- 这次没有提交本地运行世界数据和用户脚本文档，公开仓库只包含源码、测试和文档。
