# Synthetic Socio Wind Tunnel

An AI multi-agent urban social simulation system for studying **hyperlocal boundary penetration (超在地性边界渗透)** — how digital interventions can dissolve invisible social barriers in high-density urban communities. Built on a **CQRS (Command Query Responsibility Segregation)** architecture.

## Implementation Status

| Component | Status | Description |
|-----------|--------|-------------|
| Atlas (布景组) | ✅ Complete | Static map with buildings, rooms, doors, containers |
| Ledger (道具组) | ✅ Complete | Dynamic state with entities, items, door/container states |
| SimulationService | ✅ Complete | Movement, door operations, clue discovery |
| CollapseService | ✅ Complete | Schrödinger detail generation with spatial budget |
| PerceptionPipeline | ✅ Complete | Multi-modal perception with filter chain |
| Cartography | ✅ Complete | GeoJSON import and programmatic building |
| Spatial Budget | ✅ Complete | Container capacity limits |
| Evidence Blueprint | ✅ Complete | Plot-required evidence constraints |
| Door/Lock System | ✅ Complete | Doors with key requirements |
| Rashomon Effect | ✅ Complete | Observer-dependent perception |
| NavigationService | ✅ Complete | Route planning with door awareness |
| ExplorationService | ✅ Complete | Visibility-based cognitive map |
| Error Codes & Events | ✅ Complete | Structured error handling and event system |

## The Theater Model (剧组模型)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           应用层 (Application)                           │
│                 CharacterAgents │ Game │ CLI                            │
└────────────────────────────────────────────────────────────────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        │                          │                          │
        ▼                          ▼                          ▼
┌────────────────────┐    ┌────────────────────┐    ┌────────────────────┐
│  引擎层 (WRITE)     │    │  感知层 (READ)      │    │  制图服务 (OFFLINE)  │
│                    │    │                    │    │                    │
│  SimulationService │    │  PerceptionPipeline│    │  GeoJSONImporter   │
│  CollapseService   │    │  Filters           │    │  RegionBuilder     │
└────────────────────┘    └────────────────────┘    └────────────────────┘
        │                          │                          │
        │ write                    │ read                     │ output
        ▼                          ▼                          ▼
┌────────────────────────────────────────────────────────────────────────┐
│                           数据层 (Data Layer)                            │
│  ┌─────────────────────┐    ┌─────────────────────┐                    │
│  │  Atlas (布景组)       │    │  Ledger (道具组)     │                    │
│  │  只读静态地图         │    │  读写动态状态         │                    │
│  │  墙、门、容器定义      │    │  位置、物品、证据     │                    │
│  └─────────────────────┘    └─────────────────────┘                    │
└────────────────────────────────────────────────────────────────────────┘
```

## Installation

```bash
cd Synthetic_Socio_Wind_Tunnel
pip install -e ".[dev]"      # Development with pytest
pip install -e ".[full]"     # With LLM + Web editor (optional)
```

## Quick Start

```python
from synthetic_socio_wind_tunnel import (
    Atlas, Ledger, SimulationService, CollapseService,
    PerceptionPipeline, ObserverContext, ExplorationService
)
from synthetic_socio_wind_tunnel.cartography.builder import RegionBuilder
from synthetic_socio_wind_tunnel.atlas.models import Material

# Build a simple map programmatically
region = (
    RegionBuilder("my_town", "My Town")
    .add_building("house", "Old House")
        .material(Material.WOOD)
        .polygon([(0, 0), (10, 0), (10, 8), (0, 8)])
        .add_room("living_room", "Living Room")
            .room_polygon([(0, 0), (6, 0), (6, 8), (0, 8)])
            .add_container("bookshelf", "Bookshelf", "bookshelf", item_capacity=20)
            .end_room()
        .add_room("kitchen", "Kitchen")
            .room_polygon([(6, 0), (10, 0), (10, 8), (6, 8)])
            .connects_to("living_room")
            .end_room()
        .end_building()
    .build()
)

# Create services
atlas = Atlas(region)
ledger = Ledger()
sim = SimulationService(atlas, ledger)
perception = PerceptionPipeline(atlas, ledger)

# Move character
result = sim.move_entity("emma", "living_room")
print(f"Move: {result.message}")

# Get subjective view
view = perception.render(ObserverContext(
    entity_id="emma",
    position=atlas.get_center("living_room"),
    skills={"investigation": 0.9},
))
print(view.narrative)
```

## Key Features

### 1. Spatial Budget System (空间预算系统)

Containers have capacity limits defined in Atlas:

```python
# Atlas defines the physical container
container_def = atlas.get_container_def("desk")
# → item_capacity=8, surface_capacity=6

# CollapseService respects these limits when generating
budget = collapse.get_room_spatial_budget("office")
# → total_capacity=39, containers={desk: {capacity: 8, used: 0}, ...}
```

### 2. Evidence Blueprint System (证据蓝图系统)

Plot-required evidence is guaranteed to appear:

```python
# In ledger
evidence_blueprints = {
    "poison_bottle": {
        "required_in": "desk_drawer_bottom",
        "must_contain": ["small glass bottle", "residue"],
        "discoverable_facts": ["The poison was purchased recently"]
    }
}

# When examined, CollapseService ensures evidence appears
detail = collapse.examine_container("desk_drawer_bottom", "emma", "office")
# → Includes poison bottle with constrained details
```

### 3. Door/Lock System (门锁系统)

Doors have static definitions in Atlas and dynamic state in Ledger:

```python
# Static definition
door = atlas.get_door("door_lobby_office")
# → can_lock=True, lock_key_id="office_key"

