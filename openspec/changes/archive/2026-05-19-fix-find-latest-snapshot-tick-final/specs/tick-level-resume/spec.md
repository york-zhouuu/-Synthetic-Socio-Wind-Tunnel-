## ADDED Requirements

### Requirement: find_latest_snapshot SHALL recognize tick_final

`synthetic_socio_wind_tunnel.run_resilience.state_snapshot.find_latest_snapshot` SHALL consider `seed_<N>_tick_final.snapshot.json` as a snapshot candidate (in addition to `seed_<N>_tick<int>.snapshot.json` files).

When both exist, the selection rule SHALL be:

1. If `tick_final.snapshot.json` exists AND its mtime is newer or equal to the highest-tick numeric snapshot's mtime → return `tick_final.snapshot.json` (graceful_stop's final state is more authoritative than the last periodic snapshot before it).
2. Otherwise, return the highest-tick numeric snapshot.
3. If only numeric snapshots exist, return the highest-tick one (current behavior preserved).
4. If only `tick_final.snapshot.json` exists, return it.
5. If no candidates exist, return None.

This invariant fixes the 2026-05-20 silent skip where `int("_final")` raised ValueError and the file was excluded from candidates, causing auto-resume to pick stale periodic snapshots over the authoritative graceful_stop final.

#### Scenario: tick_final preferred when newer

- **GIVEN** directory contains `seed_42_tick3444.snapshot.json` (mtime 2026-05-19 20:00) and `seed_42_tick_final.snapshot.json` (mtime 2026-05-20 02:54)
- **WHEN** `find_latest_snapshot(dir, seed=42)` called
- **THEN** SHALL return the `tick_final` path (mtime newer)

#### Scenario: numeric snapshot wins when tick_final is stale

- **GIVEN** `seed_42_tick_final.snapshot.json` (mtime 2026-05-18) and `seed_42_tick3984.snapshot.json` (mtime 2026-05-20)
- **WHEN** `find_latest_snapshot` called
- **THEN** SHALL return the `tick3984` snapshot (mtime newer; tick_final is stale from old graceful_stop)

#### Scenario: only numeric snapshots — pick highest tick

- **GIVEN** `seed_42_tick3000.snapshot.json` and `seed_42_tick3500.snapshot.json` only
- **WHEN** `find_latest_snapshot` called
- **THEN** SHALL return `tick3500` (highest numeric tick; current behavior preserved)

#### Scenario: only tick_final present

- **GIVEN** `seed_42_tick_final.snapshot.json` only
- **WHEN** `find_latest_snapshot` called
- **THEN** SHALL return `tick_final`

#### Scenario: no snapshots present

- **GIVEN** empty directory
- **WHEN** `find_latest_snapshot` called
- **THEN** SHALL return None (current behavior preserved)
