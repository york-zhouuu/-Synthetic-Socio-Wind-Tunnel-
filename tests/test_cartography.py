"""Tests for cartography functionality (GeoJSON import and RegionBuilder)."""

import json
import re
import tempfile
from collections import defaultdict
from pathlib import Path

import pytest
from synthetic_socio_wind_tunnel.cartography.importer import GeoJSONImporter
from synthetic_socio_wind_tunnel.cartography.builder import RegionBuilder
from synthetic_socio_wind_tunnel.cartography.conflation import (
    merge_sources,
    category_to_activity,
)
from synthetic_socio_wind_tunnel.atlas.models import Material, BorderType
from synthetic_socio_wind_tunnel.atlas.service import Atlas


LANECOVE_GEOJSON = (
    Path(__file__).parent.parent / "data" / "lanecove_osm.geojson"
)
ENRICHED_LANECOVE_GEOJSON = (
    Path(__file__).parent.parent / "data" / "lanecove_enriched.geojson"
)


def _building_main_component_share(region) -> float:
    """Share of buildings in the largest connected component of the region."""
    adj: dict[str, set[str]] = defaultdict(set)
    for c in region.connections:
        adj[c.from_id].add(c.to_id)
        adj[c.to_id].add(c.from_id)

    all_ids = set(region.buildings) | set(region.outdoor_areas)
    visited: set[str] = set()
    components: list[list[str]] = []
    for start in all_ids:
        if start in visited:
            continue
        stack = [start]
        comp: list[str] = []
        while stack:
            n = stack.pop()
            if n in visited:
                continue
            visited.add(n)
            comp.append(n)
            for nb in adj.get(n, ()):
                if nb not in visited:
                    stack.append(nb)
        components.append(comp)

    if not components:
        return 0.0
    main = set(max(components, key=len))
    in_main = sum(1 for b in region.buildings if b in main)
    return in_main / max(1, len(region.buildings))


class TestGeoJSONImporter:
    """Tests for GeoJSON importer."""

    def test_import_simple_building(self):
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

    def test_import_building_with_amenity(self):
        """Test that amenity tags are extracted as building_type."""
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [0, 0], [0.001, 0], [0.001, 0.001], [0, 0.001], [0, 0]
                        ]]
                    },
                    "properties": {
                        "building": "yes",
                        "amenity": "cafe",
                        "name": "Test Cafe"
                    }
                }
            ]
        }

        importer = GeoJSONImporter()
        region = importer.import_data(geojson, region_id="test")

        building = list(region.buildings.values())[0]
        assert building.building_type == "cafe"
        assert "amenity" in building.osm_tags

    def test_import_road_linestring(self):
        """Test that LineString roads are converted to street segments."""
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [0, 0], [0.01, 0], [0.02, 0]
                        ]
                    },
                    "properties": {
                        "highway": "residential",
                        "name": "Test Road"
                    }
                }
            ]
        }

        importer = GeoJSONImporter()
        region = importer.import_data(geojson, region_id="test", segment_length=50.0)

        # Should have street segments
        streets = [a for a in region.outdoor_areas.values() if a.is_street]
        assert len(streets) >= 1
        assert streets[0].road_name == "Test Road"
        assert streets[0].area_type == "street"
        assert streets[0].surface == "asphalt"

    def test_import_auto_connections(self):
        """Test that connections are auto-inferred."""
        geojson = {
            "type": "FeatureCollection",
            "features": [
                # A building
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [0, 0.0005], [0.0005, 0.0005],
                            [0.0005, 0.001], [0, 0.001], [0, 0.0005]
                        ]]
                    },
                    "properties": {"building": "yes", "name": "House"}
                },
                # A road passing nearby
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[0, 0], [0.002, 0]]
                    },
                    "properties": {"highway": "residential", "name": "Main St"}
                },
            ]
        }

        importer = GeoJSONImporter()
        region = importer.import_data(geojson, region_id="test")

        # Should have connections
        assert len(region.connections) > 0

        # Should have at least one entrance connection
        entrance_conns = [c for c in region.connections if c.path_type == "entrance"]
        assert len(entrance_conns) >= 1

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
        bounds = {
            "min_lat": -1, "max_lat": 2,
            "min_lon": -1, "max_lon": 2
        }
        region = importer.import_data(geojson, bounds=bounds)
        assert len(region.buildings) == 1

    def test_import_outdoor_area_type(self):
        """Test that outdoor area types are correctly inferred."""
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [0, 0], [0.001, 0], [0.001, 0.001], [0, 0.001], [0, 0]
                        ]]
                    },
                    "properties": {
                        "leisure": "playground",
                        "name": "Kids Playground"
                    }
                }
            ]
        }

        importer = GeoJSONImporter()
        region = importer.import_data(geojson, region_id="test")

        assert len(region.outdoor_areas) == 1
        area = list(region.outdoor_areas.values())[0]
        assert area.area_type == "playground"