# Dynamic state
sim.lock_door("door_lobby_office", "librarian")  # Requires key
sim.unlock_door("door_lobby_office", "librarian")
```

### 4. Navigation Service (导航服务)

Complete route planning with door awareness:

```python
from synthetic_socio_wind_tunnel import NavigationService
from synthetic_socio_wind_tunnel.engine.navigation import PathStrategy

nav = NavigationService(atlas, ledger)

# Find route between any two locations
result = nav.find_route("reading_room", "kitchen")
print(result.describe())

# Different path strategies
result = nav.find_route("office", "kitchen", strategy=PathStrategy.AVOID_LOCKED)
result = nav.find_route("office", "kitchen", strategy=PathStrategy.FEWEST_DOORS)

# Get reachable locations
nearby = nav.get_reachable_locations("lobby", max_distance=50.0)
```

### 5. Exploration Service (探索服务 / 认知地图)

Characters don't instantly know all building layouts - they must explore:

```python
from synthetic_socio_wind_tunnel import ExplorationService

exploration = ExplorationService(atlas, ledger)

# What can Emma see from the lobby?
visible = exploration.what_can_i_see("emma", "lobby")

# Get detailed layout info
layout = exploration.get_visible_layout("emma", "lobby")
print(layout.current_room)      # Full info (current location)
print(layout.visible_adjacent)  # Partial info (through doors)
print(layout.known_locations)   # Memory (previously explored)

# Moving auto-records exploration
result = sim.move_entity("emma", "kitchen")
print(result.data["is_new_discovery"])  # True if first visit
```

### 6. Rashomon Effect (罗生门效应)

Same location, different experiences:

```python
# Detective Emma (high skill, relevant knowledge)
emma_ctx = ObserverContext(
    entity_id="emma",
    position=atlas.get_center("office"),
    skills={"investigation": 0.9},
    knowledge=["victim was poisoned"],
    suspicions=["linda"],
)
emma_view = perception.render(emma_ctx)
# → Notices clues, interprets evidence

# Random Visitor (low skill, no context)
visitor_ctx = ObserverContext(
    entity_id="visitor",
    position=atlas.get_center("office"),
    skills={"investigation": 0.2},
)
visitor_view = perception.render(visitor_ctx)
# → Basic observation, misses subtleties
```

### 7. Multi-Modal Perception (多模态感知)

Visual, auditory, and olfactory observations:

```python
view = perception.render(context)
print(view.ambient_sounds)  # ['page_turning', 'clock_ticking']
print(view.ambient_smells)  # ['old_books', 'wood_polish']

# Observations include sense type
for obs in view.observations:
    print(f"{obs.sense}: {obs.interpreted}")
```

### 8. Filter Chain (滤镜链)

Pluggable filters modify observations:

```python
from synthetic_socio_wind_tunnel.perception.filters import EnvironmentalFilter, SkillFilter

pipeline = PerceptionPipeline(atlas, ledger, filters=[
    EnvironmentalFilter(atlas, ledger),  # Lighting/weather effects
    SkillFilter(atlas, ledger),          # Skill-based filtering
])
```

## Project Structure

```
synthetic_socio_wind_tunnel/
├── synthetic_socio_wind_tunnel/
│   ├── __init__.py           # Public API
│   ├── core/                  # Shared types (Coord, Polygon)
│   ├── atlas/                 # 🎭 Static Map (Read-Only)
│   │   ├── models.py          # Region, Building, Room, DoorDef, ContainerDef
│   │   └── service.py         # Atlas queries
│   ├── ledger/                # 📋 Dynamic State (Read-Write)
│   │   ├── models.py          # EntityState, ItemState, DoorState, EvidenceBlueprint
│   │   └── service.py         # Ledger CRUD
│   ├── engine/                # ⚙️ Write Operations
│   │   ├── simulation.py      # SimulationService
│   │   └── collapse.py        # CollapseService
│   ├── perception/            # 📷 Read Operations
│   │   ├── models.py          # ObserverContext, SubjectiveView, Snapshots
│   │   ├── pipeline.py        # PerceptionPipeline
│   │   ├── exploration.py     # ExplorationService (cognitive map)
│   │   └── filters/           # Environmental, Audio, Olfactory, Skill
│   └── cartography/           # 🗺️ Map Building (Offline)
│       ├── importer.py        # GeoJSON import
│       └── builder.py         # Programmatic building
├── tests/                     # Test suite
└── docs/                      # Documentation
```

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Verify imports
python -c "from synthetic_socio_wind_tunnel import *; print('All imports OK')"
```

## Architecture Benefits

1. **High Cohesion, Low Coupling**: Each module has single responsibility
2. **CQRS Pattern**: Read/write operations are separated
3. **Save/Load Simplicity**: Only Ledger needs serialization
4. **Test Friendly**: Each component can be tested independently
5. **AI Separation**: CollapseService (creation) vs PerceptionPipeline (rendering)

## See Also

- [项目Brief](docs/项目Brief.md) - Full project brief: theory, experiments, and research framework
- [Agent System Design](docs/agent_system/) - Architecture for the 1,000-agent simulation
- [Map Pipeline](docs/map_pipeline/) - OSM import and programmatic map building guide

## License

MIT
