## ADDED Requirements

### Requirement: SHALL stream snapshot serialization to avoid 2x RSS peak

`SimulationCheckpoint.write_atomic` MUST use streaming JSON serialization
(via `orjson` with file-handle write, or equivalent generator-based approach)
to avoid building the entire JSON string in memory before write. This keeps
RSS peak during write ≤ 1.2× working set (vs current ~2× peak from
`json.dumps(full_dict)` then write).

The output bytes MUST be byte-identical to the legacy `json.dumps(...)`
output to preserve schema_version compatibility and snapshot read-roundtrip
determinism.

#### Scenario: RSS peak during write bounded

- **GIVEN** a SimulationCheckpoint with ~4M memory events (~2GB in-memory)
- **WHEN** `write_atomic(path)` is invoked
- **THEN** measured RSS peak during write SHALL be ≤ working_set_before_write
  × 1.2 (vs current 2.0×)

#### Scenario: streaming write produces byte-identical output

- **GIVEN** the same SimulationCheckpoint instance
- **WHEN** serialized via streaming write to file A and via
  `json.dumps(self.model_dump())` to file B
- **THEN** `file A bytes` SHALL equal `file B bytes`
- **AND** both files SHALL load via `SimulationCheckpoint.read(path)` to
  the same checkpoint state (round-trip equivalent)
