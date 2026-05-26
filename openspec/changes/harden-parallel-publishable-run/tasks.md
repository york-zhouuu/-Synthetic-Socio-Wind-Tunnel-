## 1. Audit cold-prune evict bug (backlog 1.20)

- [ ] 1.1 Add diagnostic logging to `evict_cold_encounter_events`:
  ```python
  n_total = len(self._events)
  n_encounter = sum(1 for e in self._events if e.kind == "encounter")
  n_with_day = sum(1 for e in self._events
                   if e.kind == "encounter" and e.day_index is not None)
  n_old_enough = sum(1 for e in self._events
                     if e.kind == "encounter"
                        and e.day_index is not None
                        and e.day_index < before_day_index)
  logger.info(f"evict diag: total={n_total} encounter={n_encounter} "
              f"with_day={n_with_day} old_enough={n_old_enough} "
              f"before_day_index={before_day_index}")
  ```

- [ ] 1.2 Run 1-day smoke (1000 agent, dev mode) → grep diag log → identify
  which hypothesis is true:
  - if `encounter` == 0: kind name mismatch → fix kind matching
  - if `with_day` == 0: day_index missing → fix record() to set day_index
  - if `old_enough` == 0 but others > 0: day_index always = current → fix
    where day_index is set to use **event's tick's day**, not record-time day

## 2. Implement fix for root cause

- [ ] 2.1 Based on §1 diagnosis, fix the relevant code path:
  - Likely: `memory_service.record()` sets `event.day_index` correctly from
    the event's `tick` field
  - OR: `evict_cold_encounter_events` uses different kind filter
- [ ] 2.2 Update existing tests if any pre-conceived behavior changes
- [ ] 2.3 Write new unit test `tests/test_evict_cold_encounter_root_cause.py`:
  - `test_evict_finds_old_events_with_correct_day_index`
  - `test_evict_finds_events_with_kind_encounter`
  - `test_evict_no_op_when_no_old_events`

## 3. Streaming snapshot serialization

- [ ] 3.1 Replace `json.dumps(self.model_dump(...))` in
  `SimulationCheckpoint.write_atomic` with orjson streaming write
- [ ] 3.2 Add benchmark test verifying ≤ 1.2× RSS peak during write (vs old
  2× peak)
- [ ] 3.3 Backward-compat verification: write old format → load with new
  reader still works

## 4. Real-artifact memory profile test

- [ ] 4.1 New `tests/test_publishable_memory_profile.py`:
  - Run 1000 agent × 4 day dev smoke via subprocess
  - Read events.jsonl, assert EVICT events at day 3+ have
    `events_evicted > 0`
  - Read snapshot files, assert day 4 snapshot ≤ day 3 snapshot size (post-fix)
  - Read memstat.jsonl, assert RSS at day 4 end < RSS at day 0 end × 2

- [ ] 4.2 Add to CI / pre-publishable gate

## 5. CLAUDE.md + spawn template update

- [ ] 5.1 Document the fix in CLAUDE.md 关键不变量 section
- [ ] 5.2 Confirm spawn template `MEMORY_EVENT_EVICT_GRACE_DAYS=2` is correct
  (default; may relax to 1 for fork phase per 2026-05-21 workaround)

## 6. Optional: streaming snapshot reader

- [ ] 6.1 If §3 streaming write done, consider streaming read too (avoid 5-10×
  RSS peak on resume)

## 7. Validate + archive

- [ ] 7.1 `openspec validate harden-parallel-publishable-run --strict`
- [ ] 7.2 Run full test suite — no regressions
- [ ] 7.3 Run 1-cell dev smoke verifying EVICT > 0 + snapshot shrinks
- [ ] 7.4 Archive after merge
