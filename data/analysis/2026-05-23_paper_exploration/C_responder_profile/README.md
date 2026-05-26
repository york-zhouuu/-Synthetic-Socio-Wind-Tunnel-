# Analysis C: Responder profile (who moves under intervention)

For each variant (HP/GD/PF), we compute per-agent mean trajectory
deviation from baseline across the intervention period (day 4-9, every 12 ticks).
An agent is a "responder" if mean dev > 20.0m.

## Files
- `responder_rates_by_demo.md` — rate by gender/age/occupation/etc per variant
- `responder_profile_summary.json` — aggregated counts
- `agents_<variant>.json` — full per-agent records (deviation + demographics)
- `deviation_histogram.png` — distribution per variant
- `extraversion_vs_deviation.png` — personality correlation scatter

## Headlines

- **hyperlocal_push**: 22.7% responder rate (682/3,000)
- **global_distraction**: 20.9% responder rate (626/3,000)
- **phone_friction**: 22.5% responder rate (676/3,000)
