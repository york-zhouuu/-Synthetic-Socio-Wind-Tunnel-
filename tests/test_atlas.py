"""Tests for the Atlas module."""

import pytest
from synthetic_socio_wind_tunnel.atlas.models import (
    Coord,
    Polygon,
    Building,
    Room,
    Region,
    Material,
)
from synthetic_socio_wind_tunnel.atlas.service import Atlas


class TestCoord:
    """Tests for Coord model."""

    def test_distance_to_same_point(self):
        c = Coord(x=5, y=5)
        assert c.distance_to(c) == 0

    def test_distance_to_horizontal(self):
        c1 = Coord(x=0, y=0)
        c2 = Coord(x=10, y=0)
        assert c1.distance_to(c2) == 10

    def test_distance_to_diagonal(self):
        c1 = Coord(x=0, y=0)
        c2 = Coord(x=3, y=4)
        assert c1.distance_to(c2) == 5  # 3-4-5 triangle

    def test_hash(self):
        c1 = Coord(x=5, y=10)
        c2 = Coord(x=5, y=10)
        assert hash(c1) == hash(c2)


class TestPolygon:
    """Tests for Polygon model."""

    def test_contains_point_inside(self, simple_polygon):
        point = Coord(x=5, y=5)
        assert simple_polygon.contains(point)

    def test_contains_point_outside(self, simple_polygon):
        point = Coord(x=15, y=15)
        assert not simple_polygon.contains(point)

    def test_contains_point_on_edge(self, simple_polygon):
        # Points on edge may or may not be considered inside
        # depending on implementation - just ensure no crash
        point = Coord(x=0, y=5)
        simple_polygon.contains(point)  # Should not raise

    def test_center_square(self, simple_polygon):
        center = simple_polygon.center
        assert center.x == 5
        assert center.y == 5

    def test_bounds(self, simple_polygon):
        min_c, max_c = simple_polygon.bounds
        assert min_c.x == 0
        assert min_c.y == 0
        assert max_c.x == 10
        assert max_c.y == 10

    def test_empty_polygon(self):
        p = Polygon(vertices=())
        assert p.center.x == 0
        assert p.center.y == 0


class TestBuilding:
    """Tests for Building model."""

    def test_get_room(self, simple_building):
        room = simple_building.rooms.get("test_room")
        assert room is not None
        assert room.name == "Test Room"

    def test_get_nonexistent_room(self, simple_building):
        room = simple_building.rooms.get("nonexistent")
        assert room is None

    def test_center(self, simple_building):
        center = simple_building.center
        assert center.x == 5
        assert center.y == 5


class TestAtlas:
    """Tests for Atlas service."""

    def test_get_building(self, atlas):
        building = atlas.get_building("test_building")
        assert building is not None
        assert building.name == "Test Building"

    def test_get_nonexistent_building(self, atlas):
        building = atlas.get_building("nonexistent")
        assert building is None

    def test_get_room(self, atlas):
        room = atlas.get_room("test_room")
        assert room is not None
        assert room.name == "Test Room"

    def test_get_outdoor_area(self, atlas):
        area = atlas.get_outdoor_area("test_park")
        assert area is not None
        assert area.name == "Test Park"

    def test_get_center(self, atlas):
        center = atlas.get_center("test_building")
        assert center is not None
        assert center.x == 5
        assert center.y == 5

    def test_list_buildings(self, atlas):
        buildings = atlas.list_buildings()
        assert "test_building" in buildings

    def test_list_outdoor_areas(self, atlas):
        areas = atlas.list_outdoor_areas()
        assert "test_park" in areas

    def test_list_rooms(self, atlas):
        rooms = atlas.list_rooms("test_building")
        assert "test_room" in rooms

    def test_find_location_at(self, atlas):
        # Point inside building/room
        location = atlas.find_location_at(Coord(x=5, y=5))
        # Should find either building or room
        assert location in ["test_building", "test_room"]

        # Point in park
        location = atlas.find_location_at(Coord(x=30, y=10))
        assert location == "test_park"

    def test_distance_between(self, atlas):
        dist = atlas.distance_between("test_building", "test_park")
        assert dist is not None
        assert dist > 0

    def test_get_connections(self, atlas):
        conns = atlas.get_connections("test_building")
        assert len(conns) == 1
        assert conns[0][0] == "test_park"  # (neighbor_id, distance)

    def test_are_adjacent(self, atlas):
        assert atlas.are_adjacent("test_building", "test_park")
        assert not atlas.are_adjacent("test_building", "nonexistent")


class TestAtlasLineOfSight:
    """Tests for line of sight calculations."""

    def test_can_see_no_obstacles(self, atlas):
        # Both points in park - should be visible
        from_coord = Coord(x=25, y=10)
        to_coord = Coord(x=35, y=10)
        can_see, obstacles = atlas.can_see(from_coord, to_coord)
        assert can_see
        assert len(obstacles) == 0


class TestAtlasPathfinding:
    """Tests for pathfinding."""

    def test_find_path_connected(self, atlas):
        success, path, distance = atlas.find_path("test_building", "test_park")
        assert success
        assert len(path) >= 2

    def test_find_path_same_location(self, atlas):
        success, path, distance = atlas.find_path("test_building", "test_building")
        assert success
        assert distance == 0

    def test_find_path_unknown(self, atlas):
        success, path, distance = atlas.find_path("test_building", "nonexistent")
        assert not success


class TestAtlasFromJson:
    """Tests for JSON loading."""

    def test_load_maple_creek(self, maple_creek_atlas):
        assert maple_creek_atlas.region_id == "maple_creek"
        assert "library" in maple_creek_atlas.list_buildings()
        assert "town_square" in maple_creek_atlas.list_outdoor_areas()
