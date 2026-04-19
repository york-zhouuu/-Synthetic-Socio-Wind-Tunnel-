"""Pytest configuration and fixtures for synthetic-socio-wind-tunnel tests."""

import pytest
from pathlib import Path

from synthetic_socio_wind_tunnel.atlas.models import (
    Region,
    Building,
    Room,
    OutdoorArea,
    Connection,
    Coord,
    Polygon,
    Material,
    ContainerDef,
    BorderType,
    BorderZone,
)
from synthetic_socio_wind_tunnel.atlas.service import Atlas
from synthetic_socio_wind_tunnel.ledger.models import LedgerData, EntityState
from synthetic_socio_wind_tunnel.ledger.service import Ledger
from synthetic_socio_wind_tunnel.perception.pipeline import PerceptionPipeline
from synthetic_socio_wind_tunnel.engine.simulation import SimulationService


@pytest.fixture
def simple_polygon():
    """A simple square polygon."""
    return Polygon(vertices=(
        Coord(x=0, y=0),
        Coord(x=10, y=0),
        Coord(x=10, y=10),
        Coord(x=0, y=10),
    ))


@pytest.fixture
def simple_room(simple_polygon):
    """A simple room."""
    return Room(
        id="test_room",
        name="Test Room",
        room_type="office",
        polygon=simple_polygon,
        floor=0,
        connected_rooms=frozenset(),
        containers={
            "desk": ContainerDef(
                container_id="desk",
                name="Desk",
                container_type="desk",
                item_capacity=5,
                surface_capacity=3,
            )
        },
    )


@pytest.fixture
def simple_building(simple_polygon, simple_room):
    """A simple building with one room."""
    return Building(
        id="test_building",
        name="Test Building",
        building_type="office",
        polygon=simple_polygon,
        exterior_material=Material.BRICK,
        floors=1,
        entrance_coord=Coord(x=5, y=0),
        rooms={"test_room": simple_room},
    )


@pytest.fixture
def simple_outdoor_area():
    """A simple outdoor area (park)."""
    return OutdoorArea(
        id="test_park",
        name="Test Park",
        area_type="park",
        polygon=Polygon(vertices=(
            Coord(x=20, y=0),
            Coord(x=40, y=0),
            Coord(x=40, y=20),
            Coord(x=20, y=20),
        )),
        surface="grass",
        vegetation_density=0.3,
    )


@pytest.fixture
def simple_street_segment():
    """A simple street segment."""
    return OutdoorArea(
        id="main_st_seg_1",
        name="Main Street (1)",
        area_type="street",
        polygon=Polygon(vertices=(
            Coord(x=10, y=-3),
            Coord(x=20, y=-3),
            Coord(x=20, y=3),
            Coord(x=10, y=3),
        )),
        surface="asphalt",
        vegetation_density=0.0,
        road_name="Main Street",
        segment_index=0,
    )


@pytest.fixture
def community_region(simple_building, simple_outdoor_area, simple_street_segment):
    """
    A community-style Region with building, street segment, and park.

    Layout:
        [Building] --entrance--> [Street Seg] --entrance--> [Park]
    """
    return Region(
        id="test_community",
        name="Test Community",
        bounds_min=Coord(x=0, y=-3),
        bounds_max=Coord(x=40, y=20),
        buildings={"test_building": simple_building},
        outdoor_areas={
            "test_park": simple_outdoor_area,
            "main_st_seg_1": simple_street_segment,
        },
        connections=(
            Connection(
                from_id="test_building",
                to_id="main_st_seg_1",
                path_type="entrance",
                distance=5.0,
            ),
            Connection(
                from_id="main_st_seg_1",
                to_id="test_park",
                path_type="entrance",
                distance=5.0,
            ),
        ),
        borders={
            "test_border": BorderZone(
                border_id="test_border",
                name="Test Border",
                border_type=BorderType.PHYSICAL,
                side_a=("test_building", "main_st_seg_1"),
                side_b=("test_park",),
                permeability=0.3,
                description="A fence separating the building area from the park.",
            ),
        },
    )


# Keep backward-compatible simple_region fixture
@pytest.fixture
def simple_region(simple_building, simple_outdoor_area):
    """Simple Region for testing (backward compat)."""
    return Region(
        id="test_region",
        name="Test Region",
        bounds_min=Coord(x=0, y=0),
        bounds_max=Coord(x=40, y=20),
        buildings={"test_building": simple_building},
        outdoor_areas={"test_park": simple_outdoor_area},
        connections=(
            Connection(
                from_id="test_building",
                to_id="test_park",
                path_type="path",
                distance=15.0,
            ),
        ),
    )


@pytest.fixture
def atlas(simple_region):
    """Atlas service with simple test data."""
    return Atlas(simple_region)


@pytest.fixture
def community_atlas(community_region):
    """Atlas service with community-style test data."""
    return Atlas(community_region)


@pytest.fixture
def ledger():
    """Ledger service with empty state."""
    return Ledger()


@pytest.fixture
def simulation(atlas, ledger):
    """SimulationService with atlas and ledger."""
    return SimulationService(atlas, ledger)


@pytest.fixture
def perception(atlas, ledger):
    """PerceptionPipeline with atlas and ledger."""
    return PerceptionPipeline(atlas, ledger)


@pytest.fixture
def maple_creek_dir():
    """Path to maple creek example data."""
    return Path(__file__).parent.parent / "examples" / "maple_creek"


@pytest.fixture
def maple_creek_atlas(maple_creek_dir):
    """Atlas loaded with maple creek data."""
    atlas_path = maple_creek_dir / "atlas.json"
    if not atlas_path.exists():
        pytest.skip("Maple Creek example data not found")
    return Atlas.from_json(atlas_path)


@pytest.fixture
def maple_creek_ledger(maple_creek_dir):
    """Ledger loaded with maple creek data."""
    ledger_path = maple_creek_dir / "ledger.json"
    if not ledger_path.exists():
        pytest.skip("Maple Creek example data not found")
    return Ledger.from_json(ledger_path)
