"""Build a print-quality static SVG thumbnail of Lane Cove for the A1 poster.

Renders real atlas geometry (building polygons + outdoor areas + streets) plus
an optional dwell-density heatmap aggregated from one or more position-trace
JSON files. Designed for the poster's "Map & Visualisation" card — no
interactivity, just a clean vector image that survives A1 printing.

Usage:
    python3 tools/build_atlas_thumbnail.py \
        --atlas data/lanecove_atlas.json \
        --positions "data/experiments/.../variant_baseline/seed_*_positions.json" \
        --out docs/poster_atlas_thumbnail.svg \
        --stats-out docs/poster_baseline_stats.json
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


# Brand colors mirror the poster palette
COLOR_BG = "#FCFAF6"
COLOR_INK = "#1B1F2A"
COLOR_PINK = "#FF4D8F"
COLOR_PINK_SOFT = "#FFD5E3"
COLOR_YELLOW = "#FFD23F"
COLOR_YELLOW_SOFT = "#FFF2B8"

# 2.5D axonometric constants (30° projection — SimCity-style)
ISO_COS = math.cos(math.radians(30))
ISO_SIN = math.sin(math.radians(30))

# Per-building-type height in meters (extrusion in 2.5D mode)
BUILDING_HEIGHT_M = {
    "residential": 12,
    "apartment": 30,
    "house": 7,
    "shop": 8,
    "supermarket": 10,
    "cafe": 7,
    "restaurant": 8,
    "office": 25,
    "school": 12,
    "hospital": 18,
    "playground": 0,
    "park": 0,
    "community": 12,
    "worship": 15,
    "entertainment": 12,
    "commercial": 10,
    "hotel": 22,
    "bar": 8,
}
BUILDING_HEIGHT_DEFAULT = 9


def _darken_hex(hex_color: str, factor: float) -> str:
    h = hex_color.lstrip("#")
    r = int(int(h[0:2], 16) * factor)
    g = int(int(h[2:4], 16) * factor)
    b = int(int(h[4:6], 16) * factor)
    r = max(0, min(255, r))
    g = max(0, min(255, g))
    b = max(0, min(255, b))
    return f"#{r:02X}{g:02X}{b:02X}"

# Building-type → fill color (mirrors map_explorer convention)
BUILDING_FILL = {
    "residential": "#F5C7D6",
    "apartment": "#F5C7D6",
    "house": "#F5C7D6",
    "cafe": "#FFD23F",
    "restaurant": "#FFD23F",
    "shop": "#FFE08C",
    "supermarket": "#FFE08C",
    "office": "#D8C0B0",
    "school": "#A8D5BA",
    "hospital": "#C9D6FF",
    "playground": "#B5E0B5",
    "park": "#9FD89F",
    "community": "#C8A6E0",
}
BUILDING_DEFAULT = "#E8E2D8"
OUTDOOR_FILL = {
    "park": "#C0E0BA",
    "playground": "#D5EBC8",
}
STREET_STROKE = "#9E988C"


def _centroid(vertices: list[dict[str, float]]) -> tuple[float, float] | None:
    if not vertices:
        return None
    cx = sum(v["x"] for v in vertices) / len(vertices)
    cy = sum(v["y"] for v in vertices) / len(vertices)
    return cx, cy


def _within_radius(cx: float, cy: float, center: tuple[float, float], radius: float) -> bool:
    dx = cx - center[0]
    dy = cy - center[1]
    return dx * dx + dy * dy <= radius * radius


def _polygon_to_svg_path(vertices: list[dict[str, float]],
                        proj: callable) -> str:
    """Convert atlas vertices to SVG `d` attribute, in projected SVG coords."""
    pts = [proj(v["x"], v["y"]) for v in vertices]
    if not pts:
        return ""
    d = f"M {pts[0][0]:.2f} {pts[0][1]:.2f}"
    for x, y in pts[1:]:
        d += f" L {x:.2f} {y:.2f}"
    d += " Z"
    return d


def _color_for_building(b: dict[str, Any]) -> str:
    t = (b.get("building_type") or "").lower()
    return BUILDING_FILL.get(t, BUILDING_DEFAULT)


def _color_for_outdoor(o: dict[str, Any]) -> tuple[str, bool]:
    """Returns (fill, is_street)."""
    t = (o.get("area_type") or "").lower()
    if t in OUTDOOR_FILL:
        return OUTDOOR_FILL[t], False
    return "none", True  # streets / roads: no fill, just stroke


def build_thumbnail(
    atlas_path: Path,
    position_globs: list[str],
    out_svg: Path,
    stats_out: Path | None,
    radius_m: float,
    center_xy: tuple[float, float] | None,
    svg_size_mm: tuple[float, float] = (160.0, 110.0),
    annotate: bool = False,
    variant_overlay: str = "baseline",
    title_text: str = "",
    style: str = "2d",
    height_exaggeration: float = 1.6,
) -> None:
    print(f"[thumbnail] loading atlas: {atlas_path}", file=sys.stderr)
    with atlas_path.open(encoding="utf-8") as fh:
        atlas = json.load(fh)

    buildings: dict = atlas.get("buildings", {})
    outdoors: dict = atlas.get("outdoor_areas", {})

    # Pick center: explicit > Hub > geometric mean of all buildings
    if center_xy is None:
        hub = buildings.get("lane_cove_community_hub")
        if hub:
            c = _centroid(hub["polygon"]["vertices"])
            if c:
                center_xy = c
        if center_xy is None:
            all_cx, all_cy, n = 0.0, 0.0, 0
            for b in buildings.values():
                c = _centroid(b.get("polygon", {}).get("vertices", []))
                if c:
                    all_cx += c[0]
                    all_cy += c[1]
                    n += 1
            center_xy = (all_cx / n, all_cy / n) if n else (0.0, 0.0)
    print(f"[thumbnail] center=({center_xy[0]:.0f}, {center_xy[1]:.0f}), "
          f"radius={radius_m}m", file=sys.stderr)

    # Build location_id → centroid lookup (for position-trace heatmap)
    loc_centroids: dict[str, tuple[float, float]] = {}
    loc_type: dict[str, str] = {}
    for k, b in buildings.items():
        c = _centroid(b.get("polygon", {}).get("vertices", []))
        if c:
            loc_centroids[k] = c
            loc_type[k] = (b.get("building_type") or "unknown").lower()
    for k, o in outdoors.items():
        c = _centroid(o.get("polygon", {}).get("vertices", []))
        if c:
            loc_centroids[k] = c
            loc_type[k] = (o.get("area_type") or "outdoor").lower()

    # Filter geometry within radius
    bldg_in: list[tuple[str, dict]] = []
    for k, b in buildings.items():
        c = _centroid(b.get("polygon", {}).get("vertices", []))
        if c and _within_radius(c[0], c[1], center_xy, radius_m):
            bldg_in.append((k, b))
    out_in: list[tuple[str, dict]] = []
    for k, o in outdoors.items():
        c = _centroid(o.get("polygon", {}).get("vertices", []))
        if c and _within_radius(c[0], c[1], center_xy, radius_m + 200):
            out_in.append((k, o))
    print(f"[thumbnail] {len(bldg_in)} buildings + {len(out_in)} outdoors in radius",
          file=sys.stderr)

    # SVG projection: atlas meters → SVG mm (center at SVG center)
    svg_w_mm, svg_h_mm = svg_size_mm
    pad = 2.0
    if style == "2.5d":
        # Iso 30°: visible diagonal length is (2*radius) * (ISO_COS + ISO_SIN),
        # plus we need vertical room for building height extrusion.
        iso_diag_w = 2 * radius_m * ISO_COS * 2  # widest visible extent
        iso_diag_h = 2 * radius_m * ISO_SIN * 2 + 60 * height_exaggeration  # +headroom for tallest building
        scale = min((svg_w_mm - 2 * pad) / iso_diag_w,
                    (svg_h_mm - 2 * pad) / iso_diag_h)
    else:
        scale = min((svg_w_mm - 2 * pad) / (2 * radius_m),
                    (svg_h_mm - 2 * pad) / (2 * radius_m))
    cx_atlas, cy_atlas = center_xy

    def proj(x: float, y: float) -> tuple[float, float]:
        # SVG y grows downward; atlas y grows northward → flip
        sx = svg_w_mm / 2 + (x - cx_atlas) * scale
        sy = svg_h_mm / 2 - (y - cy_atlas) * scale
        return sx, sy

    def proj_iso(x: float, y: float, z: float = 0.0) -> tuple[float, float]:
        """Iso 30° projection. z = height in meters (extrusion)."""
        dx = x - cx_atlas
        dy = y - cy_atlas
        # Standard axonometric: top-down rotated 45° + flattened by sin(30°)
        sx = svg_w_mm / 2 + (dx - dy) * ISO_COS * scale
        sy = svg_h_mm / 2 + (dx + dy) * ISO_SIN * scale * (-1)  # flip Y
        # Lift by height (negative because SVG y is downward and we want UP)
        sy -= z * scale * height_exaggeration
        return sx, sy

    def proj_active(x: float, y: float, z: float = 0.0) -> tuple[float, float]:
        if style == "2.5d":
            return proj_iso(x, y, z)
        else:
            return proj(x, y)

    # Dwell heatmap: 20m × 20m grid over 1000m radius bbox
    GRID_M = 25.0
    grid_n = int(math.ceil(2 * radius_m / GRID_M))
    grid: dict[tuple[int, int], int] = defaultdict(int)
    # Stats accumulators
    n_seeds = 0
    total_changes = 0
    dwell_by_type: Counter = Counter()
    per_seed_changes: list[int] = []

    pos_files: list[Path] = []
    for g in position_globs:
        pos_files.extend(Path(p) for p in glob.glob(g))
    pos_files = sorted(set(pos_files))
    print(f"[thumbnail] processing {len(pos_files)} position files",
          file=sys.stderr)

    for pf in pos_files:
        try:
            with pf.open(encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception as e:
            print(f"[thumbnail] skip {pf}: {e}", file=sys.stderr)
            continue
        changes = d.get("changes") or []
        n_seeds += 1
        per_seed_changes.append(len(changes))
        for ch in changes:
            loc = ch.get("location_id")
            if not loc:
                continue
            c = loc_centroids.get(loc)
            if not c:
                continue
            total_changes += 1
            # dwell-by-type
            dwell_by_type[loc_type.get(loc, "unknown")] += 1
            # grid cell
            gx = int(round((c[0] - cx_atlas + radius_m) / GRID_M))
            gy = int(round((c[1] - cy_atlas + radius_m) / GRID_M))
            if 0 <= gx < grid_n and 0 <= gy < grid_n:
                grid[(gx, gy)] += 1

    grid_peak = max(grid.values()) if grid else 1
    print(f"[thumbnail] grid: {len(grid)} non-empty cells, peak={grid_peak}",
          file=sys.stderr)

    # ----- Render SVG -----
    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{svg_w_mm}mm" height="{svg_h_mm}mm" '
        f'viewBox="0 0 {svg_w_mm} {svg_h_mm}" '
        f'preserveAspectRatio="xMidYMid meet">'
    )
    # Defs (arrowhead marker for gd variant)
    parts.append(
        '<defs>'
        '<marker id="arrowhead" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerUnits="strokeWidth" markerWidth="6" markerHeight="6" orient="auto">'
        f'<path d="M0,0 L10,5 L0,10 z" fill="{COLOR_INK}"/>'
        '</marker>'
        '</defs>'
    )
    # background
    parts.append(
        f'<rect width="100%" height="100%" fill="{COLOR_BG}"/>'
    )
    # 1000m radius ring — in 2.5D, project as ellipse (squished by sin(30°))
    cx_svg, cy_svg = svg_w_mm / 2, svg_h_mm / 2
    if style == "2.5d":
        rx = radius_m * scale * ISO_COS * math.sqrt(2)
        ry = radius_m * scale * ISO_SIN * math.sqrt(2)
        parts.append(
            f'<ellipse cx="{cx_svg:.2f}" cy="{cy_svg:.2f}" '
            f'rx="{rx:.2f}" ry="{ry:.2f}" fill="{COLOR_PINK}" '
            f'fill-opacity="0.04" stroke="{COLOR_PINK}" '
            f'stroke-width="0.4" stroke-dasharray="1.5 1.2"/>'
        )
    else:
        parts.append(
            f'<circle cx="{cx_svg:.2f}" cy="{cy_svg:.2f}" '
            f'r="{radius_m * scale:.2f}" fill="{COLOR_PINK}" '
            f'fill-opacity="0.04" stroke="{COLOR_PINK}" '
            f'stroke-width="0.4" stroke-dasharray="1.5 1.2"/>'
        )

    # Outdoor areas (parks / playgrounds): filled; streets: stroke only
    # In 2.5D, outdoor areas are still flat (z=0) but use iso projection.
    parts.append('<g id="outdoors">')
    for _, o in out_in:
        verts = o.get("polygon", {}).get("vertices", [])
        if len(verts) < 3:
            continue
        fill, is_street = _color_for_outdoor(o)
        path = _polygon_to_svg_path(verts, lambda x, y: proj_active(x, y, 0))
        if is_street:
            parts.append(
                f'<path d="{path}" fill="none" stroke="{STREET_STROKE}" '
                f'stroke-width="0.15" stroke-opacity="0.55"/>'
            )
        else:
            parts.append(
                f'<path d="{path}" fill="{fill}" stroke="none" '
                f'fill-opacity="0.85"/>'
            )
    parts.append("</g>")

    # Buildings: in 2.5D mode, render as extruded blocks (side walls + roof);
    # in 2D mode, flat polygons. 2.5D mode sorts back-to-front by (x+y).
    parts.append('<g id="buildings">')

    if style == "2.5d":
        # depth sort: paint back-most (smaller x+y) first so front buildings overlay
        def _depth(item):
            verts = item[1].get("polygon", {}).get("vertices", [])
            if not verts:
                return 0
            return sum(v["x"] + v["y"] for v in verts) / len(verts)
        bldg_sorted = sorted(bldg_in, key=_depth)

        for _, b in bldg_sorted:
            verts = b.get("polygon", {}).get("vertices", [])
            if len(verts) < 3:
                continue
            bt = (b.get("building_type") or "").lower()
            h_m = BUILDING_HEIGHT_M.get(bt, BUILDING_HEIGHT_DEFAULT)
            if h_m <= 0:
                # flat (park-like): one polygon at z=0
                fill = _color_for_building(b)
                path = _polygon_to_svg_path(verts, lambda x, y: proj_active(x, y, 0))
                parts.append(
                    f'<path d="{path}" fill="{fill}" stroke="{COLOR_INK}" '
                    f'stroke-width="0.04" fill-opacity="0.85"/>'
                )
                continue
            roof_fill = _color_for_building(b)
            side_fill = _darken_hex(roof_fill, 0.72)
            shadow_fill = _darken_hex(roof_fill, 0.55)
            # Compute roof points (top of extrusion)
            roof_pts = [proj_active(v["x"], v["y"], h_m) for v in verts]
            base_pts = [proj_active(v["x"], v["y"], 0) for v in verts]
            # Side faces: for each edge, draw a quad. To get correct visible-
            # vs-hidden, use signed area of projected quad — positive = back face.
            n = len(verts)
            for i in range(n):
                bx0, by0 = base_pts[i]
                bx1, by1 = base_pts[(i + 1) % n]
                tx1, ty1 = roof_pts[(i + 1) % n]
                tx0, ty0 = roof_pts[i]
                # Signed area of projected quad in SVG (y-down): negative = facing camera
                sa = ((bx1 - bx0) * (ty1 - by1) - (by1 - by0) * (tx1 - bx1))
                if sa >= 0:
                    continue  # hidden side
                # Pick darker color for "left" side (negative dx) vs "right"
                edge_dx = bx1 - bx0
                fill_color = shadow_fill if edge_dx < 0 else side_fill
                d = (
                    f'M {bx0:.2f} {by0:.2f} '
                    f'L {bx1:.2f} {by1:.2f} '
                    f'L {tx1:.2f} {ty1:.2f} '
                    f'L {tx0:.2f} {ty0:.2f} Z'
                )
                parts.append(
                    f'<path d="{d}" fill="{fill_color}" stroke="{COLOR_INK}" '
                    f'stroke-width="0.04"/>'
                )
            # Roof on top
            roof_d = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in roof_pts) + " Z"
            parts.append(
                f'<path d="{roof_d}" fill="{roof_fill}" stroke="{COLOR_INK}" '
                f'stroke-width="0.06"/>'
            )
    else:
        # 2D mode (original)
        for _, b in bldg_in:
            verts = b.get("polygon", {}).get("vertices", [])
            if len(verts) < 3:
                continue
            fill = _color_for_building(b)
            path = _polygon_to_svg_path(verts, proj)
            parts.append(
                f'<path d="{path}" fill="{fill}" stroke="{COLOR_INK}" '
                f'stroke-width="0.04" fill-opacity="0.9"/>'
            )
    parts.append("</g>")

    # Dwell heatmap layer (style varies by variant_overlay)
    # Variant overlay style: baseline = full pink heatmap; hp = same but with anchor
    # pins added below; gd = faded heatmap + arrows (drawn below); pf = lighter heatmap.
    heat_alpha_scale = {
        "baseline": 1.0,
        "hp": 1.0,
        "gd": 0.45,  # attention away from local
        "pf": 0.55,  # less manic phone-driven motion
    }.get(variant_overlay, 1.0)

    if grid:
        parts.append('<g id="heatmap" style="mix-blend-mode: multiply;">')
        cell_w_mm = GRID_M * scale
        for (gx, gy), v in grid.items():
            ax = cx_atlas - radius_m + gx * GRID_M
            ay = cy_atlas - radius_m + gy * GRID_M
            t = math.log(v + 1) / math.log(grid_peak + 1)
            alpha = max(0.0, min(0.55, 0.10 + 0.45 * t)) * heat_alpha_scale
            if style == "2.5d":
                # Render as iso parallelogram lying flat on ground (z=0)
                hg = GRID_M / 2
                corners = [
                    proj_iso(ax - hg, ay - hg, 0),
                    proj_iso(ax + hg, ay - hg, 0),
                    proj_iso(ax + hg, ay + hg, 0),
                    proj_iso(ax - hg, ay + hg, 0),
                ]
                d = "M " + " L ".join(f"{p[0]:.2f} {p[1]:.2f}" for p in corners) + " Z"
                parts.append(
                    f'<path d="{d}" fill="{COLOR_PINK}" '
                    f'fill-opacity="{alpha:.3f}"/>'
                )
            else:
                sx, sy = proj(ax, ay)
                sx -= cell_w_mm / 2
                sy -= cell_w_mm / 2
                parts.append(
                    f'<rect x="{sx:.2f}" y="{sy:.2f}" '
                    f'width="{cell_w_mm:.2f}" height="{cell_w_mm:.2f}" '
                    f'fill="{COLOR_PINK}" fill-opacity="{alpha:.3f}"/>'
                )
        parts.append("</g>")

    # Variant-specific overlay annotations
    if variant_overlay == "hp":
        anchors = [
            ("Plaza", cx_atlas, cy_atlas),
            ("Council", 386, -644),
            ("Swim Club", 400, -558),
            ("BP shop", -255, -842),
            ("Plumber Lane", 211, -227),
        ]
        for name, ax, ay in anchors:
            # Use lifted height for visibility above buildings in iso
            sx, sy = proj_active(ax, ay, 35)
            # Reach ring on ground (z=0) — ellipse in 2.5D
            sx_ground, sy_ground = proj_active(ax, ay, 0)
            if style == "2.5d":
                rrx = 200 * scale * ISO_COS * math.sqrt(2)
                rry = 200 * scale * ISO_SIN * math.sqrt(2)
                parts.append(
                    f'<ellipse cx="{sx_ground:.2f}" cy="{sy_ground:.2f}" '
                    f'rx="{rrx:.2f}" ry="{rry:.2f}" fill="{COLOR_PINK}" '
                    f'fill-opacity="0.15" stroke="{COLOR_PINK}" '
                    f'stroke-width="0.25" stroke-dasharray="1 1"/>'
                )
            else:
                parts.append(
                    f'<circle cx="{sx_ground:.2f}" cy="{sy_ground:.2f}" '
                    f'r="{200 * scale:.2f}" fill="{COLOR_PINK}" '
                    f'fill-opacity="0.10" stroke="{COLOR_PINK}" '
                    f'stroke-width="0.2" stroke-dasharray="1 1"/>'
                )
            # Anchor pin (a vertical line + dot at top in 2.5D)
            if style == "2.5d":
                parts.append(
                    f'<line x1="{sx_ground:.2f}" y1="{sy_ground:.2f}" '
                    f'x2="{sx:.2f}" y2="{sy:.2f}" '
                    f'stroke="{COLOR_INK}" stroke-width="0.25"/>'
                )
            parts.append(
                f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="1.4" '
                f'fill="{COLOR_PINK}" stroke="{COLOR_INK}" stroke-width="0.3"/>'
            )
    elif variant_overlay == "gd":
        # Arrows pointing OFF the map — attention pulled to global news
        # Place 4 arrows at compass points pointing outward
        edge = svg_w_mm * 0.46
        arrows = [
            (cx_svg, cy_svg - edge, 0, -1, "global news"),     # N
            (cx_svg + edge, cy_svg, 1, 0, ""),                 # E
            (cx_svg, cy_svg + edge, 0, 1, ""),                 # S
            (cx_svg - edge, cy_svg, -1, 0, ""),                # W
        ]
        for sx, sy, dx, dy, label in arrows:
            ex = sx + dx * 6
            ey = sy + dy * 6
            parts.append(
                f'<line x1="{sx:.2f}" y1="{sy:.2f}" x2="{ex:.2f}" y2="{ey:.2f}" '
                f'stroke="{COLOR_INK}" stroke-width="0.6" '
                f'marker-end="url(#arrowhead)"/>'
            )
        # arrowhead marker (defined in <defs> at top)
    elif variant_overlay == "pf":
        # Phone-friction: small phone icons distributed showing reduced pull
        # Use 4 small grey phone marks
        pf_pts = [
            (cx_svg - 12, cy_svg - 8), (cx_svg + 12, cy_svg - 6),
            (cx_svg - 8, cy_svg + 10), (cx_svg + 14, cy_svg + 12),
        ]
        for sx, sy in pf_pts:
            parts.append(
                f'<rect x="{sx-0.8:.2f}" y="{sy-1.3:.2f}" width="1.6" height="2.6" '
                f'fill="{COLOR_INK}" fill-opacity="0.18" '
                f'stroke="{COLOR_INK}" stroke-width="0.2" rx="0.3"/>'
            )

    # Center marker (Plaza proxy = Hub)
    plx, ply = proj_active(cx_atlas, cy_atlas, 0)
    parts.append(
        f'<rect x="{plx - 1.5:.2f}" y="{ply - 1.0:.2f}" '
        f'width="3" height="2" fill="{COLOR_YELLOW}" '
        f'stroke="{COLOR_INK}" stroke-width="0.2"/>'
    )
    parts.append(
        f'<text x="{plx + 2.5:.2f}" y="{ply + 0.6:.2f}" '
        f'font-size="2.4" font-family="Helvetica,sans-serif" '
        f'font-weight="700" fill="{COLOR_INK}">Plaza</text>'
    )

    # 1000m radius label
    parts.append(
        f'<text x="{cx_svg + radius_m * scale * 0.72:.2f}" '
        f'y="{cy_svg - radius_m * scale * 0.72:.2f}" '
        f'font-size="2.2" font-family="Helvetica,sans-serif" '
        f'font-weight="700" fill="{COLOR_PINK}">1000m radius</text>'
    )

    # Landmark callouts (only when --annotate, for the big central map)
    if annotate:
        # 5 named landmarks within radius — picked for geographic spread
        landmarks = [
            ("Lane Cove Plaza", cx_atlas, cy_atlas, "C"),         # center
            ("Council Chambers", 386, -644, "S"),
            ("BP service station", -255, -842, "SW"),
            ("Lane Cove Swim Club", 400, -558, "E"),
            ("Plumber Lane (NE)", 211, -227, "N"),
        ]
        # Callout target positions (pushed away from center)
        callout_offsets = {
            "C":  (0, -22),
            "N":  (-22, -10),
            "S":  (22, 22),
            "E":  (28, 4),
            "SW": (-28, 16),
        }
        for name, ax, ay, dir_key in landmarks:
            sx, sy = proj_active(ax, ay, 0)
            ox, oy = callout_offsets.get(dir_key, (10, -10))
            lx, ly = sx + ox, sy + oy
            # Connector line
            parts.append(
                f'<line x1="{sx:.2f}" y1="{sy:.2f}" '
                f'x2="{lx:.2f}" y2="{ly:.2f}" '
                f'stroke="{COLOR_INK}" stroke-width="0.25" '
                f'stroke-dasharray="0.8 0.6"/>'
            )
            # Landmark dot
            parts.append(
                f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.8" '
                f'fill="{COLOR_YELLOW}" stroke="{COLOR_INK}" stroke-width="0.25"/>'
            )
            # Label box
            text_anchor = "middle"
            if ox > 5: text_anchor = "start"
            elif ox < -5: text_anchor = "end"
            parts.append(
                f'<text x="{lx:.2f}" y="{ly:.2f}" font-size="2.1" '
                f'font-family="Helvetica,sans-serif" font-weight="700" '
                f'text-anchor="{text_anchor}" fill="{COLOR_INK}">{name}</text>'
            )

    # Title (top-left, only when title_text given — used for variant strip)
    if title_text:
        parts.append(
            f'<rect x="0" y="0" width="{svg_w_mm}" height="6" '
            f'fill="{COLOR_INK}"/>'
        )
        parts.append(
            f'<text x="2" y="4.2" font-size="3.2" '
            f'font-family="Helvetica,sans-serif" font-weight="800" '
            f'fill="white">{title_text}</text>'
        )

    # Legend (right side) — skip for variant-strip thumbnails (too crowded)
    if annotate:
        leg_y = svg_h_mm - 18
        leg_x = 2
        legend_items = [
            ("residential / apt", BUILDING_FILL["residential"]),
            ("cafe / restaurant", BUILDING_FILL["cafe"]),
            ("park / playground", OUTDOOR_FILL["park"]),
            ("通行热度 movement density", COLOR_PINK),
        ]
        for i, (label, color) in enumerate(legend_items):
            ly = leg_y + i * 3.4
            parts.append(
                f'<rect x="{leg_x}" y="{ly}" width="2.6" height="2.2" '
                f'fill="{color}" stroke="{COLOR_INK}" stroke-width="0.1"/>'
            )
            parts.append(
                f'<text x="{leg_x + 3.2}" y="{ly + 1.8}" font-size="2.0" '
                f'font-family="Helvetica,sans-serif" fill="{COLOR_INK}">{label}</text>'
            )

    # Footer caption (data provenance)
    if n_seeds > 0:
        cap = (f"Lane Cove · {len(bldg_in)} buildings · "
               f"{n_seeds} seed × 1d baseline · "
               f"{total_changes:,} agent-location events")
    else:
        cap = f"Lane Cove · {len(bldg_in)} buildings (no position data)"
    parts.append(
        f'<text x="{svg_w_mm - 2}" y="{svg_h_mm - 1.5}" font-size="1.9" '
        f'font-family="Helvetica,sans-serif" fill="{COLOR_INK}" '
        f'text-anchor="end" font-style="italic">{cap}</text>'
    )

    parts.append("</svg>")

    out_svg.parent.mkdir(parents=True, exist_ok=True)
    with out_svg.open("w", encoding="utf-8") as fh:
        fh.write("\n".join(parts))
    print(f"[thumbnail] wrote {out_svg} ({out_svg.stat().st_size / 1024:.0f} KB)",
          file=sys.stderr)

    # ----- Stats JSON -----
    total_dwell = sum(dwell_by_type.values()) or 1
    pct_by_type = {k: round(v / total_dwell * 100, 2)
                   for k, v in dwell_by_type.most_common()}
    residential_pct = sum(v for k, v in dwell_by_type.items()
                          if k in {"residential", "apartment", "house"}) / total_dwell * 100
    street_pct = sum(v for k, v in dwell_by_type.items()
                     if "street" in k or "road" in k or "outdoor" in k) / total_dwell * 100

    stats = {
        "n_seeds": n_seeds,
        "n_buildings_in_radius": len(bldg_in),
        "n_outdoor_in_radius": len(out_in),
        "total_position_events": total_changes,
        "dwell_by_type_pct": pct_by_type,
        "dwell_residential_pct": round(residential_pct, 2),
        "dwell_street_pct": round(street_pct, 2),
        "median_changes_per_seed": (
            statistics.median(per_seed_changes) if per_seed_changes else 0
        ),
        "config_note": "1000-agent × 1-day × baseline × stub LLM preflight",
    }
    if stats_out is not None:
        stats_out.parent.mkdir(parents=True, exist_ok=True)
        with stats_out.open("w", encoding="utf-8") as fh:
            json.dump(stats, fh, indent=2, ensure_ascii=False)
        print(f"[thumbnail] wrote stats → {stats_out}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--atlas", type=Path, required=True)
    p.add_argument("--positions", type=str, action="append", default=[],
                   help="glob pattern for seed_*_positions.json; "
                        "repeatable for multiple sources")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--stats-out", type=Path, default=None)
    p.add_argument("--radius-m", type=float, default=1000.0)
    p.add_argument("--center-x", type=float, default=None)
    p.add_argument("--center-y", type=float, default=None)
    p.add_argument("--size-mm", type=str, default="160:110",
                   help="SVG W:H in mm, default 160:110 (suits poster card)")
    p.add_argument("--annotate", action="store_true",
                   help="Add named-landmark callouts + legend (big map only)")
    p.add_argument("--variant", choices=["baseline", "hp", "gd", "pf"],
                   default="baseline",
                   help="Overlay style for the four-variant strip thumbnails")
    p.add_argument("--title", type=str, default="",
                   help="Optional title bar (used for variant strip cards)")
    p.add_argument("--style", choices=["2d", "2.5d"], default="2d",
                   help="2d = top-down (default), 2.5d = isometric/axonometric "
                        "30° with building extrusion (SimCity-style)")
    p.add_argument("--height-exag", type=float, default=1.6,
                   help="In 2.5d mode, vertical exaggeration factor (>1 makes "
                        "buildings look taller relative to footprint). Default 1.6.")
    args = p.parse_args(argv)
    center = (args.center_x, args.center_y) if args.center_x is not None else None
    try:
        w_s, h_s = args.size_mm.split(":")
        size = (float(w_s), float(h_s))
    except Exception:
        print(f"[error] invalid --size-mm {args.size_mm}", file=sys.stderr)
        return 2
    build_thumbnail(
        atlas_path=args.atlas,
        position_globs=args.positions,
        out_svg=args.out,
        stats_out=args.stats_out,
        radius_m=args.radius_m,
        center_xy=center,
        svg_size_mm=size,
        annotate=args.annotate,
        variant_overlay=args.variant,
        title_text=args.title,
        style=args.style,
        height_exaggeration=args.height_exag,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