class TestRegionBuilder:
    """Tests for RegionBuilder."""

    def test_build_simple_region(self):
        region = (
            RegionBuilder("test", "Test Region")
            .add_building("house", "House", building_type="residential")
                .material(Material.WOOD)
                .polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
                .entrance((5, 0))
                .end_building()
            .add_outdoor("yard", "Yard", area_type="garden")
                .polygon([(15, 0), (25, 0), (25, 10), (15, 10)])
                .surface("grass")
                .end_outdoor()
            .connect("house", "yard", "path")
            .build()
        )

        assert region.id == "test"
        assert "house" in region.buildings
        assert region.buildings["house"].building_type == "residential"
        assert "yard" in region.outdoor_areas
        assert region.outdoor_areas["yard"].area_type == "garden"
        assert len(region.connections) == 1

    def test_build_with_street_segments(self):
        region = (
            RegionBuilder("test", "Test")
            .add_building("cafe", "Café", building_type="cafe")
                .polygon([(0, 0), (10, 0), (10, 8), (0, 8)])
                .end_building()
            .add_street("main_st_1", "Main St (1)", road_name="Main Street")
                .polygon([(12, -3), (30, -3), (30, 3), (12, 3)])
                .segment_index(0)
                .end_outdoor()
            .add_street("main_st_2", "Main St (2)", road_name="Main Street")
                .polygon([(30, -3), (48, -3), (48, 3), (30, 3)])
                .segment_index(1)
                .end_outdoor()
            .connect("cafe", "main_st_1", "entrance")
            .connect("main_st_1", "main_st_2", "residential")
            .build()
        )

        assert region.buildings["cafe"].building_type == "cafe"

        seg1 = region.outdoor_areas["main_st_1"]
        assert seg1.is_street
        assert seg1.road_name == "Main Street"
        assert seg1.segment_index == 0

        seg2 = region.outdoor_areas["main_st_2"]
        assert seg2.segment_index == 1

    def test_build_with_rooms(self):
        region = (
            RegionBuilder("test", "Test")
            .add_building("library", "Library", building_type="library")
                .polygon([(0, 0), (20, 0), (20, 15), (0, 15)])
                .add_room("lobby", "Lobby", room_type="lobby")
                    .room_polygon([(0, 0), (10, 0), (10, 15), (0, 15)])
                    .containers(["desk"])
                    .end_room()
                .add_room("reading", "Reading Room", room_type="reading")
                    .room_polygon([(10, 0), (20, 0), (20, 15), (10, 15)])
                    .connects_to("lobby")
                    .end_room()
                .end_building()
            .build()
        )

        library = region.buildings["library"]
        assert library.building_type == "library"
        assert len(library.rooms) == 2

        lobby = library.rooms["lobby"]
        assert lobby.room_type == "lobby"

        reading = library.rooms["reading"]
        assert reading.room_type == "reading"

    def test_build_with_container_defs(self):
        """Test building with full ContainerDef support."""
        region = (
            RegionBuilder("test", "Test")
            .add_building("office", "Office", building_type="office")
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

    def test_build_with_borders(self):
        region = (
            RegionBuilder("test", "Test")
            .add_building("house_a", "House A", building_type="residential")
                .polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
                .end_building()
            .add_building("house_b", "House B", building_type="residential")
                .polygon([(30, 0), (40, 0), (40, 10), (30, 10)])
                .end_building()
            .add_border("railway", "Railway Line", BorderType.PHYSICAL)
                .border_sides(["house_a"], ["house_b"])
                .border_permeability(0.1)
                .border_description("A railway line separating the two blocks.")
                .end_border()
            .build()
        )

        assert "railway" in region.borders
        border = region.borders["railway"]
        assert border.border_type == BorderType.PHYSICAL
        assert border.permeability == 0.1
        assert "house_a" in border.side_a
        assert "house_b" in border.side_b

    def test_fluent_chaining(self):
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

        conn = region.connections[0]
        assert conn.distance > 0
        assert abs(conn.distance - 20) < 0.1


@pytest.mark.skipif(
    not LANECOVE_GEOJSON.exists(),
    reason="lanecove_osm.geojson not present — skip real-world connectivity gate",
)
class TestLaneCoveConnectivity:
    """Connectivity gate on the real Lane Cove OSM import.

    Guards against importer regressions that would reshatter the map graph.
    Imports straight from GeoJSON (no Riverview mock infill) to isolate the
    importer's own behaviour.
    """

    def test_building_main_component_share(self):
        importer = GeoJSONImporter()
        clip_bounds = {
            "min_lat": -33.835,
            "max_lat": -33.798,
            "min_lon": 151.145,
            "max_lon": 151.178,
        }
        region = importer.import_file(
            LANECOVE_GEOJSON,
            bounds=clip_bounds,
            region_id="lane_cove_test",
        )
        share = _building_main_component_share(region)
        # 85% is the floor we expect from OSM alone (no Riverview infill).
        # If this regresses, the importer graph is shattered again.
        assert share >= 0.85, (
            f"Only {share:.1%} of buildings in main component "
            f"(expected >= 85% after importer fixes)"
        )


class TestRegionBuilderAtlasIntegration:
    """Test that builder output works with Atlas service."""

    def test_builder_region_creates_valid_atlas(self):
        region = (
            RegionBuilder("community", "My Community")
            .add_building("cafe", "Sunrise Café", building_type="cafe")
                .polygon([(0, 0), (10, 0), (10, 8), (0, 8)])
                .active_hours(7, 22)
                .end_building()
            .add_street("main_st_1", "Main St (1)", road_name="Main Street")
                .polygon([(12, -3), (30, -3), (30, 3), (12, 3)])
                .segment_index(0)
                .end_outdoor()
            .add_outdoor("park", "Central Park", area_type="park")
                .polygon([(35, 0), (55, 0), (55, 20), (35, 20)])
                .end_outdoor()
            .connect("cafe", "main_st_1", "entrance")
            .connect("main_st_1", "park", "entrance")
            .add_border("divide", "The Divide", BorderType.SOCIAL)
                .border_sides(["cafe"], ["park"])
                .border_permeability(0.5)
                .end_border()
            .build()
        )

        atlas = Atlas(region)

        # Basic queries work
        assert atlas.get_building("cafe") is not None
        assert atlas.get_building("cafe").building_type == "cafe"

        # Street queries work
        streets = atlas.list_street_segments()
        assert len(streets) == 1

        roads = atlas.list_road_names()
        assert "Main Street" in roads

        # Pathfinding works
        success, path, dist = atlas.find_path("cafe", "park")
        assert success
        assert "main_st_1" in path

        # Border queries work
        border = atlas.get_border("divide")
        assert border is not None
        assert atlas.get_border_side("divide", "cafe") == "a"
        assert atlas.get_border_side("divide", "park") == "b"

        # Overview works
        overview = atlas.get_region_overview()
        assert len(overview["buildings"]) == 1
        assert len(overview["borders"]) == 1


# ────────────────────────────────────────────────────────────────────────────
# Conflation (enrich-lanecove-map change)
# ────────────────────────────────────────────────────────────────────────────

def _write_fc(tmp: Path, name: str, features: list) -> Path:
    p = tmp / name
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)
    return p


