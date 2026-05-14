## ADDED Requirements

### Requirement: compute_notification_delta SHALL apply cumulative-fatigue

The `compute_notification_delta` function SHALL apply exponential per-day
fatigue decay. The signature `compute_notification_delta(urgency,
responsiveness, openness, *, notifications_received_today: int = 0)`
MUST accept the daily count and decay with `FATIGUE_HALFLIFE_N = 8`:

```
delta_n = base_delta × exp(-ln(2) × notifications_received_today / 8)
```

This captures real-world desensitization: the 1st push of the day fires
full attention; the 8th fires half; the 16th fires a quarter.

#### Scenario: first notification full delta
- **WHEN** `compute_notification_delta(0.5, 0.5, 0.5, notifications_received_today=0)`
- **THEN** result SHALL equal `compute_notification_delta(0.5, 0.5, 0.5)`
  (no fatigue at n=0)

#### Scenario: 8th notification half delta
- **WHEN** comparing `compute_notification_delta(0.5, 0.5, 0.5, n=0)` vs
  `compute_notification_delta(0.5, 0.5, 0.5, n=8)`
- **THEN** the n=8 value SHALL be approximately half the n=0 value (±5%)

#### Scenario: 16th notification quarter delta
- **WHEN** comparing n=0 vs n=16
- **THEN** the n=16 value SHALL be approximately one-quarter the n=0 value

### Requirement: AttentionService SHALL track daily notification count per agent

`AttentionService` MUST maintain `_notifications_today: dict[agent_id, int]`
counting notifications delivered to each agent within the current sim day.

The counter MUST:
1. Increment in `_accumulate_phone_attention(agent_id, feed_item)` after the
   delta is added to phone_attention
2. Be readable internally for the fatigue calculation passed to
   `compute_notification_delta(...)`
3. Reset on day boundary via `reset_daily_counters()` (caller invokes at
   day-start hook)

Backward compat: existing callers that don't invoke `reset_daily_counters()`
SHALL see counters accumulate across day boundaries — equivalent to "no day
reset" behavior, slightly different from intended but no exception raised.

#### Scenario: counter increments per delivery
- **WHEN** `deliver_feed_item` succeeds for agent "a1" once
- **THEN** `service._notifications_today["a1"]` SHALL == 1

#### Scenario: reset clears counters
- **WHEN** `reset_daily_counters()` is called after 5 deliveries to "a1"
- **THEN** `service._notifications_today.get("a1", 0)` SHALL == 0

#### Scenario: fatigue applied via service
- **WHEN** the service delivers 10 notifications to agent "a1" in one day,
  with identical urgency/responsiveness/openness for each
- **THEN** the per-notification phone_attention delta SHALL decrease
  monotonically as the count rises
