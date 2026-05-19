## MODIFIED Requirements

### Requirement: DialogueService 必须有 rolling cleanup

`DialogueService` SHALL 在每次 `on_day_end` hook（或等价的 day 边界）evict 满足以下条件的 dialogue（位于 `synthetic_socio_wind_tunnel/conversation/dialogue_service.py`）：

- `dialogue.started_day_index < before_day_index`（即"启动于 grace_days 之前"）— `before_day_index = max(0, current_day_index - grace_days)`，grace_days 默认 2
- AND `dialogue.ended_tick is not None`（不动 in-progress）

**2026-05-20 fix-dialogue-eviction-tick-semantic**：从 `before_tick: int` (global) 改为 `before_day_index: int` (day scale)。先前 caller 传 `(day - grace) * 288` (global tick) 而 filter 比较 `d.ended_tick` (per-day 0-287) → mismatch 永远 True → 所有 ended dialogue 立刻被 demote，grace 形同虚设。`Dialogue` dataclass 加 `started_day_index: int = 0` 字段携带 day 维度。

evict 操作 SHALL：
- 保留 `dialogue_id`、`participants`、`ended_tick`、`message_count` 摘要
  到 `_dialogue_summaries: dict[str, DialogueSummary]`
- 释放 `Dialogue.messages: list[DialogueMessage]`、长 prompt 上下文等 detail
- 通过 `to_snapshot_state` 序列化时只序列化 summaries，不带 full messages

`DialogueService` SHALL 暴露 `retrieve_summary(dialogue_id) -> DialogueSummary
| None` 给下游 metric / narrative 用；下游若需 full messages SHALL 改为
通过外部 DialogueArchive 持久化路径（backlog 1.12，暂不实施）。

#### Scenario: day 边界 evict 老对话

- **WHEN** 在 day 5 触发 day_end hook，`_dialogues` 含 4 个 ended dialogue
  started_day_index 分别 1 / 2 / 3 / 4；grace_days=2 → before_day_index=3
- **THEN** started_day=1, 2 的 dialogue SHALL 被 evict 到
  `_dialogue_summaries`；started_day=3, 4 的 dialogue SHALL 留在
  `_dialogues`；`retrieve_summary` SHALL 对所有 4 个返回非 None

#### Scenario: in-progress dialogue 不被 evict

- **WHEN** day 10 时 `_dialogues` 里有一个开始于 day 1、ended_tick is None
- **THEN** 该 dialogue SHALL 留在 `_dialogues` 完整不动；`_dialogue_summaries`
  不含此 dialogue_id

#### Scenario: before_day_index <= 0 时 no-op

- **WHEN** before_day_index=0（早期 day_index < grace_days 时的常态）
- **THEN** 函数 SHALL 立即返回 0，不修改任何 dialogue 状态
