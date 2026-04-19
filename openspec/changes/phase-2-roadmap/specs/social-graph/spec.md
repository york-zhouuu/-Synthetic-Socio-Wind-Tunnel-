# social-graph — 能力增量

## ADDED Requirements

### Requirement: 关系边与强度
系统 SHALL 在 agent 两两之间维护有向关系 `Relation(from, to, kind, strength, last_interaction)`，
`kind` 至少覆盖 `stranger` / `acquaintance` / `friend` / `family` / `antagonist`，
`strength` 为 0–1 浮点表达关系强度。

#### Scenario: 共处时的关系微调
- **WHEN** 两 agent 在咖啡馆同时停留并发生一次对话
- **THEN** 两方的 Relation.strength SHALL 按既定规则小幅提升

### Requirement: 弱关系（Granovetter）指标
系统 SHALL 提供函数计算"弱关系数"：
跨社群（不同社交圈）的中等强度关系计数，作为实验核心指标之一。

#### Scenario: 实验评估
- **WHEN** 实验结束时 metrics 模块请求弱关系总数
- **THEN** social-graph SHALL 返回该值及按社群的分布
