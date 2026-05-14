## ADDED Requirements

### Requirement: SocialGraphService SHALL expose time-decayed tie strength

`SocialGraphService` MUST provide `effective_strength(tie, now_tick) -> float`
that applies a 30-day half-life exponential decay to a Tie's raw strength
based on `(now_tick - tie.last_seen_tick)`:

```
days_since = (now_tick - tie.last_seen_tick) / TICKS_PER_DAY
decay = exp(-ln(2) × days_since / 30)
effective = tie.strength × decay
```

Raw `tie.strength` SHALL be left immutable; decay applied at read time only
so existing callers using `tie.strength` directly continue to see growth-only
behaviour (backward compat). New audit code MAY opt-in to decayed strength
via `effective_strength` / `weak_ties_decayed` / `strong_ties_decayed`.

`SocialGraphService.weak_ties_decayed(agent_id, *, now_tick) -> list[Tie]`
SHALL return ties whose `effective_strength(now_tick)` is in
`[WEAK_TIE_THRESHOLD, STRONG_TIE_THRESHOLD)`.

`SocialGraphService.strong_ties_decayed(agent_id, *, now_tick) -> list[Tie]`
SHALL return ties whose `effective_strength(now_tick)` is `≥ STRONG_TIE_THRESHOLD`.

#### Scenario: never-decayed tie keeps raw strength
- **WHEN** `effective_strength(tie, tie.last_seen_tick)` is called (now == last_seen)
- **THEN** result SHALL equal `tie.strength` exactly

#### Scenario: 30-day-old tie at half strength
- **WHEN** a tie has `last_seen_tick = 0`, `strength = 0.5`, and now_tick =
  30 × 288 = 8640
- **THEN** `effective_strength(tie, 8640)` SHALL be ≈ 0.25 (50% decay)

#### Scenario: ancient tie effectively zero
- **WHEN** a tie has `last_seen_tick = 0`, `strength = 1.0`, and now_tick =
  365 × 288 (1 year)
- **THEN** `effective_strength(tie, ...)` SHALL be < 0.001

#### Scenario: weak_ties_decayed excludes faded ties
- **WHEN** a tie's raw strength is 0.15 (weak) but 60 days have passed
- **THEN** that tie SHALL NOT appear in `weak_ties_decayed(agent_id, now_tick=60*288)`
  (effective 0.15 × exp(-60/30) ≈ 0.020, below WEAK_TIE_THRESHOLD)
