## ADDED Requirements

### Requirement: AgentProfile household_id field

`AgentProfile` SHALL include a `household_id: str` field (default
`"household_<agent_id>"` for backwards compat — solo households) and
`household_role: Literal["parent", "child", "partner", "lone"] = "lone"`.

Multiple agents with the same `household_id` SHALL share the same
`home_location` value.

#### Scenario: backwards compat with current tests
- **WHEN** AgentProfile constructed without household_id / household_role
- **THEN** household_id SHALL default to `f"household_{agent_id}"`; household_role SHALL be "lone"

#### Scenario: same household_id implies shared home_location
- **WHEN** sample_population produces 4 agents with the same household_id
- **THEN** all 4 SHALL have identical home_location values


### Requirement: sample_population SHALL build household units first

`sample_population` SHALL sample household *units* per family_composition
distribution, allocate 1-5 agents per unit (couple_kids_under_15 → 4 agents
average, lone_person → 1, etc.), assign each unit a unique household_id and
shared home_location, then apportion individual ABS-dimension fields per
member.

#### Scenario: 1000 agents → reasonable household count
- **WHEN** sample_population(LANE_COVE_PROFILE × 1000)
- **THEN** distinct household_id count SHALL be in [300, 700] range


### Requirement: HouseholdRegistry SHALL provide membership lookup

`synthetic_socio_wind_tunnel/agent/household.py::HouseholdRegistry` SHALL
provide:
- `members_of(household_id) -> list[AgentProfile]`
- `home_location_for(household_id) -> str`
- `siblings_of(agent_id) -> list[AgentProfile]` (same household, excluding self)

#### Scenario: members_of returns all household agents
- **WHEN** registry built from 1000 agents and queried for a household with 3 members
- **THEN** members_of SHALL return all 3 (including the queried agent)


### Requirement: morning drop-off coordination MUST align parent leave with child wake

`build_scripted_plan` SHALL — when `household_context` provided and the agent has
household_role == "parent" with child siblings — produce a morning leave_time
within ±15 minutes of the earliest child's wake_time + commute_min,
representing school drop-off.

#### Scenario: parent leave time aligns with child wake
- **WHEN** parent agent + child agent same household, child.wake_time = "7:00"
- **THEN** parent's morning leave SHALL be in [6:45, 7:30] window


### Requirement: weekend co-trip MUST occur with ≈30% probability per household

`build_scripted_plan` SHALL — when `household_context` provided and weekend day —
produce ~30% probability of household members sharing a weekend leisure
destination (same weekend_outing_destination for ≥ 2 members in same household).

#### Scenario: weekend co-trip ≈ 30% rate
- **WHEN** 100 households simulated for weekend planning
- **THEN** ~ 25-35 households SHALL have ≥ 2 members at same weekend destination
