"""
Polygon dedup pass for cartography pipeline.

多源融合（OSM + Overture + 合成 infill）会引入近重复建筑物——同一栋楼被进了
两次。这个模块提供 IoU 判重 + 信息丰富度排序合并的纯函数实现。

设计：见 `openspec/changes/cartography-dedup-buildings/design.md` D2-D4。
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from synthetic_socio_wind_tunnel.core.types import Coord, Polygon

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.atlas.models import Building, Region


# ---------------------------------------------------------------------------
# Polygon utilities — 手写避免 shapely 大依赖（D2）
# ---------------------------------------------------------------------------

_AABB = tuple[float, float, float, float]  # (minX, minY, maxX, maxY)


def _polygon_aabb(p: Polygon) -> _AABB:
    vs = p.vertices
    if not vs:
        return (0.0, 0.0, 0.0, 0.0)
    xs = [v.x for v in vs]
    ys = [v.y for v in vs]
    return (min(xs), min(ys), max(xs), max(ys))


def _aabb_overlap(a: _AABB, b: _AABB) -> bool:
    """两个 AABB 是否相交（含边界接触）。"""
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def _aabb_overlap_area(a: _AABB, b: _AABB) -> float:
    ox = min(a[2], b[2]) - max(a[0], b[0])
    oy = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, ox) * max(0.0, oy)


def _shoelace(vertices: list[tuple[float, float]]) -> float:
    """Signed polygon area（顶点顺时针为负、逆时针为正）。"""
    n = len(vertices)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = vertices[i]
        x2, y2 = vertices[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def _ensure_ccw(vertices: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Sutherland-Hodgman 要求 clipper 逆时针；这里把顺时针的反过来。"""
    if _shoelace(vertices) < 0:
        return list(reversed(vertices))
    return vertices


