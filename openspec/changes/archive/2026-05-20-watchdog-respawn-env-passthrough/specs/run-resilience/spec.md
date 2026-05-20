## ADDED Requirements

### Requirement: worker SHALL persist Plan B env to spawn_env file

`run_variant_suite.py` MUST write a JSON file
`<suite_dir>/spawn_env_<variant>.json` at worker startup capturing
the current process's value of each Plan B / resilience env var:

- `OPERATION_POOL_HANDLER_TIMEOUT_SEC`
- `OPERATION_POOL_MAX_CONCURRENT_OPS`
- `RESILIENCE_POOL_READ_TIMEOUT`
- `RESILIENCE_RETRY_MAX_ATTEMPTS`
- `RSS_RESTART_MB`
- `MEMORY_EVENT_EVICT_GRACE_DAYS`
- `SNAPSHOT_PRUNE_BEFORE_WRITE`
- `GC_EVERY_N_TICKS`
- `RSS_CHECK_EVERY_N_TICKS`
- `RESILIENCE_SNAPSHOT_EVERY_TICKS`
- `RESILIENCE_WAL_ENABLED`

The file is written atomically (tempfile + rename). If a key is
not set in `os.environ`, it is omitted (so consumers can detect
"explicitly set" vs "default").

#### Scenario: worker 写 spawn_env 文件

- **GIVEN** `OPERATION_POOL_MAX_CONCURRENT_OPS=150` is set in the
  shell that runs `run_variant_suite.py`
- **WHEN** the worker reaches its main entry
- **THEN** `<suite_dir>/spawn_env_<variant>.json` SHALL exist
- **AND** parsed JSON SHALL contain
  `{"OPERATION_POOL_MAX_CONCURRENT_OPS": "150", ...}`

### Requirement: watchdog respawn SHALL merge spawn_env file into env

`tools/watchdog_wal_deadlock.py:_spawn_replacement` MUST read
`<suite_dir>/spawn_env_<variant>.json` (if it exists) and merge its
keys into the `env` dict passed to `subprocess.Popen`. The merged
values take precedence over `os.environ.copy()` defaults so the
respawned worker inherits the original spawn's Plan B settings.

If the spawn_env file is missing or unparseable, the watchdog SHALL
log a warning and fall back to `os.environ.copy()` (current behavior,
back-compat).

#### Scenario: watchdog respawn 用 spawn_env 的值

- **GIVEN** `<suite_dir>/spawn_env_baseline.json` contains
  `{"OPERATION_POOL_MAX_CONCURRENT_OPS": "150"}`
- **AND** the watchdog's own env has this var UNSET
- **WHEN** `_spawn_replacement(suite_dir, variant="baseline", seed=44)`
  is called
- **THEN** the launched subprocess's env SHALL include
  `OPERATION_POOL_MAX_CONCURRENT_OPS=150`

#### Scenario: 缺 spawn_env 文件 SHALL fall back

- **GIVEN** no `<suite_dir>/spawn_env_<v>.json` exists
- **WHEN** watchdog respawn is invoked
- **THEN** a WARNING SHALL be logged once
- **AND** the respawn SHALL proceed using `os.environ.copy()`
