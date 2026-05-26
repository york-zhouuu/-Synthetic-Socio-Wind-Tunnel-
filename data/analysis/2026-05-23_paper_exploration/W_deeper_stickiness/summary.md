# W: Deeper stickiness — multi-metric INT vs POST comparison

Per-metric mean comparison: intervention (day 4-9) vs post (day 10-13).
`post/int_ratio` > 1: effect persists or grows. < 1: revert toward baseline.

## encounter_count_total

| variant | INT mean | POST mean | post/int ratio | mean over seeds |
|---|---|---|---|---|
| baseline | 583,862 | 552,428 | 0.95× | [0.98, 0.95, 0.92] |
| hyperlocal_push | 3,195,956 | 4,223,665 | 1.32× | [1.42, 1.29, 1.25] |
| global_distraction | 813,226 | 882,141 | 1.08× | [0.99, 1.17, 1.08] |
| phone_friction | 2,752,319 | 4,470,148 | 1.62× | [1.6, 1.6, 1.67] |

## distinct_encounter_pairs

| variant | INT mean | POST mean | post/int ratio | mean over seeds |
|---|---|---|---|---|
| baseline | 29,117 | 39,705 | 1.36× | [1.39, 1.37, 1.33] |
| hyperlocal_push | 37,831 | 44,752 | 1.18× | [1.22, 1.19, 1.14] |
| global_distraction | 28,802 | 36,447 | 1.27× | [1.27, 1.27, 1.27] |
| phone_friction | 36,455 | 44,839 | 1.23× | [1.21, 1.24, 1.25] |

## new_ties_today

| variant | INT mean | POST mean | post/int ratio | mean over seeds |
|---|---|---|---|---|
| baseline | 3,333 | 4,848 | 1.96× | [3.76, 1.07, 1.06] |
| hyperlocal_push | 9,565 | 5,865 | 0.63× | [0.77, 0.62, 0.49] |
| global_distraction | 3,161 | 3,284 | 0.60× | [0, 0.88, 0.92] |
| phone_friction | 10,562 | 9,239 | 0.91× | [1.18, 0.75, 0.8] |

## move_success_count

| variant | INT mean | POST mean | post/int ratio | mean over seeds |
|---|---|---|---|---|
| baseline | 287,984 | 287,993 | 1.00× | [1.0, 1.0, 1.0] |
| hyperlocal_push | 287,686 | 287,775 | 1.00× | [1.0, 1.0, 1.0] |
| global_distraction | 287,926 | 287,969 | 1.00× | [1.0, 1.0, 1.0] |
| phone_friction | 287,696 | 287,726 | 1.00× | [1.0, 1.0, 1.0] |

