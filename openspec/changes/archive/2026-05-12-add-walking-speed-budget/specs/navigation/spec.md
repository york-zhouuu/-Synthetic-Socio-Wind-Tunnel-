## ADDED Requirements

### Requirement: find_route SHALL accept a mode parameter for edge filtering

The `find_route` method SHALL accept a new keyword argument `mode`. The
signature `NavigationService.find_route(from_location, to_location, ...,
mode="any")` MUST accept a string `mode` argument with possible values
`{"walking", "driving", "any"}`. The filtering semantics are:

- `mode="walking"`: SHALL skip neighbour edges whose neighbour OutdoorArea
  has `access_mode == "motor"` — car-less agents will not be routed onto
  motorways.
- `mode="driving"`: SHALL NOT filter — drivers are allowed to use any edge
  including pedestrian-only segments (interpreted as "park + walk last leg").
- `mode="any"`: SHALL NOT filter — backward-compatible default; previously
  the only behaviour.

The mode SHALL only affect edge filtering inside the A* loop. Heuristic
function and other A* internals SHALL be unchanged.

#### Scenario: walker route avoids motorway
- **WHEN** `find_route(home, work, mode="walking")` is called and a
  motorway shortcut would otherwise be selected
- **THEN** the returned route SHALL contain no NavigationStep whose
  `to_location` is an OutdoorArea with `access_mode == "motor"`

#### Scenario: driver route unrestricted
- **WHEN** `find_route(home, work, mode="driving")` is called
- **THEN** the result SHALL match `find_route(home, work, mode="any")`
  (no edge filtering)

#### Scenario: mode defaults to any (backward compat)
- **WHEN** `find_route(home, work)` is called without specifying mode
- **THEN** behaviour SHALL be identical to the previous implementation
  (no filtering, no exceptions raised)

#### Scenario: walker fallback when route impossible
- **WHEN** the only path from A to B requires traversing a motor-only edge
  AND `mode="walking"` was requested
- **THEN** `find_route` SHALL return `success=False`. The orchestrator
  caller MAY retry with `mode="any"` to obtain a fallback path
