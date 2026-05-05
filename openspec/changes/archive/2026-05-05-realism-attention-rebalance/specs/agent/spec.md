## MODIFIED Requirements

### Requirement: AgentRuntime.should_replan 纯代码规则

`AgentRuntime` SHALL 提供方法：

```
should_replan(
  memory_view: Sequence[MemoryEvent],
  candidate: MemoryEvent,
  current_step: PlanStep | None = None,
  replan_count_today: int = 0,
  rng: random.Random | None = None,
) -> bool
```

- 方法 SHALL 为**纯代码规则**，MUST NOT 调用 LLM。
- 决策 SHALL 综合 6 维 personality（`routine_adherence` / `curiosity` / `openness` / `conscientiousness` / `risk_tolerance` / `extraversion`）以及 candidate.urgency。
- 决策 SHALL 加入 **context modifier**：当 `current_step` 非 None 且 `elapsed_min > duration_minutes * 0.3`（已投入活动）时，触发阈值 SHALL 升高 ~0.10（更不易被新信息拉走）。
- 决策 SHALL 加入 **疲劳衰减**：`replan_count_today` 每加 1，触发阈值 SHALL 升高 ~0.05。
- 决策 SHALL 通过**概率门**实施（`rng.random() + (urgency - threshold) > 0`）而非硬阈值，使同一 urgency 在不同 sample 下产生有限随机性，避免"全 0 / 全 1"两极化。
- `rng` 为 None 时 SHALL 使用模块级 `random` 但 caller 必须感知此场景为非 reproducible；`MemoryService.process_tick` SHALL 注入 seeded `random.Random` 实例。
- 子类或策略对象可覆盖 `should_replan`；基类版本保持为"合理默认"。
- 方法不得修改 memory_view、candidate、current_step（只读分析）。
- 每次决策 SHALL 产出一条 `ReplanDecisionRecord`（入参 / 阈值各项 / rng_roll / 决策结果），追加到 agent 的决策日志（详见 `Requirement: AgentRuntime.replan_decision_log`）。

#### Scenario: 6 维 personality 都参与决策

- **WHEN** 两个 agent 仅 `personality.openness` 不同（一个 0.1，一个 0.9），其它 7 维 + life_pattern 完全一致；同时收到同一 candidate（`kind="notification"`, `urgency=0.6`）
- **THEN** 高 openness agent 触发概率 SHALL 显著高于低 openness agent（在 1000 次重复实验下 p<0.05）

#### Scenario: 已投入活动者更难被拉走

- **WHEN** agent A 的 `current_step.elapsed_min = 5` / `duration_minutes = 30`（刚开始），agent B 的 `current_step.elapsed_min = 20` / `duration_minutes = 30`（已投入），其它一切相同
- **THEN** 同一 candidate 下 agent B 的触发概率 SHALL 低于 agent A

#### Scenario: 疲劳衰减

- **WHEN** 同一 agent `replan_count_today` 从 0 累计到 3，期间 candidate 完全相同
- **THEN** 第 4 次 should_replan 的触发阈值 SHALL 比第 1 次高 ~0.15

#### Scenario: 概率门取代硬阈值

- **WHEN** 1000 次相同 urgency=0.6 / 相同 personality 的决策（不同 rng seed）
- **THEN** True 比例 SHALL 介于 [10%, 90%]（即不全 0 也不全 1，体现概率性）

#### Scenario: 方法不调用 LLM

- **WHEN** `should_replan` 被调用 10000 次
- **THEN** 任何 LLMClient / anthropic SDK / 网络请求 SHALL 不被触发；耗时 SHALL 在毫秒量级

### Requirement: Planner.replan 方法

`Planner` SHALL 提供异步方法：

```
async replan(
  profile: AgentProfile,
  current_plan: DailyPlan,
  interrupt_ctx: dict,
) -> DailyPlan
```

