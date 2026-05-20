## 1. TDD red — e2e tests

- [x] 1.1 `tests/test_watchdog_env_passthrough.py`:
  - `test_spawn_env_file_written_on_worker_start` — when
    run_variant_suite worker starts, spawn_env_<v>.json contains
    current OPERATION_POOL_MAX_CONCURRENT_OPS etc.
  - `test_watchdog_reads_spawn_env_and_passes` — with spawn_env.json
    containing custom values, `_spawn_replacement` SHALL include
    those vars in subprocess env
  - `test_missing_spawn_env_falls_back` — no file → use os.environ.copy()
  - `test_corrupt_spawn_env_falls_back_warns` — corrupt JSON → log warn + fallback
- [x] 1.2 Run → RED

## 2. Implement env-write in run_variant_suite

- [x] 2.1 At worker startup, write
  `<suite_dir>/spawn_env_<variant>.json` with curated Plan B keys
  (atomic write via tempfile+rename)

## 3. Implement env-read in watchdog

- [x] 3.1 `_spawn_replacement` reads spawn_env_<v>.json (if exists);
  merges into subprocess env (overriding os.environ defaults)
- [x] 3.2 Catches JSON decode error → warning + fall back

## 4. Regression

- [x] 4.1 watchdog dry-run still works
- [x] 4.2 existing tests pass

## 5. Validate + archive
- [x] 5.1 openspec validate --strict
- [x] 5.2 archive + commit + push
