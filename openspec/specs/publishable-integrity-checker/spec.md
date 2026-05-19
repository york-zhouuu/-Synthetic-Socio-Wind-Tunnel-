# publishable-integrity-checker Specification

## Purpose
TBD - created by archiving change fix-publishable-integrity-glob. Update Purpose after archive.
## Requirements
### Requirement: publishable integrity checker SHALL only treat real seed result files as records

`tools/check_publishable_integrity.py::_load_seed_files` SHALL only include files matching `^seed_\d+\.json$` exactly (digit + `.json`), excluding any auxiliary or derived files such as `seed_<N>_positions.json`, `seed_<N>_tick<T>.snapshot.json`, `seed_<N>_day<D>.partial.json`, and any other `seed_*` prefixed files whose stem contains an extra underscore-separated segment after the seed number.

This invariant prevents auxiliary files from being mistakenly checked
as seed result records, which previously generated ~23 false positives
per cell (treating positions / snapshot / partial files as if they
were seed result records missing reproducibility_lock etc).

#### Scenario: positions file excluded

- **GIVEN** a variant directory contains `seed_42.json` (real result),
  `seed_42_positions.json` (auxiliary), `seed_42_tick3984.snapshot.json`
  (auxiliary)
- **WHEN** `_load_seed_files()` runs on the suite dir
- **THEN** the returned `by_variant` dict SHALL list exactly 1 record
  for that variant (the `seed_42.json`); the positions and snapshot
  files SHALL NOT be included as records

#### Scenario: partial files excluded

- **GIVEN** `seed_42_day0.partial.json` through `seed_42_day11.partial.json`
  exist alongside `seed_42.json` in a variant dir
- **WHEN** `_load_seed_files()` runs
- **THEN** SHALL return exactly 1 record (the `seed_42.json`); the
  12 partial files SHALL NOT be records

#### Scenario: real seed files included

- **GIVEN** `seed_42.json` and `seed_43.json` both exist
- **WHEN** `_load_seed_files()` runs
- **THEN** SHALL return 2 records, one per real seed result file

