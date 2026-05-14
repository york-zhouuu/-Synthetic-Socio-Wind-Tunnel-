## ADDED Requirements

### Requirement: Phone attention state SHALL be tracked per agent

The system SHALL track a dynamic `phone_attention: float` value for every
agent. The value MUST be in the range `[0.0, 1.5]` and represent the share of
the agent's cognitive bandwidth currently consumed by phone activity.

Initial value SHALL be `min(1.0, profile.digital.daily_screen_hours / 16.0)`
(the baseline ambient screen-time share derived from waking-hour screen use).

#### Scenario: heavy screen user has higher baseline phone_attention
- **WHEN** agent has `digital.daily_screen_hours = 8.0`
- **THEN** the initial `phone_attention` SHALL be `0.5` (8/16)

#### Scenario: light screen user has near-zero baseline
- **WHEN** agent has `digital.daily_screen_hours = 1.0`
- **THEN** initial `phone_attention` SHALL be approximately `0.0625` (1/16)

### Requirement: phone_attention SHALL decay per tick toward baseline

Each simulation tick, the system MUST apply geometric decay:
`phone_attention[t+1] = max(baseline, phone_attention[t] × 0.85)`.

The decay factor 0.85 yields a half-life of approximately 4 ticks
(20 simulated minutes at 5-min tick).

#### Scenario: decay returns to baseline over time
- **WHEN** phone_attention=1.0 with baseline=0.2; tick 10 times with no notifications
- **THEN** phone_attention SHALL be ≈ `max(0.2, 1.0 × 0.85**10) = max(0.2, 0.197)` ≈ 0.2

### Requirement: Notification delivery SHALL increase phone_attention

Notification delivery MUST accumulate phone_attention via the delta formula
below. When a `FeedItem` is delivered to an agent via `AttentionService`, the
delta added to that agent's `phone_attention` SHALL be:

```
delta = NOTIFICATION_BASE_DELTA
      × urgency_factor
      × (1 + (responsiveness - 0.5) × NOTIFICATION_RESPONSIVENESS_GAIN)
      × (0.5 + openness)
```

Where:
- `NOTIFICATION_BASE_DELTA = 0.10`
- `NOTIFICATION_RESPONSIVENESS_GAIN = 2.0`
- `urgency_factor` is `feed_item.urgency` (already ∈ [0, 1])
- `responsiveness = agent.profile.digital.notification_responsiveness`
- `openness = agent.profile.personality.openness`

Result MUST be clamped to `[0, 1.5]`.

#### Scenario: medium-urgency push from responsive agent
- **WHEN** agent responsiveness=0.6, openness=0.5, urgency=0.5, current attention=0.2
- **THEN** new attention ≈ `min(1.5, 0.2 + 0.1 × 0.5 × (1 + 0.2) × 1.0)` ≈ 0.26

### Requirement: NoticingGate SHALL gate encounters via attention

The function `noticing_prob(a_attn: float, b_attn: float) -> float` MUST return:

```
max(0.0, 1.0 - max(a_attn, b_attn)) × BASE_NOTICING_RATE
```

Where `BASE_NOTICING_RATE = 0.3`.

Encounter pairing via `noticed_pair(a_attn, b_attn, seed, day, tick, pair_key)
-> bool` MUST seed a deterministic RNG from `hash((seed, day, tick, *pair_key))`
and return `rng.random() < noticing_prob(a_attn, b_attn)`. Same arguments MUST
yield the same boolean across runs.

#### Scenario: both agents on phone → low noticing
- **WHEN** a_attn=0.9, b_attn=0.8
- **THEN** noticing_prob == `max(0, 1 - 0.9) × 0.3` == 0.03 (~3% noticed)

#### Scenario: both agents not on phone → ideal noticing
- **WHEN** a_attn=0.05, b_attn=0.05
- **THEN** noticing_prob ≈ `0.95 × 0.3` ≈ 0.285 (~29% noticed)

#### Scenario: deterministic noticing
- **WHEN** noticed_pair called twice with same args
- **THEN** both calls SHALL return the same boolean

#### Scenario: one agent on phone blocks noticing
- **WHEN** a_attn=0.1, b_attn=0.95
- **THEN** noticing_prob == `0.05 × 0.3` == 0.015 (one-side glued = both blind)
