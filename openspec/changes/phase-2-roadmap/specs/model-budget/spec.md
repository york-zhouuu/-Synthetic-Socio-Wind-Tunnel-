# model-budget — 能力增量

## ADDED Requirements

### Requirement: 每 agent 每 tick 的模型额度函数
系统 SHALL 提供 `decide_model(agent, tick_context) → ModelDecision`，
输入包含：是否 protagonist、与主角的社交距离、与当前 Policy Hack 的关联度、
当前 tick 是否为 plan/replan 边界，输出为
`sonnet` / `haiku` / `skip`（沿用上一决策）之一。

#### Scenario: 主角始终 Sonnet
- **WHEN** agent.is_protagonist=True 且在 plan 边界
- **THEN** `decide_model` SHALL 返回 `sonnet`

#### Scenario: 远离主角的 NPC
- **WHEN** 普通 agent 与所有主角的社交距离 > 3 hops 且未受干预影响
- **THEN** `decide_model` SHALL 多数返回 `skip` 以压制成本

### Requirement: 预算可观测
Orchestrator SHALL 在每 tick 末记录本 tick 的 `sonnet` / `haiku` / `skip` 计数，
供 metrics 模块统计 LLM 调用成本。

#### Scenario: 日终汇报成本
- **WHEN** 一天结束
- **THEN** metrics SHALL 能拿到当日 LLM 调用分层总数