def _rect_polygon(lon0: float, lat0: float, lon1: float, lat1: float) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[
            [lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0],
        ]],
    }


class TestConflation:
    """Unit tests for conflation.merge_sources."""

    def test_category_to_activity_mapping(self):
        assert category_to_activity("eat_and_drink.coffee") == "eat"
        assert category_to_activity("shopping.supermarket") == "shop"
        assert category_to_activity("education.school") == "study"
        assert category_to_activity("health.clinic") == "medical"
        # Unknown prefix falls back to 'visit'
        assert category_to_activity("religion.synagogue") == "visit"
        assert category_to_activity(None) == "visit"

    def test_merges_overture_attrs_into_osm_building(self, tmp_path):
        osm_poly = {
            "type": "Feature",
            "geometry": _rect_polygon(151.150, -33.820, 151.151, -33.819),
            "properties": {"building": "yes", "name": "building_1"},
        }
        # Overture building with centroid inside the OSM polygon
        ov_bldg = {
            "type": "Feature",
            "geometry": _rect_polygon(151.1503, -33.8197, 151.1507, -33.8193),
            "properties": {
                "class": "commercial",
                "height": 9.0,
                "num_floors": 3,
                "names": {"primary": "Somebody's Block"},
                "confidence": 0.88,
            },
        }
        osm_path = _write_fc(tmp_path, "osm.geojson", [osm_poly])
        ob_path = _write_fc(tmp_path, "overture_bldgs.geojson", [ov_bldg])

        fc, stats = merge_sources(osm_path, ob_path, None)

        assert stats.overture_buildings_merged == 1
        assert stats.overture_buildings_added == 0
        # OSM feature is the only building feature, now carrying overture:* tags
        assert len(fc["features"]) == 1
        props = fc["features"][0]["properties"]
        assert props["name"] == "building_1"  # OSM name NOT overwritten
        assert props["overture:class"] == "commercial"
        assert props["overture:height"] == 9.0
        assert props["overture:num_floors"] == 3
        assert props["overture:primary_source"] == "osm"

    def test_merges_overture_building_without_osm_host(self, tmp_path):
        # OSM polygon far away
        osm_poly = {
            "type": "Feature",
            "geometry": _rect_polygon(151.100, -33.800, 151.101, -33.799),
            "properties": {"building": "yes"},
        }
        # Overture building elsewhere
        ov_bldg = {
            "type": "Feature",
            "geometry": _rect_polygon(151.160, -33.820, 151.161, -33.819),
            "properties": {
                "class": "residential",
                "names": {"primary": "Unit 5 Terrace"},
            },
        }
        osm_path = _write_fc(tmp_path, "osm.geojson", [osm_poly])
        ob_path = _write_fc(tmp_path, "overture_bldgs.geojson", [ov_bldg])

        fc, stats = merge_sources(osm_path, ob_path, None)

        assert stats.overture_buildings_added == 1
        assert stats.overture_buildings_merged == 0
        assert len(fc["features"]) == 2
        added = [f for f in fc["features"]
                 if (f["properties"].get("overture:primary_source")
                     == "overture_buildings")]
        assert len(added) == 1
        assert added[0]["properties"]["name"] == "Unit 5 Terrace"

    def test_place_point_inside_building_adds_affordance(self, tmp_path):
        osm_poly = {
            "type": "Feature",
            "geometry": _rect_polygon(151.150, -33.820, 151.151, -33.819),
            "properties": {"building": "yes", "name": "building_42"},
        }
        place = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [151.1505, -33.8195]},
            "properties": {
                "names": {"primary": "Sunrise Café"},
                "categories": {"primary": "eat_and_drink.coffee"},
                "confidence": 0.9,
            },
        }
        osm_path = _write_fc(tmp_path, "osm.geojson", [osm_poly])
        pl_path = _write_fc(tmp_path, "overture_places.geojson", [place])

        fc, stats = merge_sources(osm_path, None, pl_path)

        assert stats.places_bound == 1
        assert stats.anonymous_names_replaced == 1
        props = fc["features"][0]["properties"]
        assert props["name"] == "Sunrise Café"  # anonymous host got promoted
        assert props["overture:place:category"] == "eat_and_drink.coffee"
        aff = props["affordances"]
        assert len(aff) == 1
        assert aff[0]["activity_type"] == "eat"
        assert aff[0]["name"] == "Sunrise Café"

    def test_osm_name_not_overwritten_by_overture_place(self, tmp_path):
        osm_poly = {
            "type": "Feature",
            "geometry": _rect_polygon(151.150, -33.820, 151.151, -33.819),
            "properties": {
                "building": "yes",
                "name": "Lane Cove Public Library",
                "amenity": "library",
            },
        }
        place = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [151.1505, -33.8195]},
            "properties": {
                "names": {"primary": "Library Lane Cove"},
                "categories": {"primary": "education.library"},
                "confidence": 0.95,
            },
        }
        osm_path = _write_fc(tmp_path, "osm.geojson", [osm_poly])
        pl_path = _write_fc(tmp_path, "overture_places.geojson", [place])

        fc, stats = merge_sources(osm_path, None, pl_path)

        assert stats.places_bound == 1
        assert stats.anonymous_names_replaced == 0
        props = fc["features"][0]["properties"]
        # OSM name SHALL NOT be overwritten
        assert props["name"] == "Lane Cove Public Library"
        # But affordance IS still added
        assert len(props["affordances"]) == 1

    def test_unhosted_low_confidence_place_is_dropped(self, tmp_path):
        osm_poly = {
            "type": "Feature",
            "geometry": _rect_polygon(151.100, -33.800, 151.101, -33.799),
            "properties": {"building": "yes"},
        }
        # Point far from any polygon
        place = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [151.200, -33.900]},
            "properties": {
                "names": {"primary": "Ghost POI"},
                "categories": {"primary": "shopping.mystery"},
                "confidence": 0.2,
            },
        }
        osm_path = _write_fc(tmp_path, "osm.geojson", [osm_poly])
        pl_path = _write_fc(tmp_path, "overture_places.geojson", [place])

        fc, stats = merge_sources(osm_path, None, pl_path,
                                  place_confidence_floor=0.5)

        assert stats.places_stubbed == 0
        assert stats.places_dropped == 1
        # No new feature added beyond the original OSM polygon
        assert len(fc["features"]) == 1

    def test_unhosted_high_confidence_place_becomes_stub(self, tmp_path):
        osm_poly = {
            "type": "Feature",
            "geometry": _rect_polygon(151.100, -33.800, 151.101, -33.799),
            "properties": {"building": "yes"},
        }
        place = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [151.200, -33.900]},
            "properties": {
                "names": {"primary": "Trusted POI"},
                "categories": {"primary": "eat_and_drink.bakery"},
                "confidence": 0.92,
            },
        }
        osm_path = _write_fc(tmp_path, "osm.geojson", [osm_poly])
        pl_path = _write_fc(tmp_path, "overture_places.geojson", [place])

        fc, stats = merge_sources(osm_path, None, pl_path,
                                  place_confidence_floor=0.5)

        assert stats.places_stubbed == 1
        assert stats.places_dropped == 0
        assert len(fc["features"]) == 2
        stub = fc["features"][-1]
        assert stub["geometry"]["type"] == "Polygon"
        assert stub["properties"]["overture:primary_source"] == "overture_places"
        assert stub["properties"]["name"] == "Trusted POI"
        assert len(stub["properties"]["affordances"]) == 1


