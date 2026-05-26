# Effect sizes with proper variance markers (n=3 seeds)

Each metric reports: mean across 3 seeds + CV% + fold-change vs baseline + per-seed values.

## raw encounters (millions) (`encounter_total`)

**Baseline**: 8.05 (CV 7.7%, per seed: [7.51, 7.91, 8.73])

| variant | mean | CV% | fold vs BL | per seed |
|---|---|---|---|---|
| hyperlocal_push | 38.41 | 9.9% | **4.77×** | [41.1, 34.04, 40.09] |
| global_distraction | 10.75 | 9.0% | **1.33×** | [9.66, 11.52, 11.06] |
| phone_friction | 36.74 | 3.9% | **4.56×** | [35.23, 38.11, 36.86] |

## unique pairs (thousands) (`unique_pairs`)

**Baseline**: 467.42 (CV 3.2%, per seed: [476.24, 475.72, 450.29])

| variant | mean | CV% | fold vs BL | per seed |
|---|---|---|---|---|
| hyperlocal_push | 539.89 | 4.3% | **1.16×** | [566.55, 525.26, 527.86] |
| global_distraction | 452.50 | 3.0% | **0.97×** | [461.5, 458.89, 437.1] |
| phone_friction | 531.98 | 2.2% | **1.14×** | [534.37, 542.16, 519.41] |

## weak ties (thousands) (`weak_tie`)

**Baseline**: 15.84 (CV 18.1%, per seed: [12.55, 17.82, 17.16])

| variant | mean | CV% | fold vs BL | per seed |
|---|---|---|---|---|
| hyperlocal_push | 15.15 | 13.4% | **0.96×** | [12.87, 16.77, 15.79] |
| global_distraction | 12.74 | 58.1% | **0.80×** | [4.19, 16.94, 17.09] |
| phone_friction | 13.29 | 13.4% | **0.84×** | [11.39, 14.92, 13.55] |

## active dialogues at exit (`dialogue_live_at_exit`)

**Baseline**: 72.67 (CV 9.8%, per seed: [74.0, 65.0, 79.0])

| variant | mean | CV% | fold vs BL | per seed |
|---|---|---|---|---|
| hyperlocal_push | 206.67 | 12.1% | **2.84×** | [213.0, 179.0, 228.0] |
| global_distraction | 109.33 | 7.4% | **1.50×** | [118.0, 102.0, 108.0] |
| phone_friction | 243.67 | 7.4% | **3.35×** | [243.0, 226.0, 262.0] |

## replans (`replan_count`)

**Baseline**: 0.00 (CV 0.0%, per seed: [0.0, 0.0, 0.0])

| variant | mean | CV% | fold vs BL | per seed |
|---|---|---|---|---|
| hyperlocal_push | 1990.33 | 10.6% | **0.00×** | [1788.0, 1973.0, 2210.0] |
| global_distraction | 446.67 | 87.0% | **0.00×** | [0.0, 706.0, 634.0] |
| phone_friction | 1751.33 | 9.0% | **0.00×** | [1571.0, 1855.0, 1828.0] |

