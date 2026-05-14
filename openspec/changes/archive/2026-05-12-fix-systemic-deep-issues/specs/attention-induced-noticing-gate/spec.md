## MODIFIED Requirements

### Requirement: NoticingGate SHALL gate encounters via attention

The noticing gate SHALL combine attention attenuation with polygon-size
discount. The function `noticing_prob(a_attn: float, b_attn: float, *,
polygon_extent_m: float | None = None) -> float` MUST return:

```
max(0.0, 1.0 - max(a_attn, b_attn)) × BASE_NOTICING_RATE × spatial_factor
```

Where `BASE_NOTICING_RATE = 0.3` and `spatial_factor` accounts for whether
the agents are in a polygon larger than typical visual range:

```
spatial_factor = min(1.0, VISUAL_RANGE_M / polygon_extent_m)  if polygon_extent_m else 1.0
```

with `VISUAL_RANGE_M = 50.0`.

`noticed_pair(...)` MUST accept the same `polygon_extent_m` keyword and
forward it to `noticing_prob`. Same deterministic-hash semantics as before.

Pre-A3 bug: large polygons (e.g. Mowbray Park 1.4km extent) had two agents
"at same location_id" but at opposite ends still counted full noticing rate.
spatial_factor down-weights this — 1.4km park yields ~3.6% of base rate.

#### Scenario: both agents on phone → low noticing
- **WHEN** a_attn=0.9, b_attn=0.8
- **THEN** noticing_prob == `max(0, 1 - 0.9) × 0.3` == 0.03 (~3% noticed)

#### Scenario: both agents not on phone → ideal noticing
- **WHEN** a_attn=0.05, b_attn=0.05
- **THEN** noticing_prob ≈ `0.95 × 0.3` ≈ 0.285 (~29% noticed)

#### Scenario: deterministic noticing
- **WHEN** noticed_pair called twice with same args
- **THEN** both calls SHALL return the same boolean

#### Scenario: one agent on phone blocks noticing
- **WHEN** a_attn=0.1, b_attn=0.95
- **THEN** noticing_prob == `0.05 × 0.3` == 0.015 (one-side glued = both blind)

#### Scenario: large polygon discounts noticing
- **WHEN** noticing_prob(0.05, 0.05, polygon_extent_m=1400)
- **THEN** result SHALL be ~`0.95 × 0.3 × (50/1400)` ≈ 0.010 (much lower
  than the no-extent case)

#### Scenario: small polygon no discount
- **WHEN** noticing_prob(0.05, 0.05, polygon_extent_m=30)
- **THEN** result SHALL equal `noticing_prob(0.05, 0.05)` (no extent factor)
