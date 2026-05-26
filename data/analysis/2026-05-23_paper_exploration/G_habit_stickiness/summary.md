# G: Habit stickiness — responders' deviation in post-period vs intervention

Responder threshold: >20m mean deviation during day 4-9.
`post/intervention_ratio` = mean post-period dev ÷ mean intervention dev.
> 1.0 = MORE deviation after intervention stopped (sticky habit / network effect)
< 1.0 = revert toward baseline (transient effect)

| seed | variant | n_responders | int_dev_m | post_dev_m | ratio | non_resp_post_dev |
|---|---|---|---|---|---|---|
| 43 | hyperlocal_push | 501 | 712.3 | 712.3 | 1.00× | 0.4 |
| 43 | global_distraction | 519 | 483.9 | 483.9 | 1.00× | 0.6 |
| 43 | phone_friction | 490 | 694.0 | 694.0 | 1.00× | 0.3 |
| 44 | hyperlocal_push | 113 | 896.3 | 896.3 | 1.00× | 0.0 |
| 44 | global_distraction | 61 | 744.2 | 744.2 | 1.00× | 0.0 |
| 44 | phone_friction | 110 | 939.9 | 939.9 | 1.00× | 0.0 |
| 45 | hyperlocal_push | 68 | 1047.9 | 1047.9 | 1.00× | 0.0 |
| 45 | global_distraction | 46 | 893.9 | 893.9 | 1.00× | 0.0 |
| 45 | phone_friction | 76 | 1098.5 | 1098.5 | 1.00× | 0.0 |
