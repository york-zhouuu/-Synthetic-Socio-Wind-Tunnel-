## ADDED Requirements

### Requirement: SHALL execute per-agent daily_summary LLM calls concurrently

`MemoryService.run_daily_summary` MUST dispatch per-agent LLM calls via
`asyncio.gather` bounded by `asyncio.Semaphore(N)` where N is read from
env `DAILY_SUMMARY_CONCURRENCY` (default 30). Each individual LLM call
MUST retain its existing `asyncio.wait_for(60.0)` timeout guard and
fallback string ("(unavailable)" / "(daily summary timed out)") on
Exception / TimeoutError. The `daily_summary` MemoryEvent record per
agent SHALL still be written (post-gather, in deterministic agent_id
order, to keep memory_store event_id sequence stable for snapshot
round-trip).

#### Scenario: concurrent finishes ≥ N× faster than serial

- **GIVEN** 100 agents and a stub LLM client with 100ms per-call latency
- **WHEN** `run_daily_summary(agents, llm_client)` is invoked with
  DAILY_SUMMARY_CONCURRENCY=30
- **THEN** completion time SHALL be ≤ 5 seconds (concurrent) and not
  ≥ 10 seconds (serial would be)

#### Scenario: single hang isolated by concurrency

- **GIVEN** 100 agents where 1 LLM call returns after 120s (longer than
  60s wait_for) and 99 return immediately
- **WHEN** `run_daily_summary` runs with Semaphore(30)
- **THEN** total elapsed SHALL be ≤ 70 seconds (1 timeout + others fast)
- **AND** the 1 hung agent SHALL have summary_text "(daily summary
  timed out)"; the 99 fast agents SHALL have non-fallback summaries

#### Scenario: per-agent DailySummary fields preserved

- **GIVEN** real-LLM run (or fixture stub) producing per-agent summary
  text + tags + importance
- **WHEN** concurrent vs serial implementations both run on identical
  agent set + event input
- **THEN** the returned `dict[str, DailySummary]` SHALL have identical
  keys, summary_text, date, importance per agent

#### Scenario: daily_summary MemoryEvent recorded for each agent

- **GIVEN** N agents with at least one event each
- **WHEN** `run_daily_summary` completes
- **THEN** `memory_store.events` SHALL contain exactly N events with
  `kind="daily_summary"` for the current day_index

### Requirement: SHALL skip LLM call for agents with no events

`run_daily_summary` MUST skip the LLM call (no wait_for, no provider
call) for any agent whose filtered `today_events` list is empty. This
preserves the existing "(no events)" short-circuit branch and ensures
provider load remains bounded by active-event-count, not nominal
agent-count.

#### Scenario: agent with empty today_events skips LLM

- **GIVEN** an agent_id whose memory_store has zero events with the
  current day_index (e.g. bystander that didn't act today)
- **WHEN** `run_daily_summary` processes this agent
- **THEN** no LLM call SHALL be issued for this agent
- **AND** the returned summary SHALL have summary_text "(no events)"
