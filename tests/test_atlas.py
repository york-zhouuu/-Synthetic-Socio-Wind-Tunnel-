"""Tests for the Atlas module."""

import pytest
from synthetic_socio_wind_tunnel.atlas.models import (
    Coord,
    Polygon,
    Building,
    Room,
    OutdoorArea,
    Region,
    Material,
    BorderType,
    BorderZone,
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

    def test_building_type(self, simple_building):
        assert simple_building.building_type == "office"

    def test_room_type(self, simple_room):
        assert simple_room.room_type == "office"


class TestOutdoorArea:
    """Tests for OutdoorArea model."""

    def test_park_area_type(self, simple_outdoor_area):
        assert simple_outdoor_area.area_type == "park"
        assert not simple_outdoor_area.is_street

    def test_street_segment(self, simple_street_segment):
        assert simple_street_segment.area_type == "street"
        assert simple_street_segment.is_street
        assert simple_street_segment.road_name == "Main Street"
        assert simple_street_segment.segment_index == 0


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
        location = atlas.find_location_at(Coord(x=5, y=5))
        assert location in ["test_building", "test_room"]

        location = atlas.find_location_at(Coord(x=30, y=10))
        assert location == "test_park"

    def test_distance_between(self, atlas):
        dist = atlas.distance_between("test_building", "test_park")
        assert dist is not None
        assert dist > 0

    def test_get_connections(self, atlas):
        conns = atlas.get_connections("test_building")
        assert len(conns) == 1
        assert conns[0][0] == "test_park"

    def test_are_adjacent(self, atlas):
        assert atlas.are_adjacent("test_building", "test_park")
        assert not atlas.are_adjacent("test_building", "nonexistent")


class TestAtlasCommunity:
    """Tests for community-style Atlas queries."""

    def test_list_street_segments(self, community_atlas):
        streets = community_atlas.list_street_segments()
        assert len(streets) == 1
        assert streets[0].id == "main_st_seg_1"

    def test_list_open_spaces(self, community_atlas):
        spaces = community_atlas.list_open_spaces()
        assert len(spaces) == 1
        assert spaces[0].id == "test_park"

    def test_list_road_names(self, community_atlas):
        roads = community_atlas.list_road_names()
        assert "Main Street" in roads

    def test_list_buildings_by_type(self, community_atlas):
        offices = community_atlas.list_buildings_by_type("office")
        assert len(offices) == 1
        assert offices[0].id == "test_building"

        cafes = community_atlas.list_buildings_by_type("cafe")
        assert len(cafes) == 0

    def test_pathfinding_through_street(self, community_atlas):
        success, path, dist = community_atlas.find_path("test_building", "test_park")
        assert success
        assert path == ["test_building", "main_st_seg_1", "test_park"]
        assert dist == 10.0

    def test_locations_within_radius(self, community_atlas):
        center = Coord(x=15, y=0)
        nearby = community_atlas.locations_within_radius(center, 20.0)
        ids = [lid for lid, _ in nearby]
        assert "main_st_seg_1" in ids
        assert "test_building" in ids

    def test_locations_within_radius_of(self, community_atlas):
        nearby = community_atlas.locations_within_radius_of("main_st_seg_1", 20.0)
        ids = [lid for lid, _ in nearby]
        assert "test_building" in ids

    def test_get_building_info(self, community_atlas):
        info = community_atlas.get_building_info("test_building")
        assert info is not None
        assert info["type"] == "office"
        assert info["name"] == "Test Building"
        assert len(info["rooms"]) == 1
        assert info["rooms"][0]["type"] == "office"

    def test_get_region_overview(self, community_atlas):
        overview = community_atlas.get_region_overview()
        assert overview["id"] == "test_community"
        assert len(overview["buildings"]) == 1
        assert len(overview["outdoor_areas"]) == 2
        assert len(overview["borders"]) == 1
        assert "Main Street" in overview["road_names"]

    def test_list_all_locations(self, community_atlas):
        locations = community_atlas.list_all_locations()
        types = {loc["id"]: loc["type"] for loc in locations}
        assert types["test_building"] == "building"
        assert types["main_st_seg_1"] == "street"
        assert types["test_park"] == "outdoor"


class TestAtlasBorders:
    """Tests for border zone queries."""

    def test_get_border(self, community_atlas):
        border = community_atlas.get_border("test_border")
        assert border is not None
        assert border.name == "Test Border"
        assert border.border_type == BorderType.PHYSICAL
        assert border.permeability == 0.3

    def test_list_borders(self, community_atlas):
        borders = community_atlas.list_borders()
        assert len(borders) == 1

        physical = community_atlas.list_borders(BorderType.PHYSICAL)
        assert len(physical) == 1

        social = community_atlas.list_borders(BorderType.SOCIAL)
        assert len(social) == 0

    def test_get_border_between_locations(self, community_atlas):
        border = community_atlas.get_border_between_locations(
            "test_building", "test_park"
        )
        assert border is not None
        assert border.border_id == "test_border"

        # Same side — no border between
        border = community_atlas.get_border_between_locations(
            "test_building", "main_st_seg_1"
        )
        assert border is None

    def test_get_border_side(self, community_atlas):
        assert community_atlas.get_border_side("test_border", "test_building") == "a"
        assert community_atlas.get_border_side("test_border", "test_park") == "b"
        assert community_atlas.get_border_side("test_border", "nonexistent") is None

    def test_locations_on_same_side(self, community_atlas):
        same = community_atlas.locations_on_same_side(
            "test_border", "test_building", "main_st_seg_1"
        )
        assert same is True

        different = community_atlas.locations_on_same_side(
            "test_border", "test_building", "test_park"
        )
        assert different is False


class TestAtlasLineOfSight:
    """Tests for line of sight calculations."""

    def test_can_see_no_obstacles(self, atlas):
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
