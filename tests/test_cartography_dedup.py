"""Tests for cartography.dedup — polygon IoU + dedup pass."""

from __future__ import annotations

from synthetic_socio_wind_tunnel.atlas.models import (
    ActivityAffordance, Building, Material, Region,
)
from synthetic_socio_wind_tunnel.cartography.dedup import (
    dedup_buildings, polygon_iou,
)
from synthetic_socio_wind_tunnel.core.types import Coord, Polygon


def _square(cx: float, cy: float, half: float = 5.0) -> Polygon:
    return Polygon(vertices=tuple(
        Coord(x=cx + dx, y=cy + dy)
        for dx, dy in [(-half, -half), (half, -half), (half, half), (-half, half)]
    ))


def _make_building(
    bid: str, *, cx: float = 0, cy: float = 0, half: float = 5.0,
    name: str | None = None, building_type: str = "generic",
    osm_tags: dict[str, str] | None = None,
    description: str = "",
    affordances: tuple = (),
) -> Building:
    return Building(
        id=bid,
        name=name or bid,
        polygon=_square(cx, cy, half),
        building_type=building_type,
        osm_tags=osm_tags or {},
        description=description,
        floors=1,
        exterior_material=Material.BRICK,
        affordances=affordances,
    )


class TestPolygonIoU:

    def test_identical(self):
        a = _square(0, 0)
        assert polygon_iou(a, a) > 0.999

    def test_disjoint_aabb(self):
        a = _square(0, 0)
        b = _square(100, 100)
        assert polygon_iou(a, b) == 0.0

    def test_half_overlap(self):
        # 10x10 vs same shifted by 5 on x → intersection 50, union 150, IoU=1/3
        a = _square(0, 0, half=5)
        b = _square(5, 0, half=5)
        iou = polygon_iou(a, b)
        assert 0.32 < iou < 0.34

    def test_cw_vs_ccw_orientation(self):
        # OSM/Overture polygons may come in either winding order
        ccw = Polygon(vertices=tuple(Coord(x=x, y=y) for x, y in
                                     [(0, 0), (10, 0), (10, 10), (0, 10)]))
        cw = Polygon(vertices=tuple(Coord(x=x, y=y) for x, y in
                                    [(0, 0), (0, 10), (10, 10), (10, 0)]))
        assert polygon_iou(ccw, cw) > 0.999

    def test_aabb_overlap_but_polygon_disjoint(self):
        # Two L shapes whose AABBs overlap but actual polygons don't share area
        # 简化：两个小方块各自占 AABB 的一角
        a = Polygon(vertices=(Coord(x=0, y=0), Coord(x=2, y=0),
                              Coord(x=2, y=2), Coord(x=0, y=2)))
        b = Polygon(vertices=(Coord(x=8, y=8), Coord(x=10, y=8),
                              Coord(x=10, y=10), Coord(x=8, y=10)))
        assert polygon_iou(a, b) == 0.0


