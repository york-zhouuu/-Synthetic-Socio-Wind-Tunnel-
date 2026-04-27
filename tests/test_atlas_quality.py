"""
Geometric quality invariants for the live Lane Cove atlas cache.

These regression tests load `data/lanecove_atlas.json` (cache produced by
cartography pipeline) and assert dedup invariants. Skipped if cache absent
(CI-friendly).

Reference: `cartography-dedup-buildings` change spec.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

from synthetic_socio_wind_tunnel.cartography.dedup import (
    _clip_polygon, _ensure_ccw, _shoelace, polygon_iou,
)
from synthetic_socio_wind_tunnel.core.types import Coord, Polygon


_CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "lanecove_atlas.json"
_GRID_CELL = 50.0


@pytest.fixture(scope="module")
def atlas_buildings():
    if not _CACHE_PATH.exists():
        pytest.skip(f"atlas cache not found at {_CACHE_PATH}")
    data = json.loads(_CACHE_PATH.read_text())
    return list(data["buildings"].values())


def _aabb(b):
    vs = b["polygon"]["vertices"]
    return (
        min(v["x"] for v in vs), min(v["y"] for v in vs),
        max(v["x"] for v in vs), max(v["y"] for v in vs),
    )


def _aabb_overlap(a, b):
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def _aabb_overlap_area(a, b):
    ox = min(a[2], b[2]) - max(a[0], b[0])
    oy = min(a[3], b[3]) - max(a[1], b[1])
    return max(0, ox) * max(0, oy)


def _to_polygon(b) -> Polygon:
    return Polygon(vertices=tuple(
        Coord(x=v["x"], y=v["y"]) for v in b["polygon"]["vertices"]
    ))


def _iter_neighbor_pairs(buildings):
    aabbs = [_aabb(b) for b in buildings]
    bins: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, ab in enumerate(aabbs):
        cx = int((ab[0] + ab[2]) / 2 // _GRID_CELL)
        cy = int((ab[1] + ab[3]) / 2 // _GRID_CELL)
        bins[(cx, cy)].append(i)

    seen: set[tuple[int, int]] = set()
    for (cx, cy), idxs in bins.items():
        candidates: list[int] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                candidates.extend(bins.get((cx + dx, cy + dy), ()))
        for i in idxs:
            for j in candidates:
                if i >= j:
                    continue
                key = (i, j)
                if key in seen:
                    continue
                seen.add(key)
                yield i, j, aabbs[i], aabbs[j]


def test_no_iou_duplicates(atlas_buildings):
    """IoU > 0.5 重复对必须 == 0（dedup pass 的硬保证）。"""
    duplicates: list[tuple[str, str, float]] = []
    for i, j, ai, aj in _iter_neighbor_pairs(atlas_buildings):
        if not _aabb_overlap(ai, aj):
            continue
        # Cheap pre-filter
        if _aabb_overlap_area(ai, aj) < 1.0:
            continue
        iou = polygon_iou(_to_polygon(atlas_buildings[i]),
                          _to_polygon(atlas_buildings[j]))
        if iou >= 0.5:
            duplicates.append((
                atlas_buildings[i]["id"], atlas_buildings[j]["id"], iou,
            ))
    assert duplicates == [], (
        f"found {len(duplicates)} IoU>0.5 duplicate pairs; "
        f"first 5: {duplicates[:5]}"
    )


def _polygon_intersection_area(a: Polygon, b: Polygon) -> float:
    verts_a = [(v.x, v.y) for v in a.vertices]
    verts_b = [(v.x, v.y) for v in b.vertices]
    if len(verts_a) < 3 or len(verts_b) < 3:
        return 0.0
    clipper = _ensure_ccw(verts_b)
    inter = _clip_polygon(verts_a, clipper)
    if len(inter) < 3:
        return 0.0
    return abs(_shoelace(inter))


def test_significant_overlaps_under_threshold(atlas_buildings):
    """
    真实多边形重叠（polygon intersection 面积 > 30 m²）pair 数 SHALL < 50。

    NOTE: 用 polygon intersection 而非 AABB overlap——OSM 的复杂 footprint
    会让 AABB 重叠产生大量 false positive（多边形对角排列、L 形相邻店面等）。
    Baseline 数值 ~150 实测 polygon overlap pairs；dedup 后 IoU>0.5 已 0，
    剩下 IoU 0-0.5 的部分重叠属真实建筑数据噪声。
    """
    significant_pairs = 0
    for i, j, ai, aj in _iter_neighbor_pairs(atlas_buildings):
        if not _aabb_overlap(ai, aj):
            continue
        if _aabb_overlap_area(ai, aj) < 1.0:
            continue
        inter_area = _polygon_intersection_area(
            _to_polygon(atlas_buildings[i]), _to_polygon(atlas_buildings[j])
        )
        if inter_area > 30.0:
            significant_pairs += 1
    assert significant_pairs < 50, (
        f"got {significant_pairs} pairs with polygon intersection > 30 m² "
        f"(threshold 50); cartography dedup may have regressed"
    )


def test_building_count_in_expected_range(atlas_buildings):
    """Dedup 后建筑数应在合理范围；偏离则 dedup 调得太狠或太松。"""
    n = len(atlas_buildings)
    assert 5000 <= n <= 7600, (
        f"building count {n} outside expected [5000, 7600]; "
        f"check dedup IoU threshold"
    )


# ---------------------------------------------------------------------------
# Water geometry invariants (cartography-fix-water-geometry change)
# ---------------------------------------------------------------------------

_OSM_PATH = Path(__file__).resolve().parents[1] / "data" / "lanecove_osm.geojson"


def _polygon_area_m2(coords: list, center_lat: float = -33.81) -> float:
    """Approximate planar area of a lon/lat polygon in m² (small-scale OK)."""
    if len(coords) < 4:
        return 0.0
    import math
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(center_lat))
    n = len(coords)
    s = 0.0
    for i in range(n - 1):
        x1, y1 = coords[i]
        x2, y2 = coords[i + 1]
        s += (x1 * m_per_deg_lon) * (y2 * m_per_deg_lat) \
           - (x2 * m_per_deg_lon) * (y1 * m_per_deg_lat)
    return abs(s) / 2.0


@pytest.fixture(scope="module")
def osm_geojson():
    if not _OSM_PATH.exists():
        pytest.skip(f"OSM geojson not found at {_OSM_PATH}")
    return json.loads(_OSM_PATH.read_text())


def test_lane_cove_river_assembled(osm_geojson):
    """
    multipolygon ring assembly 必须装出 Lane Cove River 大水域。
    Reference: cartography-fix-water-geometry spec scenario.
    """
    matches = [
        f for f in osm_geojson["features"]
        if f["geometry"]["type"] == "Polygon"
        and f["properties"].get("name") == "Lane Cove River"
    ]
    assert matches, "Lane Cove River polygon not found in OSM GeoJSON"
    biggest = max(matches, key=lambda f:
                  _polygon_area_m2(f["geometry"]["coordinates"][0]))
    area = _polygon_area_m2(biggest["geometry"]["coordinates"][0])
    assert area > 50000, f"Lane Cove River footprint only {area:.0f} m² (< 50000)"


def test_assembled_water_polygon_count(osm_geojson):
    """至少 5 个 multipolygon-assembled 水域（Lane Cove R, Sydney Harbour, ...）。"""
    assembled = [
        f for f in osm_geojson["features"]
        if f["geometry"]["type"] == "Polygon"
        and f["properties"].get("@assembled_from", "").startswith("relation/")
    ]
    assert len(assembled) >= 5, (
        f"only {len(assembled)} assembled water polygons; expected ≥ 5 "
        f"(Lane Cove R, Sydney Harbour, Parramatta R, Tarban Creek, ...)"
    )
