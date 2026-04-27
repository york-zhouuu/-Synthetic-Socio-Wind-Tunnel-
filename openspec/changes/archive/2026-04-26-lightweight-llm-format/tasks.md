# Tasks — lightweight-llm-format

把 Planner 的 LLM I/O 从严格 JSON + Literal enum 改为轻量 XML +
同义词映射。**不改 PlanStep / DailyPlan / Planner public API**；
内部实现 + 测试 + 同步 StubReplanLLM 与 Gemini client。

**Chain-Position**: `infrastructure`
**前置**: 无（独立 fix）

## 1. 同义词映射 helper

- [x] 1.1 在 `synthetic_socio_wind_tunnel/agent/planner.py` 加：
  - `_ACTION_SYNONYMS: dict[str, str]`（覆盖 ~30 词）
  - `_SOCIAL_SYNONYMS: dict[str, str]`（覆盖 ~10 词）
  - `_normalize_action(raw: str) -> str` —— 返回 canonical 或 "stay"
  - `_normalize_social_intent(raw: str) -> str` —— 返回 canonical 或 "alone"
  - 未知词 fallback 时 `logger.debug("unknown action token: %r", raw)`

## 2. XML parser

- [x] 2.1 实现 `_parse_xml_plan(raw: str) -> list[PlanStep]`：
  - 用 `xml.etree.ElementTree.fromstring` 解析；ParseError → 尝试 wrap
    为 `<plan>{raw}</plan>` 重试；仍失败返 `[]`
  - 找 root 下的 `<step>` 元素（容忍嵌套深度 1）
  - 每个 step 提取 `<time>` / `<destination>` / `<action>` /
    `<duration>` / `<social>` / `<activity>` 子元素
  - 缺字段优雅 degrade（time 缺则跳过该 step；其它有默认值）
  - action / social 通过 `_normalize_*` 映射
  - LLM 未提供 `<activity>` 时把 `<action>` 原文作 activity（保留 LLM 措辞）
- [x] 2.2 标记 `_parse_plan`（旧 JSON parser）为 deprecated 但保留——
  作为 fallback 当 LLM 输出 JSON 而非 XML 时使用；XML parser 失败再尝试
  JSON

## 3. Prompt 模板改 XML

- [x] 3.1 修改 `_PLAN_PROMPT_TEMPLATE` 末尾段（"输出一个 JSON 数组..."），
  改为 XML 格式说明 + 一个示例
- [x] 3.2 修改 `_build_replan_prompt` 末尾段（"输出 JSON 数组..."），
  改为 XML 格式说明 + 一个示例
- [x] 3.3 在 prompt 里**字段名简化**：
  - `duration_minutes` → `duration`
  - `social_intent` → `social`
  - 解析时映射回 canonical PlanStep 字段名

## 4. Planner 切换 parser

- [x] 4.1 `Planner.generate_daily_plan` 调 `_parse_xml_plan` 替代
  `_parse_plan`；解析失败时仍可降级到 `_parse_plan`（防 LLM 偶尔输出
  JSON）
- [x] 4.2 `Planner.replan` 同上

## 5. StubReplanLLM 同步输出 XML

- [x] 5.1 修改 `tools/suite_stub_llm.py::_plan_toward`：从 JSON 字符串
  改为 XML 字符串
- [x] 5.2 dispatch 逻辑（按 variant_name）不变

## 6. Gemini client 移除 response_schema

- [x] 6.1 `tools/suite_stub_llm.py::_GeminiClient.generate`：
  - 删 `response_mime_type="application/json"` + `response_schema=...`
  - 保留 `thinking_budget=0`
- [x] 6.2 删除 `_build_plan_schema` helper（不再需要）
- [x] 6.3 删除 `genai_types` 相关用于 schema 的 import（如不再用）

## 7. 测试

- [x] 7.1 新建 `tests/test_planner_xml_parsing.py`：
  - `test_basic_xml`: 标准 XML 一个 step 解析
  - `test_multiple_steps`: 5 个 step 解析
  - `test_action_synonyms`: visit/work/go_home/commute → 各自正确映射
  - `test_social_synonyms`: private/open/social → 正确映射
  - `test_unknown_action_fallback`: "flying" → "stay"; logger.debug
    captured
  - `test_missing_optional_fields`: 缺 destination/duration/social →
    None / default / "alone"
  - `test_missing_time_skips_step`: 缺 `<time>` 的 step 被跳过
  - `test_invalid_xml_returns_empty`: 完全无效 XML 返 []
  - `test_no_root_wraps_and_retries`: `"<step>...</step>"` 无 plan root
    时被 wrap 后解析
  - `test_llm_action_preserved_to_activity`: 未提供 `<activity>` 时原始
    action 文本保留
- [x] 7.2 修改 `tests/test_planner_replan.py`：
  - MockLLM 输出从 JSON 改为 XML
  - 验证 D.2 修复（time 早于 current_time → 重写）仍工作
- [x] 7.3 修改 `tests/test_suite_stub_llm.py`：
  - StubReplanLLM 输出验证从 `json.loads()` 改为 XML 解析
  - 验证 hyperlocal_push 输出含 `<destination>cafe_main</destination>`
  - 验证 global_distraction 仍返回 `"<plan></plan>"` 或空 string
- [x] 7.4 修改 `tests/test_suite_wiring.py`（如需要）

## 8. 验证

- [x] 8.1 全 pytest 套件通过（506+ tests）
- [x] 8.2 跑 stub mode 6-variant smoke：
  `python3 tools/run_variant_suite.py --variants ... --seeds 2 --num-days 3
  --agents 20 --mode dev --phase-days 1,1,1`
  - hyperlocal_push 仍能产 plan_changed 事件
  - 数字大致与 archive 前匹配（变化由 prompt 重写自然带来；不破坏因果链）
- [x] 8.3 跑真 Gemini smoke（如可）：
  `GEMINI_API_KEY=... python3 tools/replan_trace.py --variant
  hyperlocal_push --agents 5 --num-days 2 --use-real-llm
  --llm-provider gemini`
  - 仍产 plan_changed > 0
  - LLM 原始 action 词出现在 PlanStep.activity（如 "visit cafe..."）
- [x] 8.4 `openspec validate lightweight-llm-format --strict` 通过

## 9. 文档

- [x] 9.1 更新 `docs/agent_system/09-memory-and-replan.md`（如其中提到 JSON
  prompt 格式）—— 改为 XML
- [x] 9.2 更新 `docs/agent_system/14-multi-day-simulation.md` 中 Planner
  prompt section（如有）
- [x] 9.3 更新 `docs/agent_system/19-system-snapshot.md` 已完成 changes
  列表加上本 change

## 10. 性能 sanity

- [x] 10.1 14d × 100 agent × 1 seed × stub 模式 wall time 不显著退化
  （vs archive 前 ~12s，变化 < 30%）
