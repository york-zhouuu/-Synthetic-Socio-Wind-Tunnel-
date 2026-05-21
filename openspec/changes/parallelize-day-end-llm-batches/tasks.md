## 1. TDD red — write failing tests first

- [ ] 1.1 `tests/test_run_daily_summary_concurrent.py`:
  - `test_concurrent_finishes_faster_than_serial` — 100 agent × stub_latency=100ms
    → concurrent should finish in <5s (vs 10s serial)
  - `test_concurrent_isolates_hang` — 1 hang (asyncio.sleep(120)) + 99 fast →
    finish in <70s, 99 summaries returned + 1 fallback "(unavailable)"
  - `test_concurrent_preserves_per_agent_fields` — assert summary_text + tags +
    importance match serial baseline byte-equal
  - `test_concurrent_records_daily_summary_event_per_agent` — assert each agent
    gets a `daily_summary` MemoryEvent recorded in memory_store
  - `test_concurrent_no_events_agent_skipped` — agents with no events bypass LLM
  - `test_semaphore_limits_concurrent_calls` — Semaphore(N=3) → only 3 LLM calls
    in flight at any moment

- [ ] 1.2 `tests/test_run_variant_suite_reflect_concurrent.py`:
  - `test_reflect_concurrent_finishes_faster` — stub maybe_reflect 100 protag
  - `test_reflect_concurrent_hang_isolation` — 1 hung protag doesn't block 99
  - `test_reflect_timeout_fallback_logged` — assert TIMEOUT log printed per
    hung protag

## 2. Implement concurrent `run_daily_summary`

- [ ] 2.1 Refactor `memory_service.run_daily_summary`:
  - Wrap per-agent logic in inner `async def _summarize_one(agent_id, agent)`
  - `sem = asyncio.Semaphore(int(os.environ.get("DAILY_SUMMARY_CONCURRENCY", 30)))`
  - `results = await asyncio.gather(*(_summarize_one(...) for ...), return_exceptions=False)`
  - Preserve `wait_for(60s)` per-call timeout
  - Preserve fallback summary on TimeoutError / Exception
  - Preserve `self.record(...)` daily_summary event per agent (post-gather, serial
    in deterministic order to keep memory_store event_id ordering stable)
- [ ] 2.2 New env: `DAILY_SUMMARY_CONCURRENCY` (default 30)

## 3. Implement concurrent maybe_reflect loop

- [ ] 3.1 Refactor `tools/run_variant_suite.py:970-985` day-end reflect block:
  - Wrap per-protag logic in `async def _reflect_one(rt)`
  - `sem = asyncio.Semaphore(int(os.environ.get("DAY_END_REFLECT_CONCURRENCY", 30)))`
  - `await asyncio.gather(*(_reflect_one(rt) for rt in protagonists))`
  - Preserve `wait_for(60s)` + TIMEOUT logging
- [ ] 3.2 New env: `DAY_END_REFLECT_CONCURRENCY` (default 30)

## 4. Test green + regression sweep

- [ ] 4.1 New tests from §1 all pass
- [ ] 4.2 Existing tests pass: `tests/test_memory_*.py` `tests/test_run_resilience_*.py`
- [ ] 4.3 Dev smoke (50 agent × 1 day) — verify day_summary.json written + no
  errors

## 5. CLAUDE.md update

- [ ] 5.1 Add `DAILY_SUMMARY_CONCURRENCY=30` + `DAY_END_REFLECT_CONCURRENCY=30`
  to spawn template
- [ ] 5.2 Note in invariants: "day_end LLM batches SHALL be concurrent (Semaphore)
  with per-call wait_for guard"

## 6. Validate + archive

- [ ] 6.1 `openspec validate parallelize-day-end-llm-batches --strict`
- [ ] 6.2 Archive after merge
