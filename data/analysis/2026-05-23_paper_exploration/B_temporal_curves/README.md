# Analysis B: 14-day temporal curves

## Phases
- **Baseline** (day 0-3): no intervention applied
- **Intervention** (day 4-9): 6 days of variant-specific push
- **Post** (day 10-13): intervention stopped, observe revert

## Files
- `temporal_curves.png` — 10-metric multi-panel chart
- `per_day_series.json` — raw per-day data per cell
- `phase_summary.md` — phase-aggregated stats table

## Key questions to answer from this analysis
1. **Onset shape**: Does HP effect jump suddenly on day 4 (push starts)
   or accumulate gradually? → tells us about habit-formation dynamics
2. **Habituation**: Does effect attenuate across days 5-9? → diminishing returns?
3. **Post-period revert**: Do days 10-13 return to baseline
   levels (no stickiness) or stay elevated (residual habits)?
4. **Variant separation**: When does HP/PF curve diverge from GD?