- `interrupt_ctx` SHALL 至少包含以下键：
  - `trigger_event: MemoryEvent`（触发本次 replan 的事件）
  - `recent_memories: list[MemoryEvent]`（最近 5-10 条记忆）
  - `current_time: datetime`
  - `current_step: PlanStep | None`（agent 当前正在执行的 step）
  - `current_location_kind: str`（"street" / "cafe" / "park" / "home" / "office" / "other"）
  - `nearby_agents: list[NearbyAgent]`（每条含 `is_familiar: bool`，无需暴露 id）
- SHALL 调用 `llm_client.generate(prompt, model=profile.base_model)` 恰好 1 次。
- prompt 由 `_build_replan_prompt` 装配，SHALL 满足 prompt 结构对称性约束（详见 `Requirement: Replan prompt 对称 context window`）。
- 产出新 DailyPlan：`current_step_index` 保留为原值；`steps[:current_step_index]` 不变；`steps[current_step_index:]` 替换为 LLM 新产的 step 列表。
- LLM 解析失败时 SHALL 返回 `current_plan` 的副本（fallback），不抛异常。

#### Scenario: 成功 replan

- **WHEN** 当前 plan 有 10 step，`current_step_index=4`；replan 触发；interrupt_ctx 含完整新 keys
- **THEN** 返回的新 plan SHALL 保留 `steps[:4]`，替换 `steps[4:]`；llm_client.generate SHALL 被调用 1 次

#### Scenario: LLM 失败 fallback

- **WHEN** llm_client.generate 抛异常
- **THEN** `replan` SHALL 返回原 plan 的副本，不抛；日志 SHALL 含 "replan_failed"

#### Scenario: interrupt_ctx 缺失新 key 时不崩

- **WHEN** caller 传入仅含 trigger_event + recent_memories + current_time 的旧 schema interrupt_ctx
- **THEN** `replan` SHALL 不抛异常；prompt 中缺失的 block（current_step / nearby_agents）SHALL 整块省略，不显示"无 / 空"占位

## ADDED Requirements

### Requirement: Replan prompt 对称 context window

`Planner._build_replan_prompt` SHALL 装配的 prompt 满足**对称 context window** 约束——push 不被语言学特殊化为"打断者 / interrupt"，与其它 context 信号并列展示。

具体约束：

- prompt MUST NOT 包含字符串 "打断了你的计划" / "interrupted" / "interrupting" / "中断" 或任何把 push 描述为"打断者 / 紧急事件"的措辞。
- prompt SHALL 用统一的 markdown 标记（如 `【...】` 或同级别 `## ...` heading）展示以下 context blocks：
  - `【现在】` / `【正在做】` / `【周围】` / `【最近发生】` / `【手机】` / `【接下来计划】`
- 每个 block 在数据存在时显示；数据为空时**整块省略**（不显示"无" / "空" 占位文字）。
- 推送内容 SHALL 在 `【手机】` block 中展示，禁止在该 block 标题之外的任何位置重复 / 高亮 push 内容。
- 提问句 SHALL 中性（"综合以上信息你会改变接下来的计划吗？"），不带"由于这条紧急推送 / 这件事打断你"的偏向。

#### Scenario: prompt 不含打断措辞

- **WHEN** Planner._build_replan_prompt 接收完整 interrupt_ctx 装配 prompt
- **THEN** prompt 字符串 SHALL NOT 包含 "打断"、"interrupt"、"紧急"、"urgent" 等偏向词

#### Scenario: 五个对称 block 出现

- **WHEN** prompt 装配且 interrupt_ctx 五个 block 数据完整
- **THEN** prompt SHALL 同时含 `【现在】`、`【正在做】`、`【周围】`、`【最近发生】`、`【手机】`、`【接下来计划】` 6 个 block 标记

#### Scenario: 空 block 省略

- **WHEN** `nearby_agents = []`
- **THEN** prompt SHALL NOT 含 `【周围】` 标记（整块省略）；其它 block 不受影响

