## ADDED Requirements

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
