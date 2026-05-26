# N: Methodological notes — seed 43 vs 44/45

## Fork suite directories

- **seed 43**: `20260521_185100_publishable_v6_day4to13_fork_seed43`
- **seed 44**: `20260522_165045_publishable_v7_day4to13_fork_seed44`
- **seed 45**: `20260522_212423_publishable_v7_day4to13_fork_seed45`

## Baseline outcome variance (validates protocol)

| seed | encounter_total | weak_tie | dialogue |
|---|---|---|---|
| 43 | 7,513,376.0 | 12,548 | 749 |
| 44 | 7,913,095.0 | 17,816 | 752 |
| 45 | 8,734,049.0 | 17,155 | 744 |

## Recommendation

Trajectory analyses show seed 43 has 3-4× higher per-agent deviation
vs seed 44/45. This is because seed 43's baseline-prefix run on
2026-05-21 used a different code commit (v6 fork on May 21 vs v7
on May 22) and different stochastic seed in the prefix phase.

For paper-grade analyses, prefer **seed 44 and 45** as the primary
reference (same protocol, lower-variance baseline). Use seed 43 for
robustness check / triangulation, not as primary numbers.
