## 1. TDD red — e2e tests

- [x] 1.1 `tests/test_orchestrator_persistent_loop.py`:
  - `test_async_hook_uses_persistent_loop` — register async hook,
    fire tick_end twice, verify same loop instance used both times
  - `test_no_async_hook_no_loop_created` — no hooks → no loop spawned
  - `test_loop_closed_on_simulation_end` — sim_end fires → loop closed
  - `test_legacy_path_still_works_when_no_hooks` — back-compat
- [x] 1.2 Run → RED

## 2. Implement persistent loop

- [x] 2.1 Orchestrator `_persistent_loop: asyncio.AbstractEventLoop | None`
  attribute (lazy init)
- [x] 2.2 `_get_or_create_loop()` helper
- [x] 2.3 `_fire_async_tick_end` uses persistent loop's
  `run_until_complete` instead of `asyncio.run()`
- [x] 2.4 `_close_persistent_loop()` helper called from on_simulation_end
  or explicit cleanup

## 3. Verify

- [x] 3.1 Existing orchestrator tests pass
- [x] 3.2 Multi-day tests pass
- [x] 3.3 Aitown e2e (test_aitown_port_e2e if exists) passes

## 4. Validate + archive

- [x] 4.1 `openspec validate --strict`
- [x] 4.2 archive + commit + push
