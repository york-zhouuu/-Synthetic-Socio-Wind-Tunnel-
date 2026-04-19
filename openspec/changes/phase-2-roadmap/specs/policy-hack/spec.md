# policy-hack — 能力增量

## ADDED Requirements

### Requirement: 统一干预注入接口
系统 SHALL 提供 `inject(hack: PolicyHack)`，支持至少 5 类干预：
广告牌 / 应用推送 / 社区海报 / 社区活动事件 / 邻里消息。

- `PolicyHack` SHALL 包含：`hack_id`、`channel`、`content`、`targets`
  （位置或人群过滤器）、`active_window`（时间段）、`seed`。

#### Scenario: 在某街道投放海报
- **WHEN** 调用 `inject(PolicyHack(channel="poster", location="street_main_03", ...))`
- **THEN** 从 `active_window` 开始，perception 层 SHALL 能让途经 agent 看到
  该海报内容，并可触发 Replan

### Requirement: 可感知通道解耦
干预内容 SHALL 通过 perception / conversation 的既有通道进入 agent 视野
（视觉、听觉、推送流），不得绕开感知层直接写入 agent 记忆。

#### Scenario: 不在场不感知
- **WHEN** 海报仅投放在 `street_main_03`，agent 全天未经过该位置
- **THEN** 该 agent 的感知中 SHALL 不出现此海报内容
