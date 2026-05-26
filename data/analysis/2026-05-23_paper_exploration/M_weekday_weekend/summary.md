# M: Weekday vs weekend split

day 0 = 2026-04-22 (Wed). Weekdays = Mon-Fri; Weekend = Sat-Sun.

## baseline

| metric | weekday mean | weekend mean | wkend/wkday |
|---|---|---|---|
| encounter_count | 597,296 | 520,136 | 0.87× |
| distinct_pairs | 22,891 | 59,626 | 2.60× |
| move_success | 287,980 | 288,000 | 1.00× |
| new_ties | 1,803 | 5,376 | 2.98× |

## hyperlocal_push

| metric | weekday mean | weekend mean | wkend/wkday |
|---|---|---|---|
| encounter_count | 2,804,489 | 2,591,532 | 0.92× |
| distinct_pairs | 31,439 | 56,375 | 1.79× |
| move_success | 287,774 | 287,850 | 1.00× |
| new_ties | 5,570 | 6,323 | 1.14× |

## global_distraction

| metric | weekday mean | weekend mean | wkend/wkday |
|---|---|---|---|
| encounter_count | 783,735 | 727,798 | 0.93× |
| distinct_pairs | 22,921 | 55,822 | 2.44× |
| move_success | 287,946 | 287,974 | 1.00× |
| new_ties | 1,699 | 3,816 | 2.25× |

## phone_friction

| metric | weekday mean | weekend mean | wkend/wkday |
|---|---|---|---|
| encounter_count | 2,625,122 | 2,620,977 | 1.00× |
| distinct_pairs | 30,700 | 56,245 | 1.83× |
| move_success | 287,760 | 287,850 | 1.00× |
| new_ties | 6,744 | 8,256 | 1.22× |

