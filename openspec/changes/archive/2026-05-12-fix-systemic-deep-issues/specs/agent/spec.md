## ADDED Requirements

### Requirement: LANE_COVE_PROFILE family_composition SHALL match ABS 2021 reality

The `LANE_COVE_PROFILE.family_composition_distribution` MUST reflect ABS
2021 SAL12275 Lane Cove household composition values, NOT placeholder
zeros that silently double-count one family type:

| key | proportion |
|---|---|
| `lone_person`           | 0.1903 |
| `couple_no_kids`        | 0.2666 |
| `couple_kids_under_15`  | 0.2200 |
| `couple_kids_15plus`    | 0.1500 |
| `one_parent_family`     | 0.0945 |
| `group_household`       | 0.0480 |
| `other`                 | 0.0306 |

All 7 keys MUST be present with non-zero values. Sum MUST equal 1.0 ± 1e-3.

Pre-fix bug: `lone_person=0.0` and `group_household=0.0` were placeholders;
the missing ~24% was implicitly absorbed into `couple_kids_under_15` which
ballooned to 49% — twice the realistic share. School-pickup load
proportionally inflated.

#### Scenario: distribution sums to 1
- **WHEN** caller reads `LANE_COVE_PROFILE.family_composition_distribution`
- **THEN** `sum(distribution.values())` SHALL approximate 1.0 within ±0.001

#### Scenario: lone_person and group_household non-zero
- **WHEN** caller iterates `LANE_COVE_PROFILE.family_composition_distribution`
- **THEN** `distribution["lone_person"]` SHALL be > 0.15;
  `distribution["group_household"]` SHALL be > 0.03

#### Scenario: under-15 share matches ABS
- **WHEN** sample_population draws 100 agents from LANE_COVE_PROFILE with seed
- **THEN** `couple_kids_under_15` count SHALL be in range [15, 30] (target 22 ± noise)