class TestImporterReadsEnrichedFields:
    """Importer must consume Overture enrichment fields produced by conflation."""

    def test_affordance_list_in_properties_becomes_building_affordances(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": _rect_polygon(151.150, -33.820, 151.151, -33.819),
                    "properties": {
                        "building": "yes",
                        "name": "Sunrise Café",
                        "amenity": "cafe",
                        "affordances": [
                            {
                                "activity_type": "eat",
                                "source": "overture_places",
                                "category": "eat_and_drink.coffee",
                                "name": "Sunrise Café",
                                "confidence": 0.9,
                                "description": "coffee shop",
                            }
                        ],
                    },
                }
            ],
        }
        region = GeoJSONImporter().import_data(geojson, region_id="t")
        assert len(region.buildings) == 1
        b = list(region.buildings.values())[0]
        assert b.building_type == "cafe"
        assert len(b.affordances) == 1
        assert b.affordances[0].activity_type == "eat"

    def test_overture_class_used_as_fallback_type(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": _rect_polygon(151.150, -33.820, 151.151, -33.819),
                    "properties": {
                        "building": "yes",  # OSM tag present but generic
                        "overture:class": "commercial",
                    },
                }
            ],
        }
        region = GeoJSONImporter().import_data(geojson, region_id="t")
        b = list(region.buildings.values())[0]
        assert b.building_type == "shop"  # Overture commercial → shop

    def test_overture_height_infers_floors(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": _rect_polygon(151.150, -33.820, 151.151, -33.819),
                    "properties": {
                        "building": "yes",
                        "overture:height": 9.2,
                    },
                }
            ],
        }
        region = GeoJSONImporter().import_data(geojson, region_id="t")
        b = list(region.buildings.values())[0]
        # 9.2m / 3m per storey ≈ 3
        assert b.floors == 3


