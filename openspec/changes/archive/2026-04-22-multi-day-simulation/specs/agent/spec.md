## MODIFIED Requirements

### Requirement: 每日计划生成（一次 LLM / 天）

`Planner(llm_client)` SHALL 在构造时注入 LLM 客户端；
`await planner.generate_daily_plan(profile, *, date, day_of_week, weather,
available_locations, life_patterns, carryover: CarryoverContext | None = None)
→ DailyPlan` 为**异步**方法，SHALL：
- 构造 prompt（`_PLAN_PROMPT_TEMPLATE`），包含人格、家庭位置、兴趣、
  当日天气与作息；
- **若 `carryover` 非 None**：prompt 额外包含三段：
  - `【昨日经历摘要】{carryover.yesterday_summary.summary_text}`
  - `【近 3 日反思】` 按 day_index 升序列出每条 summary 前 120 字
  - `【未完成任务锚点】` 列出 pending_task_anchors 的 content（≤ 5 条）
  - 提示 LLM："当前日期是 {date}；请生成与过去经历一致但允许偏离的新 plan"；
  - 如果 carryover 总字数超过 1500 字，SHALL 对 summary_text 截断到前 300 字
    以防 prompt 爆炸；
- 调用 `llm_client.generate(prompt, model=profile.base_model)` 一次，解析
  出 `PlanStep` 列表；
- 解析失败时 SHALL 返回空 steps 的 DailyPlan，不得抛异常中断 tick。
- 每个 PlanStep SHALL 含 `time`（如 `"7:00"`）、`action`
  （`move` / `stay` / `interact` / `explore`）、`destination`、`activity`、
  `duration_minutes`、`reason`、`social_intent`
  （`alone` / `open_to_chat` / `seeking_company`）。

- **每个 simulated day** SHALL 每个 agent 仅调用一次 `generate_daily_plan`
  （`carryover=None` 时行为与单日路径完全一致）。
- `carryover=None` 是默认值；单日调用方无需改造。

#### Scenario: 外向性高者更愿意社交
- **WHEN** profile `extroversion=0.9`
- **THEN** 返回的 PlanStep 中 `social_intent` 为 `seeking_company`
  的比例 SHOULD 显著高于 `extroversion=0.1` 的同类 agent

#### Scenario: carryover=None 时向后兼容
- **WHEN** 调用 `generate_daily_plan(profile, date=d, ..., carryover=None)`
- **THEN** 生成的 prompt SHALL 与 Phase 2 归档时完全一致；LLM 调用次数
  SHALL 为 1；产出的 DailyPlan 与单日路径等价

#### Scenario: carryover 非空时 prompt 扩展
- **WHEN** 调用时 `carryover` 非 None 且含非空 yesterday_summary +
  2 条 recent_reflections + 3 条 pending_task_anchors
- **THEN** prompt SHALL 新增【昨日经历摘要】/【近 3 日反思】/
  【未完成任务锚点】三个段落；LLM 调用次数 SHALL 仍为 1；总 prompt
  字符数 SHALL ≤ 1500 + 原单日 prompt 长度

#### Scenario: carryover 过长时截断
- **WHEN** carryover.yesterday_summary.summary_text 长 800 字符
- **THEN** prompt 中该 summary_text SHALL 被截断到 300 字符 + "…"

#### Scenario: 多日调用 plan 重生成
- **WHEN** `MultiDayRunner.run_multi_day(num_days=3)` 触发每日
  on_day_start 调 `planner.generate_daily_plan(..., carryover=ctx_day_N)`
- **THEN** 每日 SHALL 恰生成一个新 DailyPlan（共 3 个）；carryover 在
  day 0 为 None、day 1+ 非 None