class TestDedupBuildings:

    def _make_region(self, buildings: list[Building]) -> Region:
        return Region(
            id="test",
            name="test",
            bounds_min=Coord(x=-100, y=-100),
            bounds_max=Coord(x=100, y=100),
            buildings={b.id: b for b in buildings},
            outdoor_areas={},
            connections=(),
            doors={},
            borders={},
        )

    def test_dedup_keeps_richer(self):
        # Two buildings 95% overlapping; one named with rich tags, other generic
        rich = _make_building(
            "lane_cove_hub", cx=0, cy=0, half=5,
            name="Lane Cove Community Hub",
            building_type="community_centre",
            osm_tags={"building": "yes", "name": "Lane Cove Community Hub", "amenity": "community_centre"},
            description="Community hub",
        )
        generic = _make_building(
            "building_999", cx=0.2, cy=0.1, half=5,  # tiny offset → IoU > 0.9
            name="building_999",
            osm_tags={"building": "yes"},
        )
        region = self._make_region([rich, generic])
        out = dedup_buildings(region)
        assert "lane_cove_hub" in out.buildings
        assert "building_999" not in out.buildings
        # generic 的 tag 被合并到 primary（这里 generic 的 tag 是 rich 的子集）
        assert "merged_from_ids" in out.buildings["lane_cove_hub"].osm_tags
        assert "building_999" in out.buildings["lane_cove_hub"].osm_tags["merged_from_ids"]

    def test_dedup_skips_terrace(self):
        # 共墙排屋：edge-touching, IoU < 0.05
        a = _make_building("a", cx=0, cy=0, half=5)
        b = _make_building("b", cx=10, cy=0, half=5)  # 紧邻、共边但无 area 重叠
        region = self._make_region([a, b])
        out = dedup_buildings(region)
        assert len(out.buildings) == 2

    def test_dedup_disjoint_unaffected(self):
        a = _make_building("a", cx=0, cy=0, half=5)
        b = _make_building("b", cx=100, cy=100, half=5)
        region = self._make_region([a, b])
        out = dedup_buildings(region)
        assert len(out.buildings) == 2

    def test_dedup_merges_tags(self):
        # Two near-identical, each with unique non-overlapping tags.
        # Production-realistic IDs: real name vs generic building_NNNN
        a = _make_building(
            "real_place", cx=0, cy=0, half=5,
            name="Real Place",
            osm_tags={"building": "yes", "addr:street": "Main St"},
        )
        b = _make_building(
            "building_42", cx=0.1, cy=0, half=5,  # generic-style id, no real name
            osm_tags={"overture:height": "12", "overture:primary_source": "overture_buildings"},
        )
        region = self._make_region([a, b])
        out = dedup_buildings(region)
        assert len(out.buildings) == 1
        kept = next(iter(out.buildings.values()))
        assert kept.id == "real_place"  # named wins
        # b 的 overture tags 被并入
        assert kept.osm_tags.get("overture:height") == "12"
        assert kept.osm_tags.get("addr:street") == "Main St"

    def test_dedup_records_merged_from(self):
        a = _make_building(
            "a", cx=0, cy=0, half=5,
            name="Real Place",
            osm_tags={"building": "yes", "name": "Real Place"},
        )
        b = _make_building("building_b", cx=0.1, cy=0, half=5)  # generic
        c = _make_building("building_c", cx=0.05, cy=0.05, half=5)  # also overlaps
        region = self._make_region([a, b, c])
        out = dedup_buildings(region)
        assert len(out.buildings) == 1
        kept = next(iter(out.buildings.values()))
        merged_ids = kept.osm_tags["merged_from_ids"].split(",")
        assert "building_b" in merged_ids
        assert "building_c" in merged_ids

    def test_dedup_three_way_overlap(self):
        # Three buildings all overlapping each other → collapse to 1
        a = _make_building("hub", cx=0, cy=0, half=5, name="Hub", osm_tags={"name": "Hub"})
        b = _make_building("building_b", cx=0.5, cy=0.5, half=5)
        c = _make_building("building_c", cx=-0.5, cy=-0.5, half=5)
        region = self._make_region([a, b, c])
        out = dedup_buildings(region)
        assert len(out.buildings) == 1
        assert "hub" in out.buildings

    def test_dedup_drops_dangling_connections(self):
        from synthetic_socio_wind_tunnel.atlas.models import Connection
        a = _make_building("hub_a", cx=0, cy=0, half=5, name="Hub", osm_tags={"name": "Hub"})
        b = _make_building("building_b", cx=0.1, cy=0, half=5)  # will be merged into a
        # connection a→b should be dropped after merge
        region = Region(
            id="test", name="test",
            bounds_min=Coord(x=-100, y=-100), bounds_max=Coord(x=100, y=100),
            buildings={"hub_a": a, "building_b": b},
            outdoor_areas={},
            connections=(Connection(from_id="hub_a", to_id="building_b", distance=1.0),),
            doors={}, borders={},
        )
        out = dedup_buildings(region)
        assert len(out.buildings) == 1
        assert len(out.connections) == 0  # dangling conn dropped
