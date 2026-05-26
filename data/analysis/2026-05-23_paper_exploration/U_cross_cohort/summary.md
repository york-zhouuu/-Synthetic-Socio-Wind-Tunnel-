# U: Cross-cohort co-location analysis

Per location_id (end-of-day), count distinct (age_bucket, occupation) tuples.
Higher diversity = more demographic mixing at that location.

| variant | mean median_diversity | mean max_diversity | mean n_locations |
|---|---|---|---|
| baseline | 2.00 | 9.7 | 410 |
| hyperlocal_push | 1.76 | 35.2 | 391 |
| global_distraction | 1.99 | 18.4 | 408 |
| phone_friction | 1.64 | 32.7 | 394 |