@pytest.mark.skipif(
    not ENRICHED_LANECOVE_GEOJSON.exists(),
    reason="lanecove_enriched.geojson not present — skip enriched connectivity gate",
)
class TestLaneCoveEnrichedConnectivity:
    """Enrichment must not regress connectivity and must hit suburban
    realistic coverage floors."""

    def test_enriched_connectivity_and_coverage(self):
        clip_bounds = {
            "min_lat": -33.835,
            "max_lat": -33.798,
            "min_lon": 151.145,
            "max_lon": 151.178,
        }
        region = GeoJSONImporter().import_file(
            ENRICHED_LANECOVE_GEOJSON,
            bounds=clip_bounds,
            region_id="lane_cove_enriched",
        )
        # 1. Connectivity doesn't regress
        assert _building_main_component_share(region) >= 0.85

        buildings = list(region.buildings.values())
        n = max(1, len(buildings))

        # 2. Semantic coverage: almost every building has SOME affordance
        affordance_covered = sum(1 for b in buildings if len(b.affordances) > 0)
        assert affordance_covered / n >= 0.80, (
            f"Affordance coverage {affordance_covered/n:.1%} < 80% — "
            "residential default may be broken"
        )

        # 3. Residential default applied widely (Lane Cove is a suburb)
        reside_covered = sum(
            1 for b in buildings
            if any(a.activity_type == "reside" for a in b.affordances)
        )
        assert reside_covered / n >= 0.70, (
            f"Reside coverage {reside_covered/n:.1%} < 70%"
        )

        # 4. Real POI density in absolute terms — suburb-realistic floor
        poi_covered = sum(
            1 for b in buildings
            if any(a.activity_type != "reside" for a in b.affordances)
        )
        assert poi_covered >= 700, (
            f"POI-bound buildings {poi_covered} < 700 — enrichment under-performing"
        )


