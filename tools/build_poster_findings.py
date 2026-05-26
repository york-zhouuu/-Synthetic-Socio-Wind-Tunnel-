"""Build 8 poster-style 2.5D Lane Cove SVG maps, one per finding.

Reuses build_atlas_thumbnail.py's 30° axonometric projection + poster palette
(pink #FF4D8F, yellow #FFD23F, ink #1B1F2A, bg #FCFAF6).
Each SVG mixes 2.5D base map + 2D inset overlays (callout text, bar charts).

Output: docs/poster_finding_<N>_<key>.svg × 8 files.
"""
from __future__ import annotations
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
ATLAS = REPO / "data/lanecove_atlas.json"
ANALYSIS = REPO / "data/analysis/2026-05-23_paper_exploration"
OUT_DIR = REPO / "docs/figures_poster"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Poster palette
BG = "#FCFAF6"
INK = "#1B1F2A"
PINK = "#FF4D8F"
PINK_SOFT = "#FFD5E3"
YELLOW = "#FFD23F"
YELLOW_SOFT = "#FFF2B8"
INK_SOFT = "#4A4F5A"
STREET = "#9E988C"

# Building palette by type (subdued so overlays pop)
BLDG_COLOR = {
    "residential": "#E8E2D8",
    "apartment": "#D8C0B0",
    "house": "#E8E2D8",
    "shop": "#FFE08C",
    "supermarket": "#FFE08C",
    "cafe": "#FFD5E3",
    "restaurant": "#FFD5E3",
    "bar": "#FFD5E3",
    "office": "#C9D6FF",
    "school": "#C0E0BA",
    "hospital": "#F5C7D6",
    "worship": "#C8A6E0",
    "community": "#C8A6E0",
    "entertainment": "#FFD23F",
    "hotel": "#D8C0B0",
    "commercial": "#FFE08C",
    "industrial": "#A8D5BA",
    "utility": "#909AB7",
}
OUTDOOR_COLOR = {
    "park": "#C0E0BA",
    "playground": "#A8D5BA",
    "garden": "#D5EBC8",
}

# 30° axonometric
ISO_COS = math.cos(math.radians(30))
ISO_SIN = math.sin(math.radians(30))

# Building heights in meters (for extrusion)
BLDG_HEIGHT = {
    "residential": 12, "apartment": 30, "house": 7,
    "shop": 8, "supermarket": 10, "cafe": 7, "restaurant": 8, "bar": 7,
    "office": 25, "school": 16, "hospital": 22, "worship": 20,
    "community": 14, "entertainment": 14, "hotel": 28,
    "commercial": 14, "industrial": 14, "utility": 10,
}
HEIGHT_DEFAULT = 10
HEIGHT_EXAG = 1.4


# ──────────────────────────────────────────────────────────────────────
def darken(hex_color: str, factor: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return f"#{int(r * factor):02X}{int(g * factor):02X}{int(b * factor):02X}"


def centroid(verts):
    if not verts: return None
    if isinstance(verts[0], dict):
        xs = [v["x"] for v in verts]; ys = [v["y"] for v in verts]
    else:
        xs = [v[0] for v in verts]; ys = [v[1] for v in verts]
    return sum(xs)/len(xs), sum(ys)/len(ys)


def in_radius(cx, cy, ox, oy, r):
    return (cx - ox)**2 + (cy - oy)**2 <= r**2


# ──────────────────────────────────────────────────────────────────────
class IsoProj:
    """30° iso projection: atlas (m) → SVG (mm)."""
    def __init__(self, center_xy, radius_m, svg_w_mm, svg_h_mm, height_exag=HEIGHT_EXAG):
        self.cx, self.cy = center_xy
        self.r = radius_m
        self.w, self.h = svg_w_mm, svg_h_mm
        self.he = height_exag
        # Pre-compute scale
        pad = 2.0
        iso_w = 2 * radius_m * ISO_COS * 2
        iso_h = 2 * radius_m * ISO_SIN * 2 + 60 * height_exag
        self.scale = min((svg_w_mm - 2 * pad) / iso_w, (svg_h_mm - 2 * pad) / iso_h)

    def proj(self, x, y, z=0.0):
        dx = x - self.cx; dy = y - self.cy
        sx = self.w / 2 + (dx - dy) * ISO_COS * self.scale
        sy = self.h / 2 + (dx + dy) * ISO_SIN * self.scale * (-1)
        sy -= z * self.scale * self.he
        return sx, sy

    def proj_flat(self, x, y):
        return self.proj(x, y, 0)


# ──────────────────────────────────────────────────────────────────────
def load_atlas_filtered(center_xy, radius_m, pad_outdoor=200):
    """Return (buildings_in_radius, outdoors_in_radius, loc_index)."""
    with open(ATLAS) as f:
        atlas = json.load(f)
    cx, cy = center_xy
    bldgs = atlas.get("buildings", {})
    outdoors = atlas.get("outdoor_areas", {})
    bldg_in = []; out_in = []
    loc_idx = {}
    for aid, b in bldgs.items():
        c = centroid(b.get("polygon", {}).get("vertices", []))
        if c is None: continue
        loc_idx[aid] = {"x": c[0], "y": c[1], "name": b.get("name") or aid,
                        "type": b.get("building_type", "unknown"), "kind": "bldg"}
        if in_radius(c[0], c[1], cx, cy, radius_m):
            bldg_in.append((aid, b, c))
    items = outdoors.values() if isinstance(outdoors, dict) else outdoors
    for o in items:
        c = centroid(o.get("polygon", {}).get("vertices", []))
        if c is None: continue
        oid = o.get("id") or "outdoor_unknown"
        loc_idx[oid] = {"x": c[0], "y": c[1], "name": o.get("name") or oid,
                        "type": o.get("area_type", "unknown"), "kind": "outdoor"}
        if in_radius(c[0], c[1], cx, cy, radius_m + pad_outdoor):
            out_in.append((oid, o, c))
    return bldg_in, out_in, loc_idx


# ──────────────────────────────────────────────────────────────────────
def render_base_25d(proj: IsoProj, bldg_in, out_in) -> list[str]:
    """Render the 2.5D Lane Cove base layer (outdoors + extruded buildings)."""
    parts = []
    # Outdoor (streets as thin lines, parks/playgrounds as filled)
    parts.append('<g id="outdoors">')
    for _, o, _ in out_in:
        verts = o.get("polygon", {}).get("vertices", [])
        if len(verts) < 3: continue
        atype = (o.get("area_type") or "").lower()
        is_street = atype in ("street", "")
        path_pts = [proj.proj_flat(v["x"], v["y"]) for v in verts]
        d = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in path_pts) + " Z"
        if is_street:
            parts.append(
                f'<path d="{d}" fill="none" stroke="{STREET}" '
                f'stroke-width="0.18" stroke-opacity="0.45"/>'
            )
        else:
            fill = OUTDOOR_COLOR.get(atype, "#D5EBC8")
            parts.append(
                f'<path d="{d}" fill="{fill}" stroke="none" fill-opacity="0.75"/>'
            )
    parts.append("</g>")

    # Buildings — extruded blocks, back-to-front
    parts.append('<g id="buildings">')
    bldg_sorted = sorted(bldg_in, key=lambda t: (t[2][0] + t[2][1]))
    for _, b, _ in bldg_sorted:
        verts = b.get("polygon", {}).get("vertices", [])
        if len(verts) < 3: continue
        btype = (b.get("building_type") or "").lower()
        h_m = BLDG_HEIGHT.get(btype, HEIGHT_DEFAULT)
        roof_fill = BLDG_COLOR.get(btype, "#E8E2D8")
        side_fill = darken(roof_fill, 0.72)
        shadow_fill = darken(roof_fill, 0.55)
        n = len(verts)
        roof_pts = [proj.proj(v["x"], v["y"], h_m) for v in verts]
        base_pts = [proj.proj_flat(v["x"], v["y"]) for v in verts]
        # Side faces
        for i in range(n):
            bx0, by0 = base_pts[i]
            bx1, by1 = base_pts[(i + 1) % n]
            tx1, ty1 = roof_pts[(i + 1) % n]
            tx0, ty0 = roof_pts[i]
            sa = ((bx1 - bx0) * (ty1 - by1) - (by1 - by0) * (tx1 - bx1))
            if sa >= 0: continue
            edge_dx = bx1 - bx0
            fc = shadow_fill if edge_dx < 0 else side_fill
            d = (
                f'M {bx0:.2f} {by0:.2f} '
                f'L {bx1:.2f} {by1:.2f} '
                f'L {tx1:.2f} {ty1:.2f} '
                f'L {tx0:.2f} {ty0:.2f} Z'
            )
            parts.append(f'<path d="{d}" fill="{fc}" stroke="{INK}" stroke-width="0.04"/>')
        roof_d = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in roof_pts) + " Z"
        parts.append(
            f'<path d="{roof_d}" fill="{roof_fill}" stroke="{INK}" stroke-width="0.06"/>'
        )
    parts.append("</g>")
    return parts


