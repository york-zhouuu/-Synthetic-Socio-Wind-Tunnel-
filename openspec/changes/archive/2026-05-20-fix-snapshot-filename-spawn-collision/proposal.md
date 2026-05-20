## Why

2026-05-20 evening: during scout publishable run, I resumed baseline
worker from `seed_43_tick276.snapshot.json` for diagnostic purposes.
The diag worker ran for 30 minutes, internally hit tick 276 again,
and **overwrote the original `seed_43_tick276.snapshot.json`** with
its diag-state. The original baseline state at sim day 0 23:00 was
permanently lost — destroying the cross-variant sim-time alignment for
the entire β=1 run.

Root cause: snapshot filenames use the worker's internal tick counter
(`seed_<N>_tick<T>.snapshot.json`). The counter resets to 0 each spawn,
so the second spawn's tick 12, 24, 36, ... collide with and overwrite
the first spawn's snapshots at the same internal tick numbers. There
is no spawn-generation identifier in the filename.

This violates the "snapshots are forensic record" implicit assumption:
once a snapshot exists, future spawns SHALL NOT overwrite it.

## What Changes

- **Add spawn identifier** (PID-based) to snapshot filename:
  `seed_<N>_pid<PID>_tick<T>.snapshot.json`
- **`snapshot_path()`** in `run_resilience/state_snapshot.py` SHALL accept
  optional `spawn_id` parameter; existing callers updated to pass
  current process PID
- **`find_latest_snapshot()`** SHALL handle both formats:
  - new `seed_<N>_pid<PID>_tick<T>.snapshot.json` (PID-prefixed)
  - legacy `seed_<N>_tick<T>.snapshot.json` (no PID)
  - selection by mtime — latest write wins across spawns
- **`prune_snapshots()`** SHALL keep last K by mtime (not by tick number)
  so multiple spawns coexist briefly before old ones age out
- **`MultiDayRunner._write_snapshot`** SHALL thread spawn_id (= os.getpid())
  into snapshot_path()
- **Backward compat**: existing legacy filenames remain discoverable +
  resumable; new writes use new format

## Capabilities

### Modified Capabilities

- `tick-level-resume`: snapshot filenames extend with spawn-PID prefix;
  resume selection moves from "highest tick" to "latest mtime" to handle
  multiple coexisting spawns

## Impact

**Affected code**:
- `synthetic_socio_wind_tunnel/run_resilience/state_snapshot.py`
  (`snapshot_path`, `find_latest_snapshot`, `prune_snapshots`)
- `synthetic_socio_wind_tunnel/orchestrator/multi_day.py`
  (`_write_snapshot`, `_write_final_snapshot_on_graceful_stop`,
  snapshot loading at resume)
- `tools/audit_resume_strategies.py` (snapshot discovery)
- `tools/watchdog_wal_deadlock.py` (snapshot reference for resume)

**Affected behavior**:
- Existing snapshot files (legacy format) still readable + resumable
- New snapshots use PID-prefixed format
- Multiple-spawn forensics now possible (each spawn's snapshots preserved
  until pruned by mtime)
- Resume picks latest by mtime, not by tick — correctly handles "respawn
  wrote tick=12 after older spawn's tick=120"
- Slight disk overhead: K snapshots per spawn × number of recent spawns
  (typically 1-3 spawns before prune ages out old ones)

**Non-goals**:
- Not changing snapshot CONTENT or schema_version
- Not adding per-spawn manifest/index file
- Not changing WAL (separate concern)
