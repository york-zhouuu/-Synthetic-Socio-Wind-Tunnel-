# memory — 能力增量

## ADDED Requirements

### Requirement: 三层记忆结构
系统 SHALL 为每个 agent 维护三层记忆：
- **事件流**：按时间顺序记录可感知的 WorldEvent 摘要；
- **日摘要**：由 LLM 每日生成一次的当日经历压缩；
- **反思**：周期性（或受触发）产出的跨日主观总结。

#### Scenario: 基于记忆的社交判断
- **WHEN** agent 在咖啡馆遇到曾经吵架的邻居
- **THEN** memory 检索 SHALL 返回相关过去事件 / 摘要 / 反思，供 Planner 拼入 prompt

### Requirement: 记忆检索接口
`memory.retrieve(agent_id, query, top_k)` SHALL 返回与 query 相关的记忆条目，
按相关性 + 近期性 + 情感强度的组合排序。

#### Scenario: Planner 填装 prompt
- **WHEN** Planner 在生成 DailyPlan 前需要"过去 3 天与邻居的交互"
- **THEN** 通过此接口 SHALL 获取最多 top_k 条相关记忆摘要