### Requirement: AgentRuntime.replan_decision_log

`AgentRuntime` SHALL 维护 `replan_decision_log: list[ReplanDecisionRecord]`，每次 `should_replan` 调用追加一条（无论返回 True 或 False）。

`ReplanDecisionRecord` 字段：

```
agent_id: str
tick: int
simulated_time: datetime
candidate_kind: str
candidate_urgency: float
threshold_computed: float
base_components: dict[str, float]   # personality 各维度的贡献
context_modifier: float
replan_count_today: int
rng_roll: float
decision: bool
```

- 决策日志 SHALL 仅在 dev / inspector 路径累积；publishable suite 30 seed × 14 day 跑动期间 SHALL 可关闭以避免内存膨胀（通过 `AgentRuntime.enable_replan_log: bool = False` 控制）。
- 每日开始 SHALL 重置 `replan_count_today = 0`。
- inspector payload 导出器（`tools/export_inspector_payload.py`）SHALL 把决策日志写入输出 JSON 的 `replan_decision_log` 顶层 key。

#### Scenario: 默认关闭

- **WHEN** AgentRuntime 默认构造
- **THEN** `enable_replan_log` SHALL 为 False；should_replan 调用 SHALL NOT 累积记录

#### Scenario: 启用时记录每次决策

- **WHEN** `runtime.enable_replan_log = True`，should_replan 被调用 5 次（3 True, 2 False）
- **THEN** `runtime.replan_decision_log` SHALL 含 5 条 record；其中 decision=True 的 SHALL 为 3 条

#### Scenario: 跨日重置 replan_count_today

- **WHEN** 一天内累计 4 次 replan，新一天 on_day_start 调用
- **THEN** `replan_count_today` SHALL 重置为 0

### Requirement: 触发率 goldilocks band

`Planner` + `AgentRuntime.should_replan` 联合 SHALL 在标准 hyperlocal_push variant 设定下使触发率落入合理区间。

合理区间：单 24 小时窗口内，在 hyperlocal_push variant 下，per-agent 平均 replan 触发率 SHALL ∈ **[5%, 15%]**（即每 100 次 should_replan 调用约 5-15 次返回 True）。

- 高于 15%：push 触发过强，疑似 prompt artifact，需收紧 base 系数。
- 低于 5%：push 几乎无效，需放松 base 系数。
- 该区间 SHALL 在 dev mode publishable suite（5 seeds × 7 days × hp variant）下作为回归断言被检查。

#### Scenario: dev suite 触发率在范围内

- **WHEN** 跑 5 seeds × 7 days × 100 agents × hyperlocal_push variant
- **THEN** 平均 per-agent-per-day replan 触发率 SHALL ∈ [5%, 15%]

#### Scenario: 触发率超出范围时 fitness audit 报警

- **WHEN** 触发率 = 25%（超 15%）
- **THEN** `fitness-audit` SHALL 产出一条 `attention_rebalance.replan_rate_out_of_band` warning

### Requirement: 个体异质响应（heterogeneity）

同一条 push 给 8 维 personality 不同的 100 个 agent 时，触发分布 SHALL 不为单峰。

- 用 100 个 agent 跑同一个 candidate（urgency=0.6, kind=notification）1000 次决策 → 把 should_replan 触发概率按 personality 主成分聚类
- SHALL 至少出现 3 个聚类组，触发概率分别为 low (<20%) / mid (30-50%) / high (>60%)
- low 组 SHALL 主要由 `routine_adherence > 0.7` + `openness < 0.3` 的 agent 组成
- high 组 SHALL 主要由 `curiosity > 0.7` + `openness > 0.7` 的 agent 组成

#### Scenario: 多峰分布出现

- **WHEN** 100 agent × 同一 candidate × 1000 rng seed 的触发概率聚类
- **THEN** SHALL 出现至少 3 个有显著差异的聚类（KL-divergence 或 silhouette score 满足 sklearn 默认阈值）
