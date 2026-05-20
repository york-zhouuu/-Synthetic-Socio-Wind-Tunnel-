## Why

2026-05-20 scout observed: when a watchdog-respawned worker resumes
from a snapshot, `ledger.current_time` is restored to whatever it was
when the snapshot was written. The orchestrator then runs
`day_index=0`'s 288-tick loop, advancing ledger by 5 min per tick.
If the snapshot was at, say, sim day 0 23:00, the orchestrator's
"day_index=0 loop" actually covers sim day 0 23:00 → day 1 23:00.

Net effect: **`day_index` and `ledger.current_time` drift apart**.
Per-day summary metrics get tagged with orchestrator `day_index=0`
but the actual sim time recorded inside is mid-day-1. Cross-variant
contest comparison gets confused.

Underlying issue: snapshot's `ledger.current_time` is treated as
canonical. There's no "anchor" tying `day_index` back to a known
start_date. Resume can silently drift the calendar.

## What Changes

- `SimulationCheckpoint` schema gains `start_date_anchor_iso: str |
  None` field — the original start_date the run was launched with.
  Backward compatible (defaults None for legacy snapshots).
- `MultiDayRunner._write_snapshot` populates `start_date_anchor_iso`
  from `start_date` arg passed to `run_multi_day`.
- `MultiDayRunner.run_multi_day` on resume SHALL verify:
  - if snapshot has `start_date_anchor_iso` and it doesn't match the
    current `start_date` arg → log WARNING (potential desync)
  - compute expected `ledger.current_time` = `start_date_anchor +
    snap.day_index * 24h + snap.tick_index * 5min`
  - if actual `ledger.current_time` deviates from expected by > 1h
    → log WARNING with concrete drift amount
- New regression test verifies anchor field round-trips + drift
  detection works
- NOT auto-correcting drift (that would break legitimate use cases
  where ledger advanced beyond day boundary). Just DETECT + WARN.

## Capabilities

### Modified Capabilities

- `tick-level-resume`: snapshot SHALL carry `start_date_anchor_iso`;
  resume SHALL detect ledger-vs-day_index drift

## Impact

**Affected code**:
- `synthetic_socio_wind_tunnel/run_resilience/state_snapshot.py`
  (`SimulationCheckpoint` model field)
- `synthetic_socio_wind_tunnel/orchestrator/multi_day.py`
  (`_write_snapshot` populates anchor, `run_multi_day` resume path
  validates drift)

**Affected behavior**:
- New snapshot field — back-compat for legacy snapshots (None default)
- Resume WARN log when ledger drifted from expected — operator gets
  early signal before contest data is generated

**Non-goals**:
- NOT auto-correcting drift (preserves semantic of "snapshot's
  ledger.current_time is source of truth")
- NOT changing per-day summary write timing
- NOT cross-variant anchor coordination (separate R5 change)
