## ADDED Requirements

### Requirement: TickResult SHALL expose end-of-tick agent positions

The frozen dataclass `TickResult` MUST include an `entity_locations: tuple[tuple[str, str], ...]`
field defaulting to empty tuple. Each tuple element SHALL be a
`(agent_id, location_id)` pair representing the agent's location at the
end of this tick.

Orchestrator `_run_tick` MUST populate this field from the same
`entity_locations` dict it already computes for encounter detection (B9 fix).

The field SHALL be backward compatible: existing callers that construct
`TickResult(...)` without `entity_locations` MUST continue to work.

#### Scenario: orchestrator emits entity locations in tick result
- **WHEN** `_run_tick` completes a tick with 3 agents at locations a/b/c
- **THEN** the returned TickResult.entity_locations SHALL contain exactly
  3 pairs, one per agent

#### Scenario: backward compat for direct TickResult construction
- **WHEN** test code calls `TickResult(tick_index=0, simulated_time=..., commits=(), encounter_candidates=())`
  without entity_locations
- **THEN** the field SHALL default to empty tuple; no exception raised
