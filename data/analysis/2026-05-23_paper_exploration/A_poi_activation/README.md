# Analysis A: POI Activation

Mean dwell ticks per location, across 3 seeds, compared variant vs baseline.

## Files

- `activation_per_location.json` — full per-loc activation data
- `top_activated_<variant>.md` — top 25 ↑↓ per variant
- `heatmap_<variant>.png` — spatial heatmap

## Headline numbers

### hyperlocal_push
- locations with non-trivial dwell: 2737
- activated (>10%): 265
- deactivated (<-10%): 1549
- median activation: -12.1%
- max activation: +192121.2%
- min activation: -88.2%

### global_distraction
- locations with non-trivial dwell: 2732
- activated (>10%): 173
- deactivated (<-10%): 384
- median activation: -1.3%
- max activation: +49178.8%
- min activation: -85.3%

### phone_friction
- locations with non-trivial dwell: 2734
- activated (>10%): 201
- deactivated (<-10%): 1674
- median activation: -13.3%
- max activation: +232836.4%
- min activation: -85.7%

