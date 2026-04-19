# conversation — 能力增量

## ADDED Requirements

### Requirement: 广播式多方对话
系统 SHALL 支持多名 agent 同时在同一位置进行广播式对话：
每一条发言 SHALL 被所在位置所有听力范围内的 agent 接收。

- 发言 SHALL 产出 `WorldEvent(event_type=SPEECH, audible_range=...)`，
  保持与 perception 一致。

#### Scenario: 咖啡桌三人谈话
- **WHEN** A、B、C 同桌，A 发言
- **THEN** B、C 的下一 tick perception 输入 SHALL 包含 A 的发言文本

### Requirement: 信息跳数（hops）追踪
每条对话内容 SHALL 携带 `source_hack_id` 与 `hops: int`；当信息被另一 agent
转述时，hops += 1。

- metrics SHALL 能按 hops 分布统计干预内容的扩散。

#### Scenario: 从海报到三度转述
- **WHEN** agent X 见到 PolicyHack 海报后转述给 Y，Y 再转述给 Z
- **THEN** Z 收到的对话消息的 `hops` SHALL 为 2（若海报为 0）

### Requirement: 对话作为 Replan 打断
对话中出现与 agent 当前 PlanStep 冲突的信息（例如被邀请改去别处）时，
对话模块 SHALL 产生 `interrupt` 交给 `planner.replan`。

#### Scenario: 临时聚会邀请
- **WHEN** A 对 B 说"晚上七点来我家吃饭"
- **THEN** B 的 Planner SHALL 收到 interrupt，视接受/拒绝决定是否重规划
