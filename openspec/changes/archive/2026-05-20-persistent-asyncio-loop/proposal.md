## Why

2026-05-20 publishable scout reproduced the recurring asyncio/httpx
hang within 1.5h on all 4 variants. The most-consistent-with-data
root-cause hypothesis is **per-tick `asyncio.run()` creates fresh
event loops 4032 times across a 14-day run**, and the shared
`httpx.AsyncClient` (constructed once at startup outside any loop)
accumulates cross-loop state inconsistencies that eventually deadlock.

`orchestrator/service.py:_fire_async_tick_end` invokes
`asyncio.run(runner())` per tick. Each call:
1. Creates a fresh event loop
2. Runs the hooks (including OperationPool LLM dispatch via httpx)
3. Tears down the loop

httpx.AsyncClient holds internal asyncio primitives (Lock,
Semaphore, etc.) that get bound to the FIRST loop they're used in,
then become invalid when that loop is closed. Subsequent loop's
attempts to acquire these primitives can hang silently.

## What Changes

- `Orchestrator` keeps a single persistent event loop attached to
  the instance via `self._persistent_loop` (lazy-created)
- `_fire_async_tick_end` uses `loop.run_until_complete()` on the
  persistent loop instead of `asyncio.run()`
- `_close_persistent_loop()` cleanup helper called on
  `on_simulation_end` hook, plus `__del__` defensive cleanup
- Test verifies:
  - Loop created once and reused across multiple tick_end calls
  - Loop closed on simulation_end
  - No exceptions when no async hooks registered (no-op preserved)

## Capabilities

### Modified Capabilities

- `agent-operations`: per-tick async work runs on a single
  persistent event loop instead of fresh-per-tick `asyncio.run()`

## Impact

**Affected code**:
- `synthetic_socio_wind_tunnel/orchestrator/service.py`
  (`_fire_async_tick_end`, new `_persistent_loop` slot, cleanup)

**Affected behavior**:
- 4032 fewer event loop create+destroy cycles per 14-day run
- httpx.AsyncClient internal primitives bind to one persistent loop
  (the one that lives forever) — no more cross-loop state corruption
- Slight memory increase: ~1MB for persistent loop kept alive between ticks
- Slight CPU win: skip loop create+teardown overhead per tick

**Non-goals**:
- NOT making MultiDayRunner.run_multi_day async (kept sync at API)
- NOT changing tier_llm_factory's AsyncClient construction
- NOT eliminating asyncio entirely (just persisting one loop)
