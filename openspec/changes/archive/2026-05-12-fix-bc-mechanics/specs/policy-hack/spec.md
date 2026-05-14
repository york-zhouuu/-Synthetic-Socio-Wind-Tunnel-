## ADDED Requirements

### Requirement: Variant push count SHALL be equalized for paired-mirror

Variant push counts SHALL default to identical values across hp and gd.
To isolate "where pushes point" from "how many pushes happen",
`HyperlocalPushVariant.daily_push_count` and
`GlobalDistractionVariant.daily_push_count` SHALL default to the SAME
value (5). Previously hp had 1/day and gd had 20/day — confounding
direction (local vs distant) with frequency.

`HyperlocalPushVariant.hyperlocal_radius_m` SHALL default to 1000.0 m
(aligned with CLAUDE.md canonical hyperlocal radius), not the legacy 500m.

#### Scenario: hp and gd default to same push count
- **WHEN** `HyperlocalPushVariant()` and `GlobalDistractionVariant()` are
  constructed with defaults
- **THEN** both SHALL have `daily_push_count == 5`

#### Scenario: hp radius aligned with thesis canonical value
- **WHEN** `HyperlocalPushVariant()` is constructed
- **THEN** `instance.hyperlocal_radius_m` SHALL == 1000.0

#### Scenario: explicit override preserved
- **WHEN** `GlobalDistractionVariant(daily_push_count=10)` is constructed
- **THEN** `instance.daily_push_count` SHALL == 10 (override beats default)
