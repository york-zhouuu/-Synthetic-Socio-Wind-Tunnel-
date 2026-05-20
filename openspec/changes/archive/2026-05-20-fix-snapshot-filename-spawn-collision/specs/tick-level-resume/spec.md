## ADDED Requirements

### Requirement: snapshot 文件名 SHALL 含 spawn 唯一标识防覆写

Snapshot files MUST be named `seed_<N>_pid<PID>_tick<T>.snapshot.json`
where `<PID>` is the writing process's `os.getpid()` value. This
prevents a respawned worker from overwriting an earlier spawn's
snapshots at colliding internal tick numbers.

Backward compatibility: existing legacy-format files
`seed_<N>_tick<T>.snapshot.json` (no PID prefix) remain readable +
resumable. New writes use the PID-prefixed format.

#### Scenario: 两次 spawn 各自的 tick 12 snapshot 不互相覆写

- **GIVEN** worker A (PID 100) writes `seed_42_pid100_tick12.snapshot.json`
- **WHEN** worker A is killed; worker B (PID 200) starts as respawn and
  writes `seed_42_pid200_tick12.snapshot.json`
- **THEN** both files SHALL exist on disk simultaneously
- **AND** worker A's snapshot content SHALL remain readable (not corrupted
  by worker B's write)

#### Scenario: find_latest_snapshot 跨 spawn 选 mtime 最新

- **GIVEN** disk has `seed_42_pid100_tick120.snapshot.json` (mtime T1)
  AND `seed_42_pid200_tick12.snapshot.json` (mtime T2 > T1)
- **WHEN** `find_latest_snapshot(output_dir, seed=42)` is called
- **THEN** the result SHALL be `seed_42_pid200_tick12.snapshot.json`
  (latest mtime), NOT pid100's higher-numbered tick

#### Scenario: legacy 文件名仍 discoverable

- **GIVEN** disk has only `seed_42_tick120.snapshot.json` (legacy, no PID)
- **WHEN** `find_latest_snapshot(output_dir, seed=42)` is called
- **THEN** the legacy file SHALL be returned (back-compat)

### Requirement: snapshot 清理按 mtime 而非按 tick 编号

`prune_snapshots(output_dir, seed, keep=K)` MUST select the K
most-recently-written files (by mtime) to retain, and delete the rest.
Previous behavior (keep K highest tick numbers) is incompatible with
PID-prefixed naming because two spawns can have overlapping tick ranges.

#### Scenario: prune 用 mtime 排序，最新 K 个保留

- **GIVEN** 5 snapshots with mtimes T1 < T2 < T3 < T4 < T5
- **WHEN** `prune_snapshots(output_dir, seed=42, keep=2)` is called
- **THEN** files with mtimes T4 and T5 SHALL remain
- **AND** files with mtimes T1, T2, T3 SHALL be deleted