def svg_header(w_mm, h_mm):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{w_mm}mm" height="{h_mm}mm" '
        f'viewBox="0 0 {w_mm} {h_mm}" preserveAspectRatio="xMidYMid meet">\n'
        f'<defs>\n'
        f'  <marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" '
        f'markerUnits="strokeWidth" markerWidth="6" markerHeight="6" orient="auto">'
        f'<path d="M0,0 L10,5 L0,10 z" fill="{INK}"/></marker>\n'
        f'  <marker id="dot" viewBox="-3 -3 6 6" refX="0" refY="0" '
        f'markerWidth="6" markerHeight="6" orient="auto">'
        f'<circle cx="0" cy="0" r="2" fill="{PINK}"/></marker>\n'
        f'  <filter id="glow"><feGaussianBlur stdDeviation="0.5"/></filter>\n'
        f'</defs>\n'
        f'<rect width="100%" height="100%" fill="{BG}"/>\n'
    )


def title_band(w_mm, h_mm, idx, title, takeaway, kicker=""):
    """Header band at top with finding number, title, takeaway pill."""
    return f"""
<g id="header">
  <rect x="0" y="0" width="{w_mm}" height="14" fill="{INK}"/>
  <text x="3" y="5.5" font-family="Helvetica,sans-serif" font-size="2.8"
        font-weight="700" letter-spacing="1.5" fill="{YELLOW}">FINDING {idx} OF 8 {('· ' + kicker) if kicker else ''}</text>
  <text x="3" y="11.5" font-family="Helvetica,sans-serif" font-size="4.5"
        font-weight="900" fill="white">{title}</text>
</g>
<g id="takeaway">
  <rect x="3" y="{h_mm-12}" width="{w_mm-6}" height="9" fill="{PINK}" rx="0.6"/>
  <text x="{w_mm/2}" y="{h_mm-6}" font-family="Helvetica,sans-serif" font-size="3"
        font-weight="800" fill="white" text-anchor="middle">{takeaway}</text>
</g>
"""


def lane_cove_anchor_pin(proj, x, y, color=PINK, height_m=40, label=""):
    """A vertical line + dot indicating a 'pin' at location (x, y)."""
    base_x, base_y = proj.proj_flat(x, y)
    top_x, top_y = proj.proj(x, y, height_m)
    parts = [
        f'<line x1="{base_x:.2f}" y1="{base_y:.2f}" '
        f'x2="{top_x:.2f}" y2="{top_y:.2f}" '
        f'stroke="{INK}" stroke-width="0.4"/>',
        f'<circle cx="{top_x:.2f}" cy="{top_y:.2f}" r="1.6" '
        f'fill="{color}" stroke="{INK}" stroke-width="0.4"/>',
    ]
    if label:
        parts.append(
            f'<text x="{top_x:.2f}" y="{top_y - 2:.2f}" '
            f'font-family="Helvetica,sans-serif" font-size="2.2" '
            f'font-weight="700" fill="{INK}" text-anchor="middle">{label}</text>'
        )
    return parts


# ──────────────────────────────────────────────────────────────────────
# Common setup
# ──────────────────────────────────────────────────────────────────────
SVG_W, SVG_H = 260, 175  # mm — bigger so legends fit


def get_center():
    """Find Lane Cove center: try Hub building, else geometric mean."""
    with open(ATLAS) as f:
        atlas = json.load(f)
    buildings = atlas.get("buildings", {})
    hub = buildings.get("lane_cove_community_hub")
    if hub:
        c = centroid(hub.get("polygon", {}).get("vertices", []))
        if c: return c
    xs, ys = 0, 0; n = 0
    for b in buildings.values():
        c = centroid(b.get("polygon", {}).get("vertices", []))
        if c:
            xs += c[0]; ys += c[1]; n += 1
    return xs / n, ys / n