def _clip_polygon(
    subject: list[tuple[float, float]],
    clipper: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """
    Sutherland-Hodgman polygon clipping.
    Clipper 必须是凸多边形且逆时针；subject 任意。
    返回 subject ∩ clipper 的顶点列表（可能为空）。
    """
    output = list(subject)
    n_clip = len(clipper)
    if n_clip < 3 or len(output) < 3:
        return []

    for i in range(n_clip):
        if not output:
            break
        cp1 = clipper[i]
        cp2 = clipper[(i + 1) % n_clip]
        edge_dx = cp2[0] - cp1[0]
        edge_dy = cp2[1] - cp1[1]

        def _inside(p: tuple[float, float]) -> bool:
            # 逆时针 clipper：内侧为左侧 → cross(edge, p-cp1) >= 0
            return edge_dx * (p[1] - cp1[1]) - edge_dy * (p[0] - cp1[0]) >= 0.0

        def _intersect(
            p1: tuple[float, float], p2: tuple[float, float],
        ) -> tuple[float, float]:
            # edge: cp1 + t*(edge_dx, edge_dy)
            # line: p1 + u*(p2-p1)
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            denom = edge_dx * dy - edge_dy * dx
            if abs(denom) < 1e-12:
                return p1  # parallel; degenerate
            t = ((p1[0] - cp1[0]) * dy - (p1[1] - cp1[1]) * dx) / denom
            return (cp1[0] + t * edge_dx, cp1[1] + t * edge_dy)

        new_output: list[tuple[float, float]] = []
        s = output[-1]
        for e in output:
            if _inside(e):
                if not _inside(s):
                    new_output.append(_intersect(s, e))
                new_output.append(e)
            elif _inside(s):
                new_output.append(_intersect(s, e))
            s = e
        output = new_output

    return output


def polygon_iou(a: Polygon, b: Polygon) -> float:
    """
    两 Polygon 的 IoU（Intersection over Union）。
    凹多边形上是上界估计（Sutherland-Hodgman 假设 clipper 凸）；OSM/Overture
    建筑物 99% 是凸或近凸。
    """
    aabb_a = _polygon_aabb(a)
    aabb_b = _polygon_aabb(b)
    if not _aabb_overlap(aabb_a, aabb_b):
        return 0.0

    verts_a = [(v.x, v.y) for v in a.vertices]
    verts_b = [(v.x, v.y) for v in b.vertices]
    if len(verts_a) < 3 or len(verts_b) < 3:
        return 0.0

    area_a = abs(_shoelace(verts_a))
    area_b = abs(_shoelace(verts_b))
    if area_a < 1e-9 or area_b < 1e-9:
        return 0.0

    # 让 clipper 是 b（逆时针）；subject 是 a
    clipper = _ensure_ccw(verts_b)
    inter = _clip_polygon(verts_a, clipper)
    if len(inter) < 3:
        return 0.0
    area_i = abs(_shoelace(inter))

    union = area_a + area_b - area_i
    if union <= 1e-9:
        return 0.0
    return area_i / union


# ---------------------------------------------------------------------------
# Building merge scoring (D3)
# ---------------------------------------------------------------------------

_GENERIC_NAME_PREFIXES = ("building_", "rv_")


def _has_real_name(b: "Building") -> bool:
    name = (b.name or "").strip()
    if not name:
        return False
    if any(name.startswith(p) for p in _GENERIC_NAME_PREFIXES):
        return False
    return True


def _building_score(b: "Building") -> int:
    """
    信息丰富度评分。高分留下；同分时按 id 字典序保留较小的（确定性）。
    """
    score = 0
    if _has_real_name(b):
        score += 100
    score += len(b.osm_tags or {})
    if (b.osm_tags or {}).get("overture:primary_source"):
        score += 5
    if (b.building_type or "generic") != "generic":
        score += 10
    if (b.description or "").strip():
        score += 5
    score += 2 * len(b.affordances or ())
    return score


def _merge_into(primary: "Building", secondary: "Building") -> "Building":
    """
    把 secondary 的非空 osm_tags / affordances / description 并入 primary。
    返回 primary 的新副本（Building frozen）。
    """
    new_tags = dict(primary.osm_tags or {})
    for k, v in (secondary.osm_tags or {}).items():
        new_tags.setdefault(k, v)

    # 记录合并来源
    merged_ids = new_tags.get("merged_from_ids", "")
    sec_ids = [secondary.id]
    sec_merged = (secondary.osm_tags or {}).get("merged_from_ids", "")
    if sec_merged:
        sec_ids.extend(sec_merged.split(","))
    if merged_ids:
        existing = set(merged_ids.split(","))
        for sid in sec_ids:
            if sid not in existing:
                merged_ids = merged_ids + "," + sid
                existing.add(sid)
    else:
        merged_ids = ",".join(sec_ids)
    new_tags["merged_from_ids"] = merged_ids

    new_affordances = list(primary.affordances or ())
    seen = {id(a) for a in new_affordances}
    seen_keys = {(a.activity_type, a.description) for a in new_affordances}
    for a in (secondary.affordances or ()):
        key = (a.activity_type, a.description)
        if key not in seen_keys:
            new_affordances.append(a)
            seen_keys.add(key)

    new_description = primary.description
    if not new_description.strip() and (secondary.description or "").strip():
        new_description = secondary.description

    return primary.model_copy(update={
        "osm_tags": new_tags,
        "affordances": tuple(new_affordances),
        "description": new_description,
    })


# ---------------------------------------------------------------------------
# Main entry: dedup_buildings
# ---------------------------------------------------------------------------

_GRID_CELL = 50.0  # meters


def dedup_buildings(
    region: "Region", *, iou_threshold: float = 0.5,
) -> "Region":
    """
    把 IoU > threshold 的建筑物对合并为一栋；保留信息丰富的那栋。

    用 50 m grid bucket 空间索引避免 O(n²)；每栋楼只与同 cell 及邻居 cell
    的楼比较。

    返回新 Region；原 Region 不变（Pydantic frozen）。
    """
    buildings = list(region.buildings.values())
    n = len(buildings)
    if n == 0:
        return region

    aabbs = [_polygon_aabb(b.polygon) for b in buildings]

    # Grid bucket 空间索引
    bins: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, ab in enumerate(aabbs):
        cx = int((ab[0] + ab[2]) / 2 // _GRID_CELL)
        cy = int((ab[1] + ab[3]) / 2 // _GRID_CELL)
        # AABB 跨多个 cell 时需 store 在所有覆盖 cell —— 但加邻居遍历后，
        # 中心 cell 已足够（邻居覆盖 ±50 m，单楼 footprint 通常 < 50 m）
        bins[(cx, cy)].append(i)

    # Union-Find 合并组
    parent = list(range(n))

    def _find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def _union(i: int, j: int) -> None:
        ri, rj = _find(i), _find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)

    # 对每对邻居算 IoU
    visited_pairs: set[tuple[int, int]] = set()
    for (cx, cy), idxs in bins.items():
        # 收集本 cell + 8 邻居 cell 的所有 idx
        candidates: list[int] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                candidates.extend(bins.get((cx + dx, cy + dy), ()))
        # 对 cell 内每个 i 与所有 candidate j 比较
        for i in idxs:
            for j in candidates:
                if i >= j:
                    continue
                key = (i, j)
                if key in visited_pairs:
                    continue
                visited_pairs.add(key)
                if not _aabb_overlap(aabbs[i], aabbs[j]):
                    continue
                # AABB 重叠面积粗筛：< 1 m² 不可能 IoU > 0.5
                if _aabb_overlap_area(aabbs[i], aabbs[j]) < 1.0:
                    continue
                iou = polygon_iou(buildings[i].polygon, buildings[j].polygon)
                if iou >= iou_threshold:
                    _union(i, j)

    # 收集合并组
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[_find(i)].append(i)

    new_buildings: dict[str, "Building"] = {}
    n_merged = 0
    for root, members in groups.items():
        if len(members) == 1:
            b = buildings[members[0]]
            new_buildings[b.id] = b
            continue
        # 多成员组：选最高分作 primary；同分按 id 字典序最小
        members_sorted = sorted(
            members,
            key=lambda i: (-_building_score(buildings[i]), buildings[i].id),
        )
        primary = buildings[members_sorted[0]]
        for sec_idx in members_sorted[1:]:
            primary = _merge_into(primary, buildings[sec_idx])
            n_merged += 1
        new_buildings[primary.id] = primary

    if n_merged == 0:
        return region

    # 过滤 connections：丢掉指向已合并掉的 building id
    kept_ids = set(new_buildings.keys()) | set(region.outdoor_areas.keys())
    new_conns = tuple(
        c for c in region.connections
        if c.from_id in kept_ids and c.to_id in kept_ids
    )

    return region.model_copy(update={
        "buildings": new_buildings,
        "connections": new_conns,
    })


__all__ = ["dedup_buildings", "polygon_iou"]
