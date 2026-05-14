## ADDED Requirements

### Requirement: OutdoorArea capacity field MUST default by area_type

`OutdoorArea` SHALL include `capacity: int | None = None` field. Default values
applied by `cartography/lanecove.py` at load time, keyed on `area_type`:

- cafe: 15
- restaurant: 20
- shop: 10
- park / street / square / school: None (unbounded)

`capacity = None` means unbounded; integer means hard cap on simultaneous occupants.

#### Scenario: cafe gets default capacity 15
- **WHEN** atlas loaded from OSM
- **THEN** any OutdoorArea with area_type="cafe" SHALL have capacity == 15

#### Scenario: park is unbounded
- **WHEN** atlas loaded
- **THEN** any OutdoorArea with area_type="park" SHALL have capacity == None


### Requirement: POIHeatModel MUST track per-location occupancy

`synthetic_socio_wind_tunnel/atlas/heat.py::POIHeatModel` SHALL provide
per-tick occupancy tracking with the following API:
- `register_arrival(location_id, agent_id) -> None`
- `register_departure(location_id, agent_id) -> None`
- `current_occupancy(location_id) -> int`
- `is_full(location_id) -> bool`  (occupancy >= capacity)

#### Scenario: occupancy increments on arrival
- **WHEN** 5 agents register_arrival to cafe_main
- **THEN** current_occupancy("cafe_main") SHALL == 5

#### Scenario: full check
- **WHEN** cafe_main capacity=15, 15 agents arrived, no departures
- **THEN** is_full("cafe_main") SHALL == True
