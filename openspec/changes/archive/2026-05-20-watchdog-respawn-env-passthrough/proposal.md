## Why

Plan B's hot-fixes added 4 new env vars that workers MUST have set:
- `OPERATION_POOL_HANDLER_TIMEOUT_SEC=90`
- `OPERATION_POOL_MAX_CONCURRENT_OPS=200`
- `RESILIENCE_POOL_READ_TIMEOUT=60`
- `RESILIENCE_RETRY_MAX_ATTEMPTS=2`

`tools/watchdog_wal_deadlock.py:_spawn_replacement` uses
`env = os.environ.copy()` — it inherits the WATCHDOG's environment,
not the original worker's. Operators typically start the watchdog
WITHOUT these env vars in shell scope (they're injected per-worker
via `nohup env <vars> ...`). So when watchdog auto-respawns a worker,
the new worker uses **default** values, defeating all Plan B fixes.

This means: every watchdog-triggered respawn during a publishable
run silently degrades to pre-Plan-B behavior. Hang reappears, semaphore
isn't applied, timeouts revert to 120s/300s/3 retries.

## What Changes

- `run_variant_suite.py` SHALL write `<suite_dir>/spawn_env_<variant>.json`
  on worker startup, capturing the Plan B env var values from `os.environ`
- `watchdog_wal_deadlock.py:_spawn_replacement` SHALL read the
  spawn_env JSON (if present) and merge into the subprocess's env
  before launch
- E2E test verifies: write spawn_env_<v>.json with custom values →
  watchdog reads → subprocess receives those values (NOT defaults)
- Robust to missing/corrupt spawn_env.json (log warning, fall back to
  os.environ.copy())

## Capabilities

### Modified Capabilities

- `run-resilience`: watchdog respawn SHALL inherit the original
  worker's Plan B env via persisted spawn_env_<variant>.json file

## Impact

**Affected code**:
- `tools/run_variant_suite.py` (write spawn_env_<variant>.json on entry)
- `tools/watchdog_wal_deadlock.py` (`_spawn_replacement` reads + merges env)

**Affected behavior**:
- One new small JSON file per variant in each suite dir (~500 bytes)
- Watchdog respawn now correctly preserves Plan B settings
- Backward compat: spawn_env_<v>.json missing → fall back to
  os.environ.copy() (current behavior)

**Non-goals**:
- NOT changing how operators set env vars in initial spawn
- NOT covering arbitrary env vars — only a curated list of
  "Plan B + resilience" vars known to matter for respawn fidelity
