# attention-induced-noticing-gate Specification

## Purpose
TBD - created by archiving change add-attention-induced-nearby-blindness. Update Purpose after archive.
## Requirements
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

The noticing gate SHALL combine attention attenuation with polygon-size
discount. The function `noticing_prob(a_attn: float, b_attn: float, *,
polygon_extent_m: float | None = None) -> float` MUST return:

```
max(0.0, 1.0 - max(a_attn, b_attn)) × BASE_NOTICING_RATE × spatial_factor
```

Where `BASE_NOTICING_RATE = 0.3` and `spatial_factor` accounts for whether
the agents are in a polygon larger than typical visual range:

```
spatial_factor = min(1.0, VISUAL_RANGE_M / polygon_extent_m)  if polygon_extent_m else 1.0
```

with `VISUAL_RANGE_M = 50.0`.

`noticed_pair(...)` MUST accept the same `polygon_extent_m` keyword and
forward it to `noticing_prob`. Same deterministic-hash semantics as before.

Pre-A3 bug: large polygons (e.g. Mowbray Park 1.4km extent) had two agents
"at same location_id" but at opposite ends still counted full noticing rate.
spatial_factor down-weights this — 1.4km park yields ~3.6% of base rate.

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

#### Scenario: large polygon discounts noticing
- **WHEN** noticing_prob(0.05, 0.05, polygon_extent_m=1400)
- **THEN** result SHALL be ~`0.95 × 0.3 × (50/1400)` ≈ 0.010 (much lower
  than the no-extent case)

#### Scenario: small polygon no discount
- **WHEN** noticing_prob(0.05, 0.05, polygon_extent_m=30)
- **THEN** result SHALL equal `noticing_prob(0.05, 0.05)` (no extent factor)

### Requirement: Encounter noticing SHALL apply transit drive-by penalty

The `memory._is_encounter_noticed(...)` SHALL accept `a_movement_count: int`
and `b_movement_count: int` parameters representing each agent's intra-tick
movement segment count.

The transit penalty MUST inflate the agents' effective attention prior to
the noticing computation:

```
transit_factor = 1.0 / (1.0 + max(a_movement_count, b_movement_count) / 5.0)
effective_attn = real_attn + (1.0 - transit_factor) × 0.5
```

This penalizes drive-by encounters: an agent traversing 25 segments this
tick (driver) has factor 0.17 → effective_attn += 0.42 → noticing drops
substantially. Two settled agents (0 moves) get factor 1.0 → no penalty.

The caller in `memory.process_tick` MUST construct a `moves_this_tick` dict
from `tick_result.movement_traces` and pass per-agent counts to
`_is_encounter_noticed`.

#### Scenario: settled agents — no penalty
- **WHEN** _is_encounter_noticed called with both agents stationary
  (a_movement_count=0, b_movement_count=0)
- **THEN** transit_factor SHALL be 1.0; no attention penalty applied;
  noticing_prob SHALL match the pre-fix value

#### Scenario: heavy driver — strong penalty
- **WHEN** _is_encounter_noticed called with a_movement_count=25
- **THEN** transit_factor SHALL be ≈ 0.17; effective_attn for that agent
  SHALL be increased by ≈ 0.42; noticing_prob SHALL drop significantly

#### Scenario: walker meeting driver
- **WHEN** walker (5 moves) meets driver (20 moves)
- **THEN** transit_factor = 1/(1 + 20/5) = 0.2 → moderate-to-strong penalty

