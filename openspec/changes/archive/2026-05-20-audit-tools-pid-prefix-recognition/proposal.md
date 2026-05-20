## Why

R1 introduced PID-prefixed snapshot filenames:
`seed_<N>_pid<PID>_tick<T>.snapshot.json`. But
`tools/audit_resume_strategies.py` still globs only the legacy format:
`seed_{seed}_tick*.snapshot.json`. Result: post-R1 snapshots are
INVISIBLE to the audit tool — cell state gets misreported as "no
snapshot" when it actually has many.

Same issue affects any other audit/forensics tool that pattern-matches
`seed_<N>_tick*`. Tonight's `tools/check_publishable_integrity.py` was
already updated (regex `^seed_\d+\.json$`) but the snapshot-discovery
side wasn't.

## What Changes

- `tools/audit_resume_strategies.py` glob updated to match BOTH formats
  via regex: `seed_<N>(_pid\d+)?_tick(\d+|_final).snapshot.json`
- Other audit tools scanned for similar patterns; update where
  applicable
- E2E test: drop a mix of legacy + PID-prefixed snapshots → audit tool
  detects both formats and reports correct latest_snapshot_tick

## Capabilities

### Modified Capabilities

- `tick-level-resume`: audit/discovery tools SHALL recognize both
  legacy and PID-prefixed snapshot file formats

## Impact

**Affected code**:
- `tools/audit_resume_strategies.py` (snapshot discovery glob + tick extract)

**Affected behavior**:
- audit reports include PID-prefixed snapshots (previously invisible)
- legacy-only directories still work (back-compat)

**Non-goals**:
- NOT changing audit recommendation logic
- NOT touching other audit tools unless they have the same bug
