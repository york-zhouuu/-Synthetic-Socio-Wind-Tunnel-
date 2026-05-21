## ADDED Requirements

### Requirement: SHALL execute per-protag day-end reflect calls concurrently

The day-end reflection batch in `tools/run_variant_suite.py` MUST
dispatch per-protagonist `memory_service.maybe_reflect` calls via
`asyncio.gather` bounded by `asyncio.Semaphore(N)` where N is read from
env `DAY_END_REFLECT_CONCURRENCY` (default 30). Each call MUST retain
its existing `asyncio.wait_for(60.0)` timeout guard and TIMEOUT log
fallback ("skip and move on for this protag").

#### Scenario: concurrent reflect finishes ≥ N× faster than serial

- **GIVEN** 100 protagonists and a stub reflect that takes 100ms each
- **WHEN** day-end reflection batch fires with DAY_END_REFLECT_CONCURRENCY=30
- **THEN** total elapsed time SHALL be ≤ 5 seconds (concurrent) and not
  ≥ 10 seconds (serial baseline would be)

#### Scenario: reflect hang isolated

- **GIVEN** 100 protagonists where 1 maybe_reflect hangs (sleep > 60s)
  and 99 return immediately
- **WHEN** day-end reflect runs with Semaphore(30)
- **THEN** total elapsed SHALL be ≤ 70 seconds
- **AND** TIMEOUT log SHALL be emitted for the 1 hung protag
- **AND** the 99 fast protags SHALL complete their reflection writes
  to memory_store

#### Scenario: TIMEOUT log + memory_store unchanged for hung protag

- **GIVEN** a protag whose `maybe_reflect` exceeds 60s wait_for
- **WHEN** day-end batch processes this protag
- **THEN** `[aitown] reflect TIMEOUT (60s) for <agent_id>; skipping` SHALL
  print to stderr
- **AND** no reflection event SHALL be recorded in `memory_store.events`
  for this protag for the current day_index (skipped, not partial)
