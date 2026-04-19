# orchestrator — 能力增量

## ADDED Requirements

### Requirement: Tick 循环与时间推进
系统 SHALL 提供 `Orchestrator`，按固定步长（默认 5 分钟世界时间）推进
Ledger 的 `current_time`，并在每个 tick 内驱动所有 agent 各执行一次逻辑。

#### Scenario: 100 tick 日模拟
- **WHEN** 配置一天 100 tick
- **THEN** Ledger 的 `current_time` SHALL 线性推进，结束时与实际时间差一日

### Requirement: 路径相遇检测
Orchestrator SHALL 在每 tick 结束时扫描共处于同一 `location_id` 的 agent 对，
并为每一对产出"可能相遇"候选，交给 conversation / agent 决定是否互动。

#### Scenario: 两人同到街道段
- **WHEN** A、B 同 tick 抵达 `street_main_03`
- **THEN** 候选对 `(A, B)` SHALL 出现在本 tick 的相遇列表中

### Requirement: 冲突裁决
当多个 agent 在同一 tick 请求互斥操作（如拾取同一物品、通过同一门）时，
Orchestrator SHALL 以确定性规则（例如 agent_id 字典序 + seed）解决冲突，
未获胜者收到可触发 Replan 的 interrupts。

#### Scenario: 两人抢同一把伞
- **WHEN** A、B 同 tick 调用 `pick_up_item("umbrella_01")`
- **THEN** 仅一位成功；另一位的 SimulationResult SHALL 为失败，
  error_code 指示物品被抢先
