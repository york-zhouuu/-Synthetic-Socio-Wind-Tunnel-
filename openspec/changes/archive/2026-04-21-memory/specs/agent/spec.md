# agent — 能力增量

## ADDED Requirements

### Requirement: AgentRuntime.should_replan 纯代码规则

`AgentRuntime` SHALL 新增方法：

```
should_replan(
  memory_view: Sequence[MemoryEvent],
  candidate: MemoryEvent,
) -> bool
```

- 方法 SHALL 为**纯代码规则**，MUST NOT 调用 LLM（每 tick 每 agent 触发，
  LLM 成本禁区）。
- 默认实现基于 `profile.personality.routine_adherence` /
  `profile.personality.curiosity` typed 字段（typed-personality change 引入）
  以及 `candidate.kind` 分支决定；具体规则由 `memory` spec 的
  process_tick Requirement 与 `docs/agent_system/09` 文档说明。
- 子类或策略对象可覆盖 `should_replan`；基类版本保持为"合理默认"。
- 方法不得修改 memory_view 或 candidate（只读分析）。

#### Scenario: 高好奇心 agent 对通知返回 True
- **WHEN** agent `profile.personality.routine_adherence=0.2,
  profile.personality.curiosity=0.9`，candidate 是 `kind="notification"` 且
  `urgency=0.8`
- **THEN** `should_replan(memory_view, candidate)` SHALL 返回 `True`

#### Scenario: 高坚持 agent 对通知返回 False
- **WHEN** agent `profile.personality.routine_adherence=0.9`，同样的通知
  candidate
- **THEN** `should_replan(memory_view, candidate)` SHALL 返回 `False`

#### Scenario: 方法不调用 LLM
- **WHEN** `should_replan` 被调用 10000 次
- **THEN** 任何 LLMClient / anthropic SDK / 网络请求 SHALL 不被触发；
  耗时 SHALL 在毫秒量级

### Requirement: Planner.replan 方法

`Planner` SHALL 新增异步方法：

```
async replan(
  profile: AgentProfile,
  current_plan: DailyPlan,
  interrupt_ctx: dict,
) -> DailyPlan
```

- `interrupt_ctx` 至少含 `trigger_event: MemoryEvent` 与
  `recent_memories: list[MemoryEvent]`。
- SHALL 调用 `llm_client.generate(prompt, model=profile.base_model)`
  恰好 1 次。
- 产出新 DailyPlan：`current_step_index` 保留为原值；
  `steps[:current_step_index]` 不变；`steps[current_step_index:]` 替换为
  LLM 新产的 step 列表。
- LLM 解析失败时 SHALL 返回 `current_plan` 的副本（fallback），不抛异常。

#### Scenario: 成功 replan
- **WHEN** 当前 plan 有 10 step，`current_step_index=4`；replan 触发
- **THEN** 返回的新 plan SHALL 保留 `steps[:4]`，替换 `steps[4:]`；
  llm_client.generate SHALL 被调用 1 次

#### Scenario: LLM 失败 fallback
- **WHEN** llm_client.generate 抛异常
- **THEN** `replan` SHALL 返回原 plan 的副本，不抛；日志 SHALL 含"replan_failed"
