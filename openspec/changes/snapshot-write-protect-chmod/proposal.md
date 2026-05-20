## Why

R1 (PID-prefixed filenames) prevents same-PID collision but doesn't
defend against deliberate `> file` or external `cp -f` overwrite.
R2 (auto-backup on resume) catches the resume case. Defense in depth:
chmod 0444 (read-only) right after atomic write closes the per-file
gap completely.

Operator typo (e.g. `cat foo > seed_42_tick120.snapshot.json` instead
of `cat foo > newfile.json`) currently silently destroys a snapshot.
With 0444, the write fails loudly with permission denied.

## What Changes

- `SimulationCheckpoint.write_atomic` SHALL chmod 0444 the final file
  immediately after `os.rename(tmp, path)`
- `DayCheckpointWriter.write_partial` and `write_day_summary` SHALL do
  the same
- `prune_snapshots` SHALL chmod +w before unlink (Python `os.unlink`
  on read-only file works on macOS/Linux when parent dir is writable,
  but be explicit to avoid Windows/edge cases)
- Backup tool / forensic operations SHALL document `chmod +w <file>`
  before modification
- E2E test: write snapshot → assert file mode is 0444 → assert
  overwrite raises PermissionError → assert prune still succeeds

## Capabilities

### Modified Capabilities

- `tick-level-resume`: snapshot / partial / summary files SHALL be
  chmod 0444 after atomic write

## Impact

**Affected code**:
- `synthetic_socio_wind_tunnel/run_resilience/state_snapshot.py`
  (`SimulationCheckpoint.write_atomic` + `prune_snapshots`)
- `synthetic_socio_wind_tunnel/run_resilience/checkpoint.py`
  (`DayCheckpointWriter.write_partial` + `write_day_summary`)

**Affected behavior**:
- Accidental overwrites caught by OS at write time
- Legitimate prune still works (explicit chmod +w in prune logic)
- Manual operator inspection unchanged (read-only is fine for read)

**Non-goals**:
- NOT changing WAL file permissions (append-only — would break appends)
- NOT changing JSONL telemetry files (events / memstat / llm)
- NOT atomic checksums (separate concern)
