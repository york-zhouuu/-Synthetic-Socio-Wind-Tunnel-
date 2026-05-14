## ADDED Requirements

### Requirement: SocialGraphService SHALL distinguish physical vs noticed encounters

`SocialGraphService` MUST provide two distinct recording methods:

- `record_physical_encounter(agent_a, agent_b, tick, day_index=0) -> Tie`:
  records that two agents shared a location at this tick. MUST NOT increment
  tie.strength (geographic colocation alone does not build social bonds).
- `record_noticed_encounter(agent_a, agent_b, tick, day_index=0) -> Tie`:
  records that the two agents actually noticed each other through the
  attention-noticing gate. MUST increment tie.strength via the existing
  `_strength(encounter_count)` formula.

The legacy `record_encounter` MAY remain as an alias for
`record_noticed_encounter` (preserving prior tests that expected strength
to grow per call), but new caller code SHALL use the explicit variant.

#### Scenario: physical encounter does NOT grow tie strength
- **WHEN** `record_physical_encounter("a", "b", tick=1)` is called 5 times
  on distinct ticks
- **THEN** the returned Tie.strength SHALL be 0.0 (no noticed encounters yet)

#### Scenario: noticed encounter grows tie strength
- **WHEN** `record_noticed_encounter("a", "b", tick=t)` for `t = 1..10`
- **THEN** Tie.strength SHALL be `10 / (10 + K)` where K is the service's K
  parameter

#### Scenario: mixed physical + noticed
- **WHEN** 5 physical_encounters + 2 noticed_encounters on distinct ticks
- **THEN** Tie.encounter_count SHALL be 7 (physical contact count) but
  Tie.strength SHALL reflect only noticed (`2 / (2 + K)`)
