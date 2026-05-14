## ADDED Requirements

### Requirement: PositionTraceRecorder SHALL record sparse position-change events

The class `synthetic_socio_wind_tunnel.metrics.PositionTraceRecorder` MUST
subscribe to `Orchestrator.on_tick_end` and record `PositionChange` events
ONLY when an agent's `location_id` differs from its previously recorded value.

This sparseness ensures that storage scales with movement volume (~20
events/agent/day), not with tick count × agent count.

The recorder MUST expose:
- `on_tick_end(tick_result: TickResult) -> None`: hook signature
- `to_dict() -> dict`: serializable form
- `write(path: Path) -> None`: write JSON to a file
- `total_changes: int` property: total recorded change count

The output JSON SHALL conform to schema `position_trace_v1` containing
`n_agents`, `n_changes`, and a `changes` list where each entry has
`tick: int`, `day: int`, `agent_id: str`, `location_id: str`.

#### Scenario: stationary agent yields no extra records
- **WHEN** the same agent's location is unchanged across 10 consecutive ticks
- **THEN** only 1 PositionChange event SHALL be recorded (the first sighting)

#### Scenario: position change recorded
- **WHEN** agent A at location "home" on tick 0, then "cafe" on tick 5
- **THEN** the recorder SHALL store 2 changes:
  `(tick=0, agent_id="A", location_id="home")` and
  `(tick=5, agent_id="A", location_id="cafe")`

#### Scenario: empty location skipped
- **WHEN** an agent's location_id is empty string at the tick boundary
- **THEN** the recorder SHALL NOT record a change

#### Scenario: companion JSON file produced by suite
- **WHEN** `tools/run_variant_suite.py` finishes a seed run
- **THEN** a `seed_<N>_positions.json` file SHALL exist next to
  `seed_<N>.json` inside `variant_<name>/`; its `changes` array SHALL be
  non-empty for any non-trivial run