class TestResidentialSemantics:
    """Default 'reside' affordance lets agents enumerate homes."""

    def test_residential_default_reside_affordance(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": _rect_polygon(151.150, -33.820, 151.151, -33.819),
                    "properties": {"building": "house"},  # → residential
                }
            ],
        }
        region = GeoJSONImporter().import_data(geojson, region_id="t")
        b = list(region.buildings.values())[0]
        assert b.building_type == "residential"
        assert len(b.affordances) == 1
        aff = b.affordances[0]
        assert aff.activity_type == "reside"
        assert aff.capacity == 1
        assert "inferred" in aff.description

    def test_apartment_gets_higher_capacity(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": _rect_polygon(151.150, -33.820, 151.151, -33.819),
                    "properties": {
                        "building": "apartments",
                        "building:levels": "5",
                    },
                }
            ],
        }
        region = GeoJSONImporter().import_data(geojson, region_id="t")
        b = list(region.buildings.values())[0]
        reside = [a for a in b.affordances if a.activity_type == "reside"]
        assert len(reside) == 1
        # floors=5, capacity = min(12, 5*4) = 12
        assert reside[0].capacity == 12

    def test_poi_bound_residential_keeps_poi_affordance(self):
        """When a place POI binds to a residential building, the POI affordance
        must survive (we don't clobber real signals with the default)."""
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": _rect_polygon(151.150, -33.820, 151.151, -33.819),
                    "properties": {
                        "building": "apartments",
                        "affordances": [{
                            "activity_type": "eat",
                            "name": "Mixed-Use Café",
                        }],
                    },
                }
            ],
        }
        region = GeoJSONImporter().import_data(geojson, region_id="t")
        b = list(region.buildings.values())[0]
        activity_types = {a.activity_type for a in b.affordances}
        # POI is preserved; default may or may not be added — current impl
        # only adds default when affordances is empty.
        assert "eat" in activity_types

    def test_atlas_list_residential_buildings(self):
        from synthetic_socio_wind_tunnel.atlas.service import Atlas
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": _rect_polygon(151.150, -33.820, 151.151, -33.819),
                    "properties": {"building": "house"},
                },
                {
                    "type": "Feature",
                    "geometry": _rect_polygon(151.160, -33.820, 151.161, -33.819),
                    "properties": {"building": "yes", "amenity": "cafe",
                                    "name": "The Beans"},
                },
            ],
        }
        region = GeoJSONImporter().import_data(geojson, region_id="t")
        atlas = Atlas(region)
        homes = atlas.list_residential_buildings()
        assert len(homes) == 1
        assert homes[0].building_type == "residential"
        # Capacity is readable from the reside affordance
        reside = [a for a in homes[0].affordances if a.activity_type == "reside"]
        assert reside and reside[0].capacity >= 1
