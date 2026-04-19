# metrics — 能力增量

## ADDED Requirements

### Requirement: 四类实验指标
系统 SHALL 采集并输出以下指标：
1. **轨迹偏离** — 干预后 agent 访问位置分布相较基线组的 KL / Wasserstein 距离；
2. **网络密度** — social-graph 在实验窗口末的平均度、聚类系数；
3. **弱关系数** — 跨社群中等强度关系的计数（Granovetter 意义）；
4. **叙事质量** — 由 LLM 评审对 agent 日记 / 反思的结构化打分。

#### Scenario: 实验结束导出
- **WHEN** 模拟结束后调用 `metrics.export(experiment_id)`
- **THEN** SHALL 落盘四类指标到统一目录，带实验/对照组标记

### Requirement: 对比组种子冻结
metrics SHALL 记录实验与对照组使用的：profile seed、Policy Hack seed、
Orchestrator 冲突裁决 seed、LLM 采样 seed。

- 两组在相同起点下运行，仅 Policy Hack 不同，以保证因果可归因。

#### Scenario: 复现实验
- **WHEN** 使用保存的全部 seed + 配置重跑
- **THEN** 得到的 agent 轨迹 SHALL 与原实验逐 tick 一致（在确定性范围内）

### Requirement: 运行期成本观测
metrics SHALL 汇总 model-budget 的 tick 级调用计数，输出每日 Sonnet/Haiku/skip
总数与成本估算（基于每 token 价格常量）。

#### Scenario: 成本日报
- **WHEN** 某日模拟结束
- **THEN** `metrics.cost_report(date)` SHALL 返回三档调用次数与美元估值
