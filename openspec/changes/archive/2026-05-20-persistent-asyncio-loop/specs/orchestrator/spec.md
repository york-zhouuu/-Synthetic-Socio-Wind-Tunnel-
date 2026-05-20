## ADDED Requirements

### Requirement: tick-end async hooks SHALL share a persistent event loop

`Orchestrator._fire_async_tick_end` SHALL use a single persistent
`asyncio.AbstractEventLoop` instance attached to the Orchestrator
for the duration of the simulation, rather than calling
`asyncio.run()` per tick (which creates+destroys a fresh loop each
time). httpx.AsyncClient and other async-bound resources keep
internal state tied to the first loop they were used in; per-tick
fresh loops cause state corruption that has been observed to manifest
as recurring deadlock at scale (2026-05-20 scout: 4 worker hang at
~1.5h, backlog 1.9).

The loop is lazy-created on first call. Cleanup happens on the
`on_simulation_end` hook. The orchestrator's outer API
(`Orchestrator.run`, `MultiDayRunner.run_multi_day`) remains
synchronous.

#### Scenario: 多次 tick_end async 调用复用同一 loop

- **GIVEN** an Orchestrator with at least one async tick_end hook
  registered
- **WHEN** `_fire_async_tick_end` is invoked N times during simulation
- **THEN** the SAME `asyncio.AbstractEventLoop` instance SHALL be used
  for all N invocations
- **AND** at no point SHALL `asyncio.run()` be called inside the
  Orchestrator's tick path

#### Scenario: 无 async hook 时不创建 loop

- **GIVEN** an Orchestrator with NO async tick_end hooks registered
- **WHEN** `_fire_async_tick_end` is invoked
- **THEN** no event loop SHALL be created (back-compat for sync-only
  simulations)

#### Scenario: simulation 结束时关闭 loop

- **GIVEN** an Orchestrator that has been running with a persistent
  event loop
- **WHEN** `on_simulation_end` hooks fire (end of simulation)
- **THEN** the persistent loop SHALL be closed (`loop.is_closed() == True`)
