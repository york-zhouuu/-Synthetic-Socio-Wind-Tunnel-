"""Tests for cartography functionality (GeoJSON import and RegionBuilder)."""

import pytest
from synthetic_socio_wind_tunnel.cartography.importer import GeoJSONImporter
from synthetic_socio_wind_tunnel.cartography.builder import RegionBuilder
from synthetic_socio_wind_tunnel.atlas.models import Material


class TestGeoJSONImporter:
    """Tests for GeoJSON importer."""

    def test_import_simple_geojson(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [-0.001, 51.001],
                            [0.001, 51.001],
                            [0.001, 51.003],
                            [-0.001, 51.003],
                            [-0.001, 51.001]
                        ]]
                    },
                    "properties": {
                        "building": "yes",
                        "name": "Test Building"
                    }
                }
            ]
        }

        importer = GeoJSONImporter()
        region = importer.import_data(geojson, region_id="test")

        assert region.id == "test"
        assert len(region.buildings) == 1

    def test_import_with_bounds(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [0, 0], [1, 0], [1, 1], [0, 1], [0, 0]
                        ]]
                    },
                    "properties": {"building": "yes"}
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [10, 10], [11, 10], [11, 11], [10, 11], [10, 10]
                        ]]
                    },
                    "properties": {"building": "yes"}
                }
            ]
        }

        importer = GeoJSONImporter()

        # Import with bounds that only include first building
        bounds = {
            "min_lat": -1, "max_lat": 2,
            "min_lon": -1, "max_lon": 2
        }
        region = importer.import_data(geojson, bounds=bounds)

        assert len(region.buildings) == 1


class TestRegionBuilder:
    """Tests for RegionBuilder."""

    def test_build_simple_region(self):
        region = (
            RegionBuilder("test", "Test Region")
            .add_building("house", "House")
                .material(Material.WOOD)
                .polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
                .entrance((5, 0))
                .end_building()
            .add_outdoor("yard", "Yard")
                .polygon([(15, 0), (25, 0), (25, 10), (15, 10)])
                .surface("grass")
                .end_outdoor()
            .connect("house", "yard", "path")
            .build()
        )

        assert region.id == "test"
        assert "house" in region.buildings
        assert "yard" in region.outdoor_areas
        assert len(region.connections) == 1

    def test_build_with_rooms(self):
        region = (
            RegionBuilder("test", "Test")
            .add_building("library", "Library")
                .polygon([(0, 0), (20, 0), (20, 15), (0, 15)])
                .add_room("lobby", "Lobby")
                    .room_polygon([(0, 0), (10, 0), (10, 15), (0, 15)])
                    .containers(["desk"])  # Simple list form
                    .end_room()
                .add_room("reading", "Reading Room")
                    .room_polygon([(10, 0), (20, 0), (20, 15), (10, 15)])
                    .connects_to("lobby")
                    .end_room()
                .end_building()
            .build()
        )

        library = region.buildings["library"]
        assert len(library.rooms) == 2
        assert "lobby" in library.rooms
        assert "reading" in library.rooms

    def test_build_with_container_defs(self):
        """Test building with full ContainerDef support."""
        region = (
            RegionBuilder("test", "Test")
            .add_building("office", "Office")
                .polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
                .add_room("main", "Main Room")
                    .room_polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
                    .add_container(
                        container_id="desk",
                        name="Office Desk",
                        container_type="desk",
                        item_capacity=8,
                        surface_capacity=4,
                        can_lock=True,
                        search_difficulty=0.5,
                    )
                    .add_container(
                        container_id="cabinet",
                        name="Filing Cabinet",
                        container_type="cabinet",
                        item_capacity=20,
                        can_lock=True,
                        search_difficulty=0.7,
                    )
                    .end_room()
                .end_building()
            .build()
        )

        room = region.buildings["office"].rooms["main"]
        assert "desk" in room.containers
        assert "cabinet" in room.containers

        desk = room.containers["desk"]
        assert desk.name == "Office Desk"
        assert desk.item_capacity == 8
        assert desk.can_lock is True
        assert desk.search_difficulty == 0.5

    def test_fluent_chaining(self):
        # Test that all methods return self for chaining
        builder = RegionBuilder("test", "Test")
        result = builder.add_building("b", "B")
        assert result is builder

        result = builder.material(Material.BRICK)
        assert result is builder

        result = builder.polygon([(0, 0), (1, 1), (0, 1)])
        assert result is builder

    def test_auto_calculate_distance(self):
        region = (
            RegionBuilder("test", "Test")
            .add_building("a", "Building A")
                .polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
                .end_building()
            .add_building("b", "Building B")
                .polygon([(20, 0), (30, 0), (30, 10), (20, 10)])
                .end_building()
            .connect("a", "b", "path")  # No explicit distance
            .build()
        )

        # Distance should be calculated from centers
        conn = region.connections[0]
        assert conn.distance > 0
        # Center of A is (5,5), center of B is (25,5), distance = 20
        assert abs(conn.distance - 20) < 0.1
