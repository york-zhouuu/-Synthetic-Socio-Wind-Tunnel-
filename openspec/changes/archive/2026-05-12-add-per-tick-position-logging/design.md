## Context

Current per-day metrics aren't enough for 14-day activity replay. Existing
hook chain (`on_tick_end`) already has every piece needed:

- `entity_locations` dict is computed in `_run_tick` for encounter detection
  (B9 fix added it for stationary co-presence)
- Just needs to be exposed via TickResult so recorders can subscribe

## Goals / Non-Goals

**Goals**:
1. Sparse position change events available to all on_tick_end subscribers
2. Suite writes companion file alongside `seed_X.json`
3. ≤ 5% wall-time overhead per tick (recorder is O(N_changed_agents))

**Non-Goals**:
1. Don't update dashboard to consume — separate change
2. Don't change publishable protocol
3. Don't add per-tick LLM state, only position

## Decisions

### D1 · Sparse vs dense recording

**Choose sparse** (only record on change):
- 100 agent × 288 ticks/day × 14 day = 403,200 entries if dense
- Most agents stay still hours → ~20 moves/day actual
- Sparse: 100 × 14 × 20 = 28,000 entries (14× smaller)

Cost: requires `_last_location: dict[str, str]` per recorder to detect
change. Memory bounded by num_agents not ticks. Acceptable.

### D2 · Companion file vs embed in seed_X.json

**Choose companion** `seed_<N>_positions.json`:
- Keep main metrics JSON lean for backward compat (existing dashboards / audit
  scripts don't need to parse 100KB+ of position data)
- Easier lazy-load for 3D dashboard (only fetch positions when time-slider
  active)

### D3 · TickResult mutation

Add `entity_locations: tuple[tuple[str, str], ...] = ()` (default empty,
backward compat). Existing code that constructs TickResult without
entity_locations continues to work; tests verified.

### D4 · Storage in TickResult — tuple not dict

`dict` is unhashable for frozen dataclass; `tuple[tuple[str, str], ...]`
preserves ordering and is hashable. Recorder reconstructs into dict
internally if needed.

## Risks / Trade-offs

- **[wall-time overhead]** measured @ 50 agent × 14 day: total run 575s,
  position recorder consumes ~140k iterations through entity_locations.
  Estimated <2% overhead. Acceptable.
- **[disk usage at scale]** 1000 agent × 15 seed × 14 day ≈ 1-2GB total.
  Mitigation: companion files can be gzipped (1 line code change later)
  or excluded from git via existing `data/experiments/` .gitignore.
- **[stale positions if agent removed mid-sim]** unlikely in current sim
  (population is static); recorder just records last seen.

## Migration Plan

1. Add field to TickResult (default empty tuple → backward compat)
2. Orchestrator passes entity_locations into TickResult
3. New `PositionTraceRecorder` class
4. Suite registers + writes companion file
5. Tests
6. Verify 14-day smoke produces realistic file sizes