# ──────────────────────────────────────────────────────────────────────
# Finding 1: Bimodal response — dots colored by responder/non
# ──────────────────────────────────────────────────────────────────────
def fig_finding_1():
    center = get_center()
    RADIUS = 1100
    proj = IsoProj(center, RADIUS, SVG_W, SVG_H)
    bldg_in, out_in, loc_idx = load_atlas_filtered(center, RADIUS)

    parts = [svg_header(SVG_W, SVG_H)]
    parts.append('<g id="map" opacity="0.55">')
    parts.extend(render_base_25d(proj, bldg_in, out_in))
    parts.append("</g>")

    # Load responder data (seed 43 for max visual richness)
    with open(ANALYSIS / "C_responder_profile/agents_hyperlocal_push.json") as f:
        agents = json.load(f)
    resp = []; non = []
    for a in agents:
        if a["seed"] != 43: continue
        if not a.get("home_xy") or a["home_xy"][0] is None: continue
        if a["is_responder"]:
            resp.append(a["home_xy"])
        else:
            non.append(a["home_xy"])

    # Plot non-responders as small grey dots
    parts.append('<g id="non-responders">')
    for x, y in non:
        if not in_radius(x, y, center[0], center[1], RADIUS): continue
        sx, sy = proj.proj_flat(x, y)
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.7" fill="{INK_SOFT}" fill-opacity="0.45"/>')
    parts.append("</g>")

    # Plot responders as larger pink dots with halo
    parts.append('<g id="responders">')
    for x, y in resp:
        if not in_radius(x, y, center[0], center[1], RADIUS): continue
        sx, sy = proj.proj_flat(x, y)
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="2.2" fill="{PINK}" fill-opacity="0.15" stroke="none"/>')
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="1.1" fill="{PINK}" stroke="{INK}" stroke-width="0.15"/>')
    parts.append("</g>")

    # 2D inset: pie chart top-right
    cx_p, cy_p = SVG_W - 32, 32
    parts.append('<g id="inset-pie">')
    parts.append(f'<rect x="{cx_p-22}" y="{cy_p-22}" width="44" height="44" fill="white" stroke="{INK}" stroke-width="0.3" opacity="0.94"/>')
    # Pie: 22.7% responder
    pct = 22.7
    angle = pct / 100 * 2 * math.pi
    x1 = cx_p + 15 * math.sin(angle)
    y1 = cy_p - 15 * math.cos(angle)
    large = 0 if pct < 50 else 1
    parts.append(f'<circle cx="{cx_p}" cy="{cy_p}" r="15" fill="{INK_SOFT}" opacity="0.3"/>')
    parts.append(f'<path d="M {cx_p} {cy_p} L {cx_p} {cy_p-15} A 15 15 0 {large} 1 {x1:.2f} {y1:.2f} Z" fill="{PINK}"/>')
    parts.append(f'<text x="{cx_p}" y="{cy_p-19}" font-family="Helvetica,sans-serif" font-size="2.4" font-weight="700" fill="{INK}" text-anchor="middle">响应率 (HP)</text>')
    parts.append(f'<text x="{cx_p}" y="{cy_p+1}" font-family="Helvetica,sans-serif" font-size="3.6" font-weight="900" fill="white" text-anchor="middle">22.7%</text>')
    parts.append(f'<text x="{cx_p}" y="{cy_p+5}" font-family="Helvetica,sans-serif" font-size="1.8" fill="white" text-anchor="middle">n=682 / 3000</text>')
    parts.append("</g>")

    # Legend top-left
    lx, ly = 4, 18
    parts.append(f'<g id="legend">')
    parts.append(f'<rect x="{lx}" y="{ly}" width="50" height="14" fill="white" stroke="{INK}" stroke-width="0.3" opacity="0.94"/>')
    parts.append(f'<circle cx="{lx+3}" cy="{ly+4}" r="1.1" fill="{PINK}"/>')
    parts.append(f'<text x="{lx+6}" y="{ly+4.8}" font-family="Helvetica,sans-serif" font-size="2.4" font-weight="700" fill="{INK}">响应者 (n={len(resp)})</text>')
    parts.append(f'<circle cx="{lx+3}" cy="{ly+10}" r="0.7" fill="{INK_SOFT}"/>')
    parts.append(f'<text x="{lx+6}" y="{ly+10.8}" font-family="Helvetica,sans-serif" font-size="2.4" font-weight="700" fill="{INK}">非响应者 (n={len(non)})</text>')
    parts.append("</g>")

    parts.append(title_band(SVG_W, SVG_H, 1,
        "物理位移是双峰的:22.7% 大动,77.3% 完全不动",
        "响应者地理聚集成簇,不是随机分布 → 暗示空间机制",
        kicker="双峰响应"))
    parts.append("</svg>")
    write(OUT_DIR / "poster_finding_1_bimodal.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# Finding 2: Spillover with 200m rings
# ──────────────────────────────────────────────────────────────────────
def fig_finding_2():
    center = get_center()
    RADIUS = 1100
    proj = IsoProj(center, RADIUS, SVG_W, SVG_H)
    bldg_in, out_in, _ = load_atlas_filtered(center, RADIUS)

    parts = [svg_header(SVG_W, SVG_H)]
    parts.append('<g id="map" opacity="0.55">')
    parts.extend(render_base_25d(proj, bldg_in, out_in))
    parts.append("</g>")

    # Find top 30 protag-responders with most responder neighbors
    with open(ANALYSIS / "C_responder_profile/agents_hyperlocal_push.json") as f:
        agents = json.load(f)
    protag_resp = [a for a in agents if a["seed"] == 43 and a["is_protagonist"] and a["is_responder"]
                   and a.get("home_xy") and a["home_xy"][0] is not None]
    # Score by neighbor density
    scored = []
    for c in protag_resp:
        cx, cy = c["home_xy"]
        nr = sum(1 for o in protag_resp if o is not c
                 and math.hypot(o["home_xy"][0]-cx, o["home_xy"][1]-cy) <= 200)
        scored.append((nr, c))
    scored.sort(key=lambda t: -t[0])
    top = scored[:20]

    # Plot 200m rings as ellipses (iso-projected circles → ellipses)
    parts.append('<g id="rings">')
    for nr, c in top:
        x, y = c["home_xy"]
        if not in_radius(x, y, center[0], center[1], RADIUS): continue
        sx, sy = proj.proj_flat(x, y)
        # Iso-projected circle: rx = 200 * scale * cos(30) * sqrt(2), ry = 200 * scale * sin(30) * sqrt(2)
        rx = 200 * proj.scale * ISO_COS * math.sqrt(2)
        ry = 200 * proj.scale * ISO_SIN * math.sqrt(2)
        parts.append(f'<ellipse cx="{sx:.2f}" cy="{sy:.2f}" rx="{rx:.2f}" ry="{ry:.2f}" '
                     f'fill="{PINK}" fill-opacity="0.10" stroke="{PINK}" stroke-width="0.35" stroke-dasharray="1.2 0.8"/>')
        # Pin at center
        parts.extend(lane_cove_anchor_pin(proj, x, y, PINK, height_m=35))
    parts.append("</g>")

    # 2D inset: distance-decay bar chart top-right
    parts.append('<g id="inset-bars">')
    bx, by, bw, bh = SVG_W - 65, 20, 60, 50
    parts.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" fill="white" stroke="{INK}" stroke-width="0.3" opacity="0.95"/>')
    parts.append(f'<text x="{bx + bw/2}" y="{by+4}" font-family="Helvetica,sans-serif" font-size="2.6" font-weight="900" fill="{INK}" text-anchor="middle">距离衰减(米 → 响应率)</text>')
    bars = [("0-50",26.2),("50-100",20.6),("100-150",11.4),("150-200",4.3),("200-300",4.4),("300+",1.0)]
    chart_x = bx + 4; chart_w = bw - 8
    chart_y = by + 8; chart_h = bh - 14
    bar_w = chart_w / len(bars) - 0.5
    max_v = 28
    for i, (lbl, v) in enumerate(bars):
        h = (v/max_v) * chart_h
        x0 = chart_x + i * (chart_w/len(bars))
        y0 = chart_y + chart_h - h
        color = PINK if v > 8 else INK_SOFT
        parts.append(f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{bar_w:.2f}" height="{h:.2f}" fill="{color}"/>')
        parts.append(f'<text x="{x0 + bar_w/2:.2f}" y="{y0-0.4:.2f}" font-family="Helvetica,sans-serif" font-size="1.7" font-weight="700" fill="{INK}" text-anchor="middle">{v}%</text>')
        parts.append(f'<text x="{x0 + bar_w/2:.2f}" y="{chart_y + chart_h + 2.5:.2f}" font-family="Helvetica,sans-serif" font-size="1.4" fill="{INK_SOFT}" text-anchor="middle">{lbl}</text>')
    parts.append("</g>")

    parts.append(title_band(SVG_W, SVG_H, 2,
        "邻居传染有几何形状:200米内26%,外4%",
        "推送的真实作用域 = 收推送的人 + 半径~150m 邻居 → 8倍 spillover",
        kicker="空间传染"))
    parts.append("</svg>")
    write(OUT_DIR / "poster_finding_2_spillover.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# Finding 3: Repeat hotspots — extruded columns at top dwell locations
# ──────────────────────────────────────────────────────────────────────
def fig_finding_3():
    center = get_center()
    RADIUS = 1100
    proj = IsoProj(center, RADIUS, SVG_W, SVG_H)
    bldg_in, out_in, loc_idx = load_atlas_filtered(center, RADIUS)

    parts = [svg_header(SVG_W, SVG_H)]
    parts.append('<g id="map" opacity="0.5">')
    parts.extend(render_base_25d(proj, bldg_in, out_in))
    parts.append("</g>")

    # Top hot locations from activation data
    with open(ANALYSIS / "A_poi_activation/activation_per_location.json") as f:
        a_data = json.load(f)
    hp_acts = list(a_data["activation_vs_baseline"]["hyperlocal_push"].values())
    hp_acts = [a for a in hp_acts if a["variant_mean"] > 1000]
    hp_acts.sort(key=lambda r: -r["variant_mean"])
    top = hp_acts[:60]

    parts.append('<g id="hotspots">')
    max_dwell = max(t["variant_mean"] for t in top) if top else 1
    for t in top:
        if t["x"] is None: continue
        x, y = t["x"], t["y"]
        if not in_radius(x, y, center[0], center[1], RADIUS): continue
        # Column height proportional to sqrt(dwell)
        h_m = math.sqrt(t["variant_mean"]) * 0.4
        # Draw extruded column
        sx_b, sy_b = proj.proj_flat(x, y)
        sx_t, sy_t = proj.proj(x, y, h_m)
        ratio = t["variant_mean"] / max_dwell
        color = PINK if ratio > 0.5 else YELLOW if ratio > 0.2 else "#FFD5E3"
        # vertical line for column
        parts.append(f'<line x1="{sx_b:.2f}" y1="{sy_b:.2f}" x2="{sx_t:.2f}" y2="{sy_t:.2f}" '
                     f'stroke="{color}" stroke-width="{1.0 + ratio*2:.2f}" stroke-linecap="round"/>')
        # top circle
        parts.append(f'<circle cx="{sx_t:.2f}" cy="{sy_t:.2f}" r="{0.6 + ratio*1.2:.2f}" '
                     f'fill="{color}" stroke="{INK}" stroke-width="0.2"/>')
    parts.append("</g>")

    # 2D inset bottom-right: bar chart of repeats/pair
    bx, by, bw, bh = SVG_W - 65, SVG_H - 70, 60, 45
    parts.append('<g id="inset">')
    parts.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" fill="white" stroke="{INK}" stroke-width="0.3" opacity="0.95"/>')
    parts.append(f'<text x="{bx + bw/2}" y="{by+4}" font-family="Helvetica,sans-serif" font-size="2.5" font-weight="900" fill="{INK}" text-anchor="middle">每对邻居 14 天相遇次数</text>')
    bars = [("BL",17.3,INK_SOFT),("HP",71.1,PINK),("GD",23.8,"#3d7ec8"),("PF",69.1,"#3dc873")]
    chart_x = bx + 3; chart_w = bw - 6
    chart_y = by + 8; chart_h = bh - 12
    bar_w = chart_w / len(bars) - 1
    max_v = 80
    for i, (lbl, v, col) in enumerate(bars):
        h = (v/max_v) * chart_h
        x0 = chart_x + i * (chart_w/len(bars))
        y0 = chart_y + chart_h - h
        parts.append(f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{bar_w:.2f}" height="{h:.2f}" fill="{col}"/>')
        parts.append(f'<text x="{x0 + bar_w/2:.2f}" y="{y0-0.4:.2f}" font-family="Helvetica,sans-serif" font-size="2" font-weight="700" fill="{INK}" text-anchor="middle">{v:.1f}</text>')
        parts.append(f'<text x="{x0 + bar_w/2:.2f}" y="{chart_y + chart_h + 2.8:.2f}" font-family="Helvetica,sans-serif" font-size="1.8" font-weight="700" fill="{INK}" text-anchor="middle">{lbl}</text>')
    parts.append("</g>")

    parts.append(title_band(SVG_W, SVG_H, 3,
        "重复见面机制:同人见面 4 倍多次",
        "弱关系沉淀为强关系 → 强关系数量 5.6× 翻倍",
        kicker="频次→关系"))
    parts.append("</svg>")
    write(OUT_DIR / "poster_finding_3_repeat.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# Finding 4: Post-period compounding — 14-day curves overlaid on map
# ──────────────────────────────────────────────────────────────────────
def fig_finding_4():
    center = get_center()
    RADIUS = 1100
    proj = IsoProj(center, RADIUS, SVG_W, SVG_H)
    bldg_in, out_in, _ = load_atlas_filtered(center, RADIUS)

    parts = [svg_header(SVG_W, SVG_H)]
    parts.append('<g id="map" opacity="0.4">')
    parts.extend(render_base_25d(proj, bldg_in, out_in))
    parts.append("</g>")

    # Load daily encounter data
    with open(ANALYSIS / "B_temporal_curves/per_day_series.json") as f:
        tc = json.load(f)

    # Large curve chart center-right, on top of map
    cx, cy = SVG_W * 0.55, SVG_H * 0.45
    chart_w, chart_h = 130, 70
    parts.append('<g id="chart">')
    parts.append(f'<rect x="{cx-chart_w/2}" y="{cy-chart_h/2}" width="{chart_w}" height="{chart_h}" fill="white" stroke="{INK}" stroke-width="0.3" opacity="0.96"/>')
    # Phase shading
    chart_x = cx - chart_w/2 + 8
    chart_y = cy - chart_h/2 + 6
    plot_w = chart_w - 16
    plot_h = chart_h - 14
    # Phase backgrounds
    parts.append(f'<rect x="{chart_x}" y="{chart_y}" width="{plot_w * 4/14:.2f}" height="{plot_h}" fill="#E5E2D6" opacity="0.6"/>')
    parts.append(f'<rect x="{chart_x + plot_w * 4/14:.2f}" y="{chart_y}" width="{plot_w * 6/14:.2f}" height="{plot_h}" fill="{PINK}" opacity="0.12"/>')
    parts.append(f'<rect x="{chart_x + plot_w * 10/14:.2f}" y="{chart_y}" width="{plot_w * 4/14:.2f}" height="{plot_h}" fill="#E5E2D6" opacity="0.6"/>')
    # Phase labels
    parts.append(f'<text x="{chart_x + plot_w*2/14:.2f}" y="{chart_y-0.6:.2f}" font-family="Helvetica,sans-serif" font-size="2" font-weight="700" fill="{INK}" text-anchor="middle">基线 day 0-3</text>')
    parts.append(f'<text x="{chart_x + plot_w*7/14:.2f}" y="{chart_y-0.6:.2f}" font-family="Helvetica,sans-serif" font-size="2" font-weight="900" fill="{PINK}" text-anchor="middle">干预 day 4-9</text>')
    parts.append(f'<text x="{chart_x + plot_w*12/14:.2f}" y="{chart_y-0.6:.2f}" font-family="Helvetica,sans-serif" font-size="2" font-weight="700" fill="{INK}" text-anchor="middle">后撤 day 10-13</text>')

    # Plot lines
    max_v = 5.0  # millions
    variants = [
        ("hyperlocal_push", PINK, "HP"),
        ("phone_friction", "#3dc873", "PF"),
        ("global_distraction", "#3d7ec8", "GD"),
        ("baseline", INK_SOFT, "BL"),
    ]
    for vkey, color, lbl in variants:
        series = tc["data"][f"{vkey}|encounter_count_total"]
        pts = []
        for d, s in enumerate(series[:14]):
            v = (s["mean"] or 0) / 1e6
            px = chart_x + (d / 13) * plot_w
            py = chart_y + plot_h - (v / max_v) * plot_h
            pts.append((px, py))
        path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in pts)
        parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="0.8"/>')
        for x, y in pts:
            parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="0.6" fill="{color}"/>')
        # label at end
        last_x, last_y = pts[-1]
        parts.append(f'<text x="{last_x+1.2:.2f}" y="{last_y+1:.2f}" font-family="Helvetica,sans-serif" font-size="2.2" font-weight="900" fill="{color}">{lbl}</text>')

    # Y axis
    for v in [0, 1, 2, 3, 4, 5]:
        py = chart_y + plot_h - (v/max_v) * plot_h
        parts.append(f'<text x="{chart_x-1:.2f}" y="{py+0.6:.2f}" font-family="Helvetica,sans-serif" font-size="1.6" fill="{INK_SOFT}" text-anchor="end">{v}M</text>')

    # X axis day labels
    for d in [0, 4, 9, 13]:
        px = chart_x + (d / 13) * plot_w
        parts.append(f'<text x="{px:.2f}" y="{chart_y + plot_h + 2.4:.2f}" font-family="Helvetica,sans-serif" font-size="1.6" font-weight="700" fill="{INK}" text-anchor="middle">d{d}</text>')

    # Big arrow + annotation pointing to post-period growth
    end_x = chart_x + plot_w
    parts.append(f'<line x1="{end_x-15:.2f}" y1="{chart_y+5:.2f}" x2="{end_x-2:.2f}" y2="{chart_y+1:.2f}" stroke="{PINK}" stroke-width="0.6" marker-end="url(#ah)"/>')
    parts.append(f'<text x="{end_x-20:.2f}" y="{chart_y+8:.2f}" font-family="Helvetica,sans-serif" font-size="2.2" font-weight="900" fill="{PINK}">post 仍增长 1.32×</text>')

    parts.append("</g>")

    parts.append(title_band(SVG_W, SVG_H, 4,
        "推送停了之后,效应仍在生长 — 1.32×",
        "干预不用永远跑;一旦推到新位置,网络效应自维持",
        kicker="持久性"))
    parts.append("</svg>")
    write(OUT_DIR / "poster_finding_4_compounding.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# Finding 5: Mirror comparison — side-by-side HP vs GD activated columns
# ──────────────────────────────────────────────────────────────────────
def fig_finding_5():
    center = get_center()
    RADIUS = 900
    # Two side-by-side maps
    map_w = SVG_W / 2 - 4
    proj_hp = IsoProj(center, RADIUS, map_w, SVG_H - 30)
    proj_gd = IsoProj(center, RADIUS, map_w, SVG_H - 30)
    bldg_in, out_in, _ = load_atlas_filtered(center, RADIUS)

    parts = [svg_header(SVG_W, SVG_H)]

    # Helper to render one side
    def render_side(proj, x_offset, label, color, acts_top, takeaway_value):
        # Embed translated SVG in <g transform>
        parts.append(f'<g transform="translate({x_offset}, 18)">')
        parts.append(f'<rect x="0" y="0" width="{map_w}" height="{SVG_H-30}" fill="{BG}" stroke="{INK}" stroke-width="0.4"/>')
        # Base map
        parts.append('<g opacity="0.45">')
        parts.extend(render_base_25d(proj, bldg_in, out_in))
        parts.append("</g>")
        # Top label
        parts.append(f'<text x="{map_w/2:.2f}" y="6" font-family="Helvetica,sans-serif" font-size="3.5" font-weight="900" fill="{color}" text-anchor="middle">{label}</text>')
        parts.append(f'<text x="{map_w/2:.2f}" y="10" font-family="Helvetica,sans-serif" font-size="6" font-weight="900" fill="{color}" text-anchor="middle">{takeaway_value}</text>')
        # Activated POI columns
        max_d = max(a["abs_delta"] for a in acts_top) if acts_top else 1
        for a in acts_top:
            if a.get("x") is None: continue
            x, y = a["x"], a["y"]
            if not in_radius(x, y, center[0], center[1], RADIUS): continue
            h_m = math.sqrt(max(0, a["abs_delta"])) * 0.5
            sx_b, sy_b = proj.proj_flat(x, y)
            sx_t, sy_t = proj.proj(x, y, h_m)
            parts.append(f'<line x1="{sx_b:.2f}" y1="{sy_b:.2f}" x2="{sx_t:.2f}" y2="{sy_t:.2f}" stroke="{color}" stroke-width="0.9" stroke-linecap="round"/>')
            parts.append(f'<circle cx="{sx_t:.2f}" cy="{sy_t:.2f}" r="0.8" fill="{color}" stroke="{INK}" stroke-width="0.15"/>')
        parts.append("</g>")

    # Load activation
    with open(ANALYSIS / "A_poi_activation/activation_per_location.json") as f:
        a_data = json.load(f)
    hp_acts = sorted(list(a_data["activation_vs_baseline"]["hyperlocal_push"].values()),
                     key=lambda r: -r["abs_delta"])[:50]
    gd_acts = sorted(list(a_data["activation_vs_baseline"]["global_distraction"].values()),
                     key=lambda r: -r["abs_delta"])[:50]

    render_side(proj_hp, 2, "超在地推送 HP", PINK, hp_acts, "+377%")
    render_side(proj_gd, SVG_W/2 + 2, "镜像 · 全球新闻 GD", "#3d7ec8", gd_acts, "+33%")

    parts.append(title_band(SVG_W, SVG_H, 5,
        "镜像组验证:必须是「附近的内容」,不是「推送动作」",
        "同样推送 5 条/天:HP encounter +377% vs GD +33% → 内容指向决定效应",
        kicker="因果验证"))
    parts.append("</svg>")
    write(OUT_DIR / "poster_finding_5_mirror.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# Finding 6: POI activation with real names
# ──────────────────────────────────────────────────────────────────────
def fig_finding_6():
    center = get_center()
    RADIUS = 1100
    proj = IsoProj(center, RADIUS, SVG_W, SVG_H)
    bldg_in, out_in, _ = load_atlas_filtered(center, RADIUS)

    parts = [svg_header(SVG_W, SVG_H)]
    parts.append('<g id="map" opacity="0.55">')
    parts.extend(render_base_25d(proj, bldg_in, out_in))
    parts.append("</g>")

    # Top POIs
    with open(ANALYSIS / "DEEP_MINING/specific_pois.json") as f:
        sp = json.load(f)
    top = sp["top_activated"][:12]

    # Load atlas for centroids
    with open(ATLAS) as f:
        atlas = json.load(f)
    buildings = atlas.get("buildings", {})
    outdoor = atlas.get("outdoor_areas", {})
    if isinstance(outdoor, list):
        outdoor = {o["id"]: o for o in outdoor}

    parts.append('<g id="pois">')
    max_d = max(p["abs_delta_ticks"] for p in top) if top else 1
    label_pos = []
    for p in top:
        loc_id = p["loc_id"]
        b = buildings.get(loc_id) or outdoor.get(loc_id)
        if not b: continue
        c = centroid(b.get("polygon", {}).get("vertices", []))
        if c is None: continue
        x, y = c
        if not in_radius(x, y, center[0], center[1], RADIUS): continue
        h_m = math.sqrt(p["abs_delta_ticks"]) * 0.42
        sx_b, sy_b = proj.proj_flat(x, y)
        sx_t, sy_t = proj.proj(x, y, h_m)
        ratio = p["abs_delta_ticks"] / max_d
        color = PINK if ratio > 0.5 else YELLOW if ratio > 0.15 else "#FFD5E3"
        parts.append(f'<line x1="{sx_b:.2f}" y1="{sy_b:.2f}" x2="{sx_t:.2f}" y2="{sy_t:.2f}" '
                     f'stroke="{color}" stroke-width="{1.8 + ratio*2:.2f}" stroke-linecap="round"/>')
        parts.append(f'<circle cx="{sx_t:.2f}" cy="{sy_t:.2f}" r="{1.0 + ratio*1.6:.2f}" '
                     f'fill="{color}" stroke="{INK}" stroke-width="0.25"/>')
        label_pos.append((sx_t, sy_t, p))
    parts.append("</g>")

    # Labels for top 6 (avoid overlapping)
    parts.append('<g id="labels">')
    label_pos.sort(key=lambda t: -t[2]["abs_delta_ticks"])
    label_idx = 0
    for sx_t, sy_t, p in label_pos[:8]:
        name = (p.get("name") or "?")
        if len(name) > 24: name = name[:22] + "…"
        # Position: stagger above/below
        ly = sy_t - 4 if label_idx % 2 == 0 else sy_t + 4
        parts.append(f'<rect x="{sx_t-13:.2f}" y="{ly-3:.2f}" width="26" height="4.5" fill="{INK}" rx="0.4"/>')
        parts.append(f'<text x="{sx_t:.2f}" y="{ly+0.3:.2f}" font-family="Helvetica,sans-serif" font-size="1.9" font-weight="700" fill="white" text-anchor="middle">{name}</text>')
        parts.append(f'<line x1="{sx_t:.2f}" y1="{sy_t:.2f}" x2="{sx_t:.2f}" y2="{ly:.2f}" stroke="{INK}" stroke-width="0.2"/>')
        label_idx += 1
    parts.append("</g>")

    # Inset: legend of top 12 POIs with delta numbers
    bx, by, bw, bh = 4, 18, 62, 100
    parts.append('<g id="inset">')
    parts.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" fill="white" stroke="{INK}" stroke-width="0.3" opacity="0.96"/>')
    parts.append(f'<text x="{bx + bw/2}" y="{by+4}" font-family="Helvetica,sans-serif" font-size="2.4" font-weight="900" fill="{INK}" text-anchor="middle">Top 10 被激活地点</text>')
    for i, p in enumerate(top[:10]):
        name = (p.get("name") or "?")
        if len(name) > 23: name = name[:21] + "…"
        ty = by + 9 + i * 8.5
        parts.append(f'<text x="{bx+2}" y="{ty}" font-family="Helvetica,sans-serif" font-size="1.8" font-weight="700" fill="{INK}">{i+1}. {name}</text>')
        parts.append(f'<text x="{bx+2}" y="{ty+3.0}" font-family="Helvetica,sans-serif" font-size="1.6" fill="{PINK}" font-weight="900">+{p["abs_delta_ticks"]:,} ticks (+{p["activation_pct"]:.0f}%)</text>')
    parts.append("</g>")

    parts.append(title_band(SVG_W, SVG_H, 6,
        "Lane Cove 真实街角被点亮:Longueville Park 从 0 ticks 涨到 21K",
        "「楼下死区」变成「日常聚集点」 — 推送有具体的地理后果",
        kicker="真实地理"))
    parts.append("</svg>")
    write(OUT_DIR / "poster_finding_6_pois.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# Finding 7: Cross-occupation bridges as arcs
# ──────────────────────────────────────────────────────────────────────
def fig_finding_7():
    center = get_center()
    RADIUS = 1100
    proj = IsoProj(center, RADIUS, SVG_W, SVG_H)
    bldg_in, out_in, _ = load_atlas_filtered(center, RADIUS)

    parts = [svg_header(SVG_W, SVG_H)]
    parts.append('<g id="map" opacity="0.5">')
    parts.extend(render_base_25d(proj, bldg_in, out_in))
    parts.append("</g>")

    # Load profiles to find representative agents per occupation
    with open(REPO / "data/population_cache/v1/08d79c69cc045b32.json") as f:  # seed 43
        d = json.load(f)
    profs = {p["agent_id"]: p for p in d["profiles"]}
    by_occ = defaultdict(list)
    for p in profs.values():
        by_occ[p.get("occupation", "?")].append(p)

    def occ_home_xy(occ):
        for p in by_occ.get(occ, []):
            h = p.get("home_location")
            for src in (atlas_buildings, atlas_outdoor):
                if h and h in src:
                    c = centroid(src[h].get("polygon", {}).get("vertices", []))
                    if c: return c
        return None

    with open(ATLAS) as f:
        atlas = json.load(f)
    atlas_buildings = atlas.get("buildings", {})
    atlas_outdoor = atlas.get("outdoor_areas", {})
    if isinstance(atlas_outdoor, list):
        atlas_outdoor = {o["id"]: o for o in atlas_outdoor}

    student_home = occ_home_xy("student")
    if not student_home: student_home = center
    targets = [
        ("学生→工人 (+1029)", "tradesperson", PINK),
        ("学生→建筑工 (+709)", "construction", PINK),
        ("学生→工程师 (+580)", "engineer", PINK),
        ("学生→管理者 (+514)", "manager", PINK),
        ("学生→律师 (+490)", "lawyer", PINK),
        ("学生→退休 (+925)", "retired", PINK),
    ]

    # Arcs from student home to each target
    parts.append('<g id="arcs">')
    sx_s, sy_s = proj.proj_flat(student_home[0], student_home[1])
    for label, occ, color in targets:
        tgt = occ_home_xy(occ)
        if not tgt: continue
        if not in_radius(tgt[0], tgt[1], center[0], center[1], RADIUS): continue
        tx, ty = proj.proj_flat(tgt[0], tgt[1])
        # Arc: quadratic Bezier with control point above midpoint
        mx, my = (sx_s + tx) / 2, (sy_s + ty) / 2 - 12
        parts.append(f'<path d="M {sx_s:.2f} {sy_s:.2f} Q {mx:.2f} {my:.2f} {tx:.2f} {ty:.2f}" '
                     f'fill="none" stroke="{color}" stroke-width="0.55" opacity="0.8" marker-end="url(#ah)"/>')
        # End label
        parts.append(f'<rect x="{tx-15:.2f}" y="{ty+2:.2f}" width="30" height="3.5" fill="{INK}" rx="0.4"/>')
        parts.append(f'<text x="{tx:.2f}" y="{ty+4.7:.2f}" font-family="Helvetica,sans-serif" font-size="1.7" font-weight="700" fill="white" text-anchor="middle">{label}</text>')
    parts.append("</g>")

    # Student home as big blue dot
    parts.append(f'<circle cx="{sx_s:.2f}" cy="{sy_s:.2f}" r="3.5" fill="#3d7ec8" stroke="{INK}" stroke-width="0.35"/>')
    parts.append(f'<text x="{sx_s:.2f}" y="{sy_s-5:.2f}" font-family="Helvetica,sans-serif" font-size="2.5" font-weight="900" fill="#3d7ec8" text-anchor="middle">学生群体</text>')

    parts.append(title_band(SVG_W, SVG_H, 7,
        "新出现的「跨职业桥」:学生↔工人/工程师/律师",
        "基线下 0 次共处的职业对,HP 下出现 500-1000 次 → 物理破除阶层隔阂",
        kicker="跨群体"))
    parts.append("</svg>")
    write(OUT_DIR / "poster_finding_7_bridges.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# Finding 8: Hub agents — Pareto inequality
# ──────────────────────────────────────────────────────────────────────
def fig_finding_8():
    center = get_center()
    RADIUS = 1100
    proj = IsoProj(center, RADIUS, SVG_W, SVG_H)
    bldg_in, out_in, _ = load_atlas_filtered(center, RADIUS)

    parts = [svg_header(SVG_W, SVG_H)]
    parts.append('<g id="map" opacity="0.5">')
    parts.extend(render_base_25d(proj, bldg_in, out_in))
    parts.append("</g>")

    # Top hub agents (seed 43 protag-responders by deviation)
    with open(ANALYSIS / "C_responder_profile/agents_hyperlocal_push.json") as f:
        agents = json.load(f)
    hubs = sorted([a for a in agents if a["seed"] == 43 and a["is_responder"]
                   and a.get("home_xy") and a["home_xy"][0] is not None],
                  key=lambda a: -a["deviation_m"])[:30]

    parts.append('<g id="hubs">')
    max_dev = max(h["deviation_m"] for h in hubs) if hubs else 1
    for h in hubs:
        x, y = h["home_xy"]
        if not in_radius(x, y, center[0], center[1], RADIUS): continue
        h_m = (h["deviation_m"] / max_dev) * 80
        sx_b, sy_b = proj.proj_flat(x, y)
        sx_t, sy_t = proj.proj(x, y, h_m)
        # Glow ring at base
        parts.append(f'<circle cx="{sx_b:.2f}" cy="{sy_b:.2f}" r="2.5" fill="{YELLOW}" fill-opacity="0.3" filter="url(#glow)"/>')
        # Vertical column
        parts.append(f'<line x1="{sx_b:.2f}" y1="{sy_b:.2f}" x2="{sx_t:.2f}" y2="{sy_t:.2f}" '
                     f'stroke="{PINK}" stroke-width="1.4" stroke-linecap="round"/>')
        parts.append(f'<circle cx="{sx_t:.2f}" cy="{sy_t:.2f}" r="1.2" fill="{YELLOW}" stroke="{INK}" stroke-width="0.3"/>')
    parts.append("</g>")

    # Pareto inset: lines
    bx, by, bw, bh = SVG_W - 78, 18, 73, 60
    parts.append('<g id="inset">')
    parts.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" fill="white" stroke="{INK}" stroke-width="0.3" opacity="0.96"/>')
    parts.append(f'<text x="{bx + bw/2}" y="{by+4}" font-family="Helvetica,sans-serif" font-size="2.4" font-weight="900" fill="{INK}" text-anchor="middle">Top X% agent 占共处量份额</text>')
    px = bx + 6; py = by + 8; pw = bw - 12; ph = bh - 14
    pcts = ["1","5","10","25","50"]
    bl_vals = [3.3, 13.9, 24.7, 48.9, 76.6]
    hp_vals = [5.9, 28.4, 52.4, 84.8, 94.2]
    # axes
    parts.append(f'<line x1="{px}" y1="{py+ph}" x2="{px+pw}" y2="{py+ph}" stroke="{INK}" stroke-width="0.2"/>')
    parts.append(f'<line x1="{px}" y1="{py}" x2="{px}" y2="{py+ph}" stroke="{INK}" stroke-width="0.2"/>')
    # Lines
    for vals, color, lbl in [(bl_vals, INK_SOFT, "BL"), (hp_vals, PINK, "HP")]:
        pts = []
        for i, v in enumerate(vals):
            x = px + (i / (len(vals)-1)) * pw
            y = py + ph - (v/100) * ph
            pts.append((x, y))
        path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in pts)
        parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="0.6"/>')
        for x, y in pts:
            parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="0.6" fill="{color}"/>')
        # Label end
        parts.append(f'<text x="{pts[-1][0]+1.5:.2f}" y="{pts[-1][1]+0.5:.2f}" font-family="Helvetica,sans-serif" font-size="2" font-weight="900" fill="{color}">{lbl}</text>')
    # X labels
    for i, p in enumerate(pcts):
        x = px + (i / (len(pcts)-1)) * pw
        parts.append(f'<text x="{x:.2f}" y="{py+ph+2.5:.2f}" font-family="Helvetica,sans-serif" font-size="1.6" fill="{INK_SOFT}" text-anchor="middle">{p}%</text>')

    parts.append("</g>")

    parts.append(title_band(SVG_W, SVG_H, 8,
        "社交活动集中在少数 hub:top 10% agent 占 52% 共处量",
        "「附近性」回归不是普遍现象,而是重构成局部 hub 中心圈",
        kicker="网络拓扑"))
    parts.append("</svg>")
    write(OUT_DIR / "poster_finding_8_hubs.svg", parts)


# ──────────────────────────────────────────────────────────────────────
def write(path, parts):
    with open(path, "w") as f:
        f.write("\n".join(parts))
    print(f"  → {path.name} ({path.stat().st_size//1024} KB)")


def main():
    print("Building 8 poster-style finding SVGs...")
    print(f"Output: {OUT_DIR}/")
    for fn in [fig_finding_1, fig_finding_2, fig_finding_3, fig_finding_4,
               fig_finding_5, fig_finding_6, fig_finding_7, fig_finding_8]:
        try: fn()
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"FAILED: {fn.__name__}: {e}")
    print(f"\nDone. Files in {OUT_DIR}")


if __name__ == "__main__":
    main()
