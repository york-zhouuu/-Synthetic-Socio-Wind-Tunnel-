## ADDED Requirements

### Requirement: snapshot 文件写完 SHALL chmod 0444

`SimulationCheckpoint.write_atomic` MUST execute `os.chmod(path, 0o444)`
immediately after the `os.rename(tmp, path)` atomic-write step. The
file becomes read-only at the OS level — any attempt to overwrite via
`>` redirection, `cp`, or `open(..., "w")` raises PermissionError
loudly instead of silently destroying the snapshot.

#### Scenario: snapshot 写完是 read-only

- **GIVEN** `SimulationCheckpoint.write_atomic(path)` succeeds
- **WHEN** `os.stat(path).st_mode & 0o777` is read
- **THEN** value SHALL be 0o444

#### Scenario: overwrite blocked

- **GIVEN** an existing snapshot file (chmod 0o444)
- **WHEN** another process tries `open(path, "w")`
- **THEN** SHALL raise `PermissionError`

### Requirement: SHALL chmod 0444 day-summary and partial files

Day-summary and partial-day files SHALL be chmod 0o444 (read-only)
after atomic rename, matching the snapshot file protection. Both
`DayCheckpointWriter.write_partial` and
`DayCheckpointWriter.write_day_summary` implement this.

#### Scenario: day_summary chmod 0444

- **GIVEN** `DayCheckpointWriter.write_day_summary(...)` succeeds
- **WHEN** `os.stat(path).st_mode & 0o777` is read
- **THEN** value SHALL be 0o444

### Requirement: prune SHALL chmod 写权限再删

`prune_snapshots(output_dir, seed, keep=K)` MUST chmod 0o644 the
file to be deleted BEFORE calling `os.unlink`. This ensures legitimate
pruning works regardless of platform delete-on-readonly semantics.

#### Scenario: prune 能删 chmod 0444 文件

- **GIVEN** 5 snapshots all at chmod 0o444
- **WHEN** `prune_snapshots(output_dir, seed, keep=2)` is invoked
- **THEN** 3 oldest SHALL be deleted (no PermissionError raised)
- **AND** the surviving 2 SHALL remain at chmod 0o444
