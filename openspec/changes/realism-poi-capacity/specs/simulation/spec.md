## ADDED Requirements

### Requirement: move_entity MUST handle full-capacity locations

`SimulationService.move_entity(agent_id, dest_location)` SHALL — before
finalizing arrival — check `POIHeatModel.is_full(dest_location)`. If full:

1. With probability ~ 30%: defer arrival (re-emit MoveIntent same target next tick)
2. With probability ~ 30%: redirect to nearest same-area-type alternative within 1000m
3. With probability ~ 40%: abandon (set agent's plan step to "abandoned"; emit MemoryEvent kind="abandon_attempt")

If `capacity = None`, location is unbounded — skip overflow check, behave as today.

`POIHeatModel.register_arrival` SHALL be invoked exactly once per successful
arrival; `register_departure` exactly once per departure.

#### Scenario: full cafe abandons or redirects new arrivals
- **WHEN** cafe_main capacity=5, 5 agents arrived, agent_X tries move_entity → cafe_main
- **THEN** move_entity outcome SHALL be one of: defer / redirect / abandon (per probability)

#### Scenario: unbounded park always succeeds
- **WHEN** park has capacity=None, 1000 agents try arrival
- **THEN** all 1000 SHALL succeed; POIHeatModel.current_occupancy SHALL == 1000
