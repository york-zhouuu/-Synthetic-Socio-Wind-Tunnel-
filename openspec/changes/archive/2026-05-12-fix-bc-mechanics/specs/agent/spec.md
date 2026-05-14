## ADDED Requirements

### Requirement: LANE_COVE_PROFILE work_mode SHALL reflect steady-state, not COVID anomaly

The `LANE_COVE_PROFILE.work_mode_distribution` MUST reflect steady-state
Sydney commute patterns, NOT the ABS 2021 raw values captured during Delta
lockdown (which had `remote=52.7%`, anomalously high). Steady-state values
SHALL be:

| key | proportion |
|---|---|
| `commute`    | 0.594 |
| `remote`     | 0.180 |
| `shift`      | 0.127 |
| `nonworking` | 0.099 |

Publishable reports SHALL disclose this de-anomaly choice in §Limitations.

#### Scenario: remote share is steady-state
- **WHEN** caller reads `LANE_COVE_PROFILE.work_mode_distribution["remote"]`
- **THEN** value SHALL be approximately 0.18 (within ±0.02)

#### Scenario: distribution sums to 1
- **WHEN** caller reads `LANE_COVE_PROFILE.work_mode_distribution`
- **THEN** `sum(distribution.values())` SHALL approximate 1.0 within ±0.001

### Requirement: scripted_plan SHALL restrict child agents' destinations

`build_scripted_plan` MUST post-process child-aged agents to limit their
destination autonomy:

- `profile.age < 6`: every step's destination SHALL be `profile.home_location`,
  action SHALL be `"stay"`
- `profile.age 6-12`: commute / school-pickup destinations preserved; meal /
  end-of-day destinations forced to `home_location`; errand / outing
  destinations forced to `home_location`; leisure may be preserved

The post-process runs after `_meal_steps` + `_reroute_school_pickup` so
all upstream destinations exist before clamping.

#### Scenario: toddler stays home
- **WHEN** build_scripted_plan runs for a 4-year-old agent
- **THEN** every plan step's destination SHALL == `profile.home_location`
  and action SHALL == `"stay"`

#### Scenario: school-age child commutes to school only
- **WHEN** build_scripted_plan runs for a 9-year-old agent with kids in
  family_composition
- **THEN** commute step destination SHALL be a school building (from work_pool);
  errand / outing steps SHALL be at home_location

#### Scenario: teen unrestricted
- **WHEN** build_scripted_plan runs for a 15-year-old agent
- **THEN** no destination restriction SHALL apply (age >= 13 path)
