## ADDED Requirements

### Requirement: DayRunSummary SHALL persist per-day across resume boundaries

`MultiDayRunner.run_multi_day` SHALL persist each day's `DayRunSummary` to disk at day_end as `seed_<N>_day<D>.summary.json` (atomic write via tempfile + rename). At run start, before entering the day loop, SHALL read all existing `seed_<N>_day<D>.summary.json` files in the output directory and hydrate the `per_day` list with them (sorted by day_index), so the final `MultiDayResult.per_day_summaries` contains every day's data, not only those days run in the current spawn.

This requirement closes the 2026-05-20 thesis-blocking bug where 14-day publishable runs that completed via multiple resumes had `seed_<N>.json` containing only the last resume's days (typically only post-phase, missing baseline + intervention phases).

`MultiDayResult.total_encounters` and `MultiDayResult.total_ticks` SHALL be computed as sums over the hydrated per_day list (already true; this requirement makes it sum over full 14 days instead of last-resume's days).

Day summary files SHALL NOT be cleaned up by `cleanup_partials` — they
serve as the canonical per-day record and remain on disk through cell
completion + audit.

#### Scenario: resume from mid-run loads prior day summaries

- **GIVEN** a previous worker spawn completed days 0, 1, 2 and wrote
  `seed_42_day0.summary.json`, `seed_42_day1.summary.json`,
  `seed_42_day2.summary.json` to disk
- **WHEN** a new worker spawn resumes from snapshot at day 3 and runs
  days 3 + 4 to completion
- **THEN** the final `seed_42.json`'s `multi_day_result.per_day_summaries`
  SHALL have 5 entries with `day_index` = [0, 1, 2, 3, 4] in order

#### Scenario: each day_end writes its summary atomically

- **WHEN** `MultiDayRunner.run_multi_day` completes day_index=N
- **THEN** before returning to next day's loop, SHALL write
  `seed_<seed>_day<N>.summary.json` to `_output_dir` containing the
  full DayRunSummary JSON (atomic — temp file then rename)

#### Scenario: summary files survive cleanup_partials

- **GIVEN** day_summary files exist alongside day_partial files
- **WHEN** `DayCheckpointWriter.cleanup_partials` runs after final
  `seed_N.json` write
- **THEN** SHALL only delete `seed_*_day*.partial.json` files; SHALL
  NOT delete `seed_*_day*.summary.json` files

#### Scenario: total_encounters reflects all 14 days post-resume

- **GIVEN** a 14-day publishable run completed via 3 resumes
  (day 0-4 in spawn 1, day 5-9 in spawn 2, day 10-13 in spawn 3)
- **WHEN** spawn 3 completes and writes seed_42.json
- **THEN** `multi_day_result.total_encounters` SHALL equal the sum of
  encounter_count across all 14 day summaries (not just spawn 3's 4 days)
