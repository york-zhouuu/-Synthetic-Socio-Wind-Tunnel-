## ADDED Requirements

### Requirement: AttentionService SHALL expose phone_attention state API

`AttentionService` MUST provide three new methods to manage per-agent
phone attention state:

- `get_phone_attention(agent_id: str) -> float`: returns current value
  (or baseline if agent unseen)
- `set_phone_attention_baseline(agent_id: str, baseline: float) -> None`:
  registers an agent's resting-state attention share (typically called
  during simulation setup from `profile.digital.daily_screen_hours / 16`)
- `tick_decay_all() -> None`: applies geometric decay to every tracked agent

Internal state is a dict `_phone_attention: dict[str, float]` + a
companion `_phone_attention_baseline: dict[str, float]`.

#### Scenario: get_phone_attention returns baseline for unseen agent
- **WHEN** `service.set_phone_attention_baseline("a1", 0.2)`, then
  `service.get_phone_attention("a1")`
- **THEN** returns `0.2`

#### Scenario: tick_decay_all reduces all tracked values
- **WHEN** two agents at 0.8 and 1.0, both with baseline 0.1, then `tick_decay_all`
- **THEN** values become `max(0.1, 0.8 × 0.85)` ≈ 0.68 and `max(0.1, 1.0 × 0.85)` = 0.85

### Requirement: AttentionService.deliver_feed_item SHALL accumulate phone_attention

The `deliver_feed_item` method MUST update the recipient's phone_attention.
When a feed item is successfully delivered to an agent, it SHALL accumulate
that agent's `phone_attention` by the delta formula specified in the
`attention-induced-noticing-gate` capability.

Delta MUST be computed using `agent_profile` (passed by caller) for
`digital.notification_responsiveness` and `personality.openness`. When
profile is None, fallback is `responsiveness=0.5, openness=0.5`.

#### Scenario: delivered notification updates attention
- **WHEN** baseline=0.2, current=0.2, `deliver_feed_item(item, agent_id, profile)`
  with `item.urgency=0.6`, `responsiveness=0.7`, `openness=0.5`
- **THEN** attention after delivery > 0.2

#### Scenario: suppressed notification does NOT update attention
- **WHEN** delivery fails (suppressed_by_bias=True)
- **THEN** attention SHALL remain unchanged
