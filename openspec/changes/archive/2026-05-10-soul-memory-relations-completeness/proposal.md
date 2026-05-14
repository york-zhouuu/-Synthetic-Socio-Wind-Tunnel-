## Why

`Chain-Position: infrastructure`（agent 内容填充层；不在 thesis 主链条上但服务整条链）

`docs/agent_system/21-current-agent-design.md` §6 列出了 agent 灵魂 / 记忆 /
关系填充的三件套缺口。round-1 fix 已 ship 了：
- B1 archetype 模板 + match_archetype（7 个 archetype）
- B2 life_history 函数（**纯 LLM 即兴，无 Lane Cove 真实数据 anchor**）
- B3 social_priors 6 rules（**实际产 ties / ABS commute matrix 接入未验证**）

但是经过 2026-05-10 audit 发现：
- **B1 严重缺口**：1000 agent population 的 archetype 实际匹配率 **31.3%**，
  68.7% 是 unmatched —— 现有 7 个 archetype 不足以覆盖 Lane Cove 的真实人群
  分布（年轻 renter / mid-career renting families / older renters / 部分时段
  工作者全是 unmatched）。
- **B2 半成品**：`generate_life_history_for_protagonists` 函数活着，但 LLM
  prompt 里没有 archetype-specific 真实 Lane Cove 故事 anchor —— 输出是 LLM
  凭空写的，"emma 是 Lane Cove 居民"和"emma 是 Brooklyn 居民"输出几乎一样。
- **B3 未验证**：6 rules + preload_ties 都在，但**从来没在 1000 agent 上跑过
  完整 audit**。每个 rule 实际产多少 ties / coverage / 是否有偏差，未知。
- **B4 未做**：do_something prompt 没有"本地话题种子"，对话内容缺 Lane Cove
  风味。

本 change = 一次性补完 B 系列。

## What Changes

- **B1** — `data/lanecove/archetypes.json` **扩展到 11+ archetype**：补
  `young_renter_commuter` / `mid_renter_family` / `older_renter_downsizer` /
  `casual_shift_worker` 4 个 fallback archetype 覆盖 unmatched profile；
  **目标**：匹配率从 31.3% → ≥ 80%。
- **B2** — 新建 `data/lanecove/life_history_templates.json`：每个 archetype
  对应一组 5-8 条 Lane Cove-grounded 第一人称生命事件模板（"我 8 年前从 Hong
  Kong 搬来"、"在 Lane Cove West public school 上的小学"等）。
  `generate_life_history_for_protagonists` 改为优先用模板变奏，fallback 才走
  LLM 即兴。
- **B3** — 新增 `tools/audit_social_priors.py`：在 1000 agent population 上跑
  `compute_social_priors_for_population`，统计每 rule 实际产 ties 数 / 覆盖率
  / 异常分布；如 rule 不 fire 或过 fire 调阈值。
- **B4** — 新建 `data/lanecove/conversation_topics.json`：5-10 条 Lane Cove
  特定对话话题（school zone debate / Cammeray-Plaza 停车 / Cameraygal
  Festival / Council elections / data centre proposal 等）+
  `load_conversation_topics()` + 接入到 `do_something` handler 的 args
  作为 "local_topics" 提示。

- **NON-GOAL**：本 change **不**改 `match_archetype` 算法本身（已经合理）；
  只补 archetype 数据。
- **NON-GOAL**：B2 life_history 模板**不要求**深度 Lane Cove 个体历史 web
  research（那是 V2）；本 change 用 archetype 描述提炼合理模板就够。
- **NON-GOAL**：B3 不重写 `social_priors` rules，只 audit + 调阈值。

## Capabilities

### New Capabilities
无。

### Modified Capabilities
无 spec delta 改动——B 全是数据 / tool / 数据消费链路扩展，不改 capability 契约。

## Impact

**代码**：
- `data/lanecove/archetypes.json` 加 4 个 archetype（保持 schema_version=1）
- `data/lanecove/life_history_templates.json` 新建
- `data/lanecove/conversation_topics.json` 新建
- `synthetic_socio_wind_tunnel/data_loader/lanecove.py`：
  - `_generate_life_history_for_one` 新增模板 anchor 路径
  - 新增 `load_conversation_topics()` 函数
- `synthetic_socio_wind_tunnel/agent/operations/handlers/do_something.py`：handler args
  接收 `local_topics: tuple[str,...] | None`，prompt 里如非空插入 local_topics 段
- `tools/audit_social_priors.py` 新建
- `tools/audit_archetype_coverage.py` 新建

**测试**：
- `tests/test_archetype_coverage.py`：用 LANE_COVE_PROFILE × 1000 sample，断言
  matched ≥ 80%
- `tests/test_life_history_templates.py`：每个 archetype 都有 ≥ 5 条模板；模板
  参数渲染（{name} / {age}）替换正确
- `tests/test_social_priors_audit.py`：跑 audit 输出 ≥ 1 条 tie per rule
- `tests/test_conversation_topics_load_and_inject.py`：加载 topics + do_something
  prompt 含 topic 文本

**外部影响**：
- 修复后 Gemini real-LLM run 的 reflection / dialogue 内容**真带 Lane Cove 风味**
- audit script 留作 tool，未来加 archetype / rule 时可重跑验证
