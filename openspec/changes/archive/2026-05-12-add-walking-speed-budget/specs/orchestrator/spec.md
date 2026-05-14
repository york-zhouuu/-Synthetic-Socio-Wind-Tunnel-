## ADDED Requirements

### Requirement: Orchestrator SHALL enforce per-tick walking-distance budget

The orchestrator MUST limit how far an agent travels in a single tick.
`Orchestrator.__init__` SHALL accept a new keyword parameter
`walking_speed_m_per_min: float = 80.0` representing the global fallback
travel pace (used only when an agent lacks a per-agent speed value).

`_dispatch_move(agent_id, intent, agent)` MUST:

1. Compute `tick_budget_m = tick_minutes × agent_speed`, where `agent_speed`
   reads `agent.profile.walking_speed_m_per_min` and falls back to the
   orchestrator-level default.
2. Walk the route step-by-step, accumulating distance, and STOP after the
   first step whose accumulated distance reaches or exceeds `tick_budget_m`
   (always advance at least one step so a single oversized segment doesn't
   stall the agent).
3. Save unwalked NavigationSteps to `agent._in_flight_route_remaining` and
   `agent._in_flight_target = intent.to_location` so the next tick resumes
   from the same path.
4. Clear `_in_flight_*` when the route is fully consumed.

If a subsequent tick arrives with a different `intent.to_location` than
`agent._in_flight_target`, the orchestrator SHALL discard the stale
in-flight state and recompute a fresh route.

#### Scenario: long route spans multiple ticks
- **WHEN** an 80 m/min agent (400m budget) initiates a 1.2km route
- **THEN** the move SHALL complete across approximately 3 ticks; each
  intermediate tick SHALL leave `agent._in_flight_route_remaining` non-empty;
  the final tick SHALL clear it

#### Scenario: short route completes in one tick
- **WHEN** an 80 m/min agent moves to a destination 200m away (single tick
  budget covers it)
- **THEN** `agent._in_flight_route_remaining` SHALL be empty after the move

#### Scenario: target change invalidates in-flight state
- **WHEN** `_in_flight_target = "cafe_A"` and a new MoveIntent arrives with
  `to_location = "cafe_B"`
- **THEN** the orchestrator SHALL discard the cafe_A route and recompute
  to cafe_B from the agent's current location

#### Scenario: at least one segment per tick (no stall)
- **WHEN** the only available segment is 500m (exceeds 400m budget for a
  walker)
- **THEN** the agent SHALL still advance one segment that tick; budget
  is treated as advisory, not absolute, for single-segment progress

### Requirement: Orchestrator SHALL call NavigationService with agent-appropriate mode

`_dispatch_move` MUST pick `mode = "driving"` when
`agent.profile.prefer_driving is True`, else `mode = "walking"`. If the
mode-filtered route returns `success=False`, the orchestrator MAY retry
with `mode="any"` as a fallback to avoid hard-failing on edge cases (e.g.
a tagged pedestrian path leading to the final building).

#### Scenario: walker requests walking mode
- **WHEN** `_dispatch_move` runs for an agent with
  `profile.prefer_driving == False`
- **THEN** the first `nav.find_route` call SHALL pass `mode="walking"`

#### Scenario: driver requests driving mode
- **WHEN** `_dispatch_move` runs for an agent with
  `profile.prefer_driving == True`
- **THEN** the first `nav.find_route` call SHALL pass `mode="driving"`

#### Scenario: fallback to any if mode-filtered fails
- **WHEN** `nav.find_route(..., mode="walking")` returns `success=False`
- **THEN** the orchestrator SHALL retry with `nav.find_route(..., mode="any")`
  before raising a Route-not-found error
