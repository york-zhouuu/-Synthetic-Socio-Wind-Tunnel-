"""F1 · 2.5D topology figure — dual panel within baseline.

Left panel : WHERE PEOPLE MEET  (encounter volume, neutral grey)
Right panel: WHERE PEOPLE NOTICE (noticed volume, warm-pink rate ramp)
              + 4 named callouts (2 awareness islands + 2 blindness canyons)

Base map: re-use tools/build_atlas_thumbnail.py to generate a clean 2.5d
axonometric base, then post-process to overlay F1 circles + callouts +
headlines + pullquote in a composite parent SVG.

Output: data/analysis/.../F1_shape/f1_25d_topology.svg
"""
from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
ATLAS_PATH = REPO / "data/lanecove_atlas.json"
F1_JSON = REPO / "data/analysis/2026-05-24_hypothesis_validation/F1_shape/f1_shape_baseline.json"
OUT_SVG = REPO / "data/analysis/2026-05-24_hypothesis_validation/F1_shape/f1_25d_topology.svg"
BUILD_BAT = REPO / "tools/build_atlas_thumbnail.py"
TMP_BASE = Path("/tmp/f1_25d_base.svg")

# Panel + page layout (mm)
PANEL_W = 165.0
PANEL_H = 130.0
GAP = 8.0
MARGIN_X = 10.0
HEADER_H = 36.0
FOOTER_H = 30.0
TOTAL_W = PANEL_W * 2 + GAP + MARGIN_X * 2
TOTAL_H = HEADER_H + PANEL_H + FOOTER_H

LEFT_PANEL_X = MARGIN_X
RIGHT_PANEL_X = MARGIN_X + PANEL_W + GAP
PANEL_Y = HEADER_H

# Projection params (must mirror build_atlas_thumbnail.py exactly)
RADIUS_M = 1000.0
PAD = 2.0
HEIGHT_EXAG = 1.6
ISO_COS = math.cos(math.radians(30))
ISO_SIN = math.sin(math.radians(30))

# Palette (matches poster_map_baseline.svg / build_atlas_thumbnail constants)
BG = "#FCFAF6"
INK = "#1B1F2A"
PINK = "#FF4D8F"
GREY_NEUTRAL = "#9E988C"
GREY_DEEP = "#6B6359"
LABEL_BOX_BG = "#FFFFFF"


# ------------------------------------------------------------------ helpers

def gen_base() -> str:
    """Call build_atlas_thumbnail.py to produce a clean 2.5d base SVG."""
    cmd = [
        str(REPO / ".venv/bin/python3"),
        str(BUILD_BAT),
        "--atlas", str(ATLAS_PATH),
        "--out", str(TMP_BASE),
        "--style", "2.5d",
        "--size-mm", f"{int(PANEL_W)}:{int(PANEL_H)}",
        "--radius-m", str(int(RADIUS_M)),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return TMP_BASE.read_text(encoding="utf-8")


def extract_base_inner(base_svg: str) -> str:
    """Strip outer <svg> wrapper + chrome so we can re-embed body."""
    body = re.sub(r"<\?xml[^?]*\?>\s*", "", base_svg)
    m = re.search(r"<svg[^>]*>(.*)</svg>\s*$", body, re.DOTALL)
    if not m:
        raise RuntimeError("could not parse base svg")
    inner = m.group(1)
    # Strip the auto-emitted 1000m ellipse ring (we draw our own subtler one)
    inner = re.sub(r'<ellipse[^>]*stroke-dasharray[^>]*/>', "", inner)
    # Strip auto dwell heatmap grid (we don't want it under our data circles)
    inner = re.sub(r'<g[^>]*id="dwell-grid"[^>]*>.*?</g>', "", inner, flags=re.DOTALL)
    # Strip ALL <text> nodes from base (legend / scale-bar / "1000m radius" /
    # "Lane Cove · 2070 buildings (no position data)" footer — our parent
    # composite adds its own typography).
    inner = re.sub(r'<text[^>]*>.*?</text>', "", inner, flags=re.DOTALL)
    # Strip scale bar / legend rects emitted by build_atlas_thumbnail (the
    # script labels them with id="scale-bar" / id="legend"; if missing, the
    # text-strip above already handles label cleanup).
    inner = re.sub(r'<g[^>]*id="scale-bar"[^>]*>.*?</g>', "", inner, flags=re.DOTALL)
    inner = re.sub(r'<g[^>]*id="legend"[^>]*>.*?</g>', "", inner, flags=re.DOTALL)
    return inner


def load_atlas() -> dict:
    return json.loads(ATLAS_PATH.read_text(encoding="utf-8"))


def hub_center(atlas: dict) -> tuple[float, float]:
    bldgs = atlas["buildings"]
    hub = bldgs.get("lane_cove_community_hub")
    if hub:
        vs = hub["polygon"]["vertices"]
        return (
            sum(v["x"] for v in vs) / len(vs),
            sum(v["y"] for v in vs) / len(vs),
        )
    # fallback: mean of all building centroids
    sx = sy = 0.0
    n = 0
    for b in bldgs.values():
        vs = b.get("polygon", {}).get("vertices", [])
        if not vs:
            continue
        sx += sum(v["x"] for v in vs) / len(vs)
        sy += sum(v["y"] for v in vs) / len(vs)
        n += 1
    return (sx / n, sy / n) if n else (0.0, 0.0)


def make_proj(center: tuple[float, float]):
    """Return proj_iso(x, y, z=0) matching build_atlas_thumbnail.py exactly."""
    iso_diag_w = 2 * RADIUS_M * ISO_COS * 2
    iso_diag_h = 2 * RADIUS_M * ISO_SIN * 2 + 60 * HEIGHT_EXAG
    scale = min((PANEL_W - 2 * PAD) / iso_diag_w,
                (PANEL_H - 2 * PAD) / iso_diag_h)
    cx, cy = center

    def proj_iso(x: float, y: float, z: float = 0.0) -> tuple[float, float]:
        dx = x - cx
        dy = y - cy
        sx = PANEL_W / 2 + (dx - dy) * ISO_COS * scale
        sy = PANEL_H / 2 + (dx + dy) * ISO_SIN * scale * (-1)
        sy -= z * scale * HEIGHT_EXAG
        return sx, sy

    return proj_iso, scale


def loc_centroid_index(atlas: dict) -> dict[str, tuple[float, float, str]]:
    """Map location_id -> (x, y, type)."""
    out: dict[str, tuple[float, float, str]] = {}
    for bid, b in atlas["buildings"].items():
        vs = b.get("polygon", {}).get("vertices", [])
        if not vs:
            continue
        x = sum(v["x"] for v in vs) / len(vs)
        y = sum(v["y"] for v in vs) / len(vs)
        out[bid] = (x, y, b.get("building_type") or "")
    out_areas = atlas.get("outdoor_areas", {})
    items = out_areas.items() if isinstance(out_areas, dict) else [
        (o["id"], o) for o in out_areas
    ]
    for oid, o in items:
        vs = o.get("polygon", {}).get("vertices", [])
        if not vs:
            continue
        x = sum(v["x"] for v in vs) / len(vs)
        y = sum(v["y"] for v in vs) / len(vs)
        out[oid] = (x, y, o.get("area_type") or "")
    return out


# ------------------------------------------------------------------ encoding

def rate_to_color(rate: float) -> str:
    """0% -> deep grey, ~20%+ -> saturated pink."""
    t = max(0.0, min(rate / 0.22, 1.0))
    grey = (0x9E, 0x98, 0x8C)
    pink = (0xFF, 0x4D, 0x8F)
    r = int(grey[0] + (pink[0] - grey[0]) * t)
    g = int(grey[1] + (pink[1] - grey[1]) * t)
    b = int(grey[2] + (pink[2] - grey[2]) * t)
    return f"#{r:02X}{g:02X}{b:02X}"


def vol_to_radius(vol: int, vol_p95: int,
                  r_min: float = 0.35, r_max: float = 6.0) -> float:
    """sqrt scale; saturate at p95 to keep mega-streets from dominating."""
    if vol <= 0:
        return 0.0
    t = min(math.sqrt(vol / vol_p95), 1.4)
    return r_min + (r_max - r_min) * (t / 1.4)


# Lift data circles to roof-level of the average building so they visually
# anchor inside the iso city cluster rather than floating at ground (which
# in 2.5d projection ends up BELOW the visible building mass).
CIRCLE_LIFT_M = 10.0


def build_panel_circles(f1_locs: list[dict],
                        loc_idx: dict,
                        proj,
                        value_key: str,
                        mode: str,
                        min_value: int) -> str:
    """Render circles for one panel.

    min_value filters out long-tail noise. ~80-100 keeps urban scale meaningful
    locations only.
    """
    valid = [l for l in f1_locs
             if loc_idx.get(l["loc"]) and l[value_key] >= min_value]
    if not valid:
        return ""
    vol_p95 = sorted(l[value_key] for l in valid)[int(len(valid) * 0.95)]

    # Draw large circles first so small ones layer on top
    valid.sort(key=lambda x: -x[value_key])

    parts = []
    for l in valid:
        x, y, _ = loc_idx[l["loc"]]
        sx, sy = proj(x, y, z=CIRCLE_LIFT_M)
        if sx < -3 or sx > PANEL_W + 3 or sy < -3 or sy > PANEL_H + 3:
            continue
        r = vol_to_radius(l[value_key], vol_p95)
        if r < 0.4:
            continue
        if mode == "neutral":
            fill = "#5F584F"
            alpha = 0.32
            stroke = "#2E2922"
            stroke_op = 0.50
        else:  # by_rate
            fill = rate_to_color(l["rate"])
            alpha = 0.50 + 0.28 * min(l["rate"] / 0.22, 1.0)
            stroke = fill
            stroke_op = 0.90
        parts.append(
            f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{r:.2f}" '
            f'fill="{fill}" fill-opacity="{alpha:.2f}" '
            f'stroke="{stroke}" stroke-opacity="{stroke_op:.2f}" '
            f'stroke-width="0.18"/>'
        )
    return "\n".join(parts)


# ------------------------------------------------------------------ callouts

# Each callout: (loc_id, label, sub_line, anchor_pos)
# anchor_pos is the label-box position relative to panel coords (mm).
# We hand-tune anchors to keep leader lines clean and avoid overlapping the
# busiest map regions.
# Each callout: box_pos is in panel-local mm; right panel only.
CALLOUTS = [
    {
        "loc_name_match": "Saint Michael's Catholic Church",
        "label": "Saint Michael's Catholic Church",
        "sub": "21% noticed · n = 66 co-presences",
        "kind": "island",
        "box_pos": (3, 18),
        "box_w": 58,
    },
    {
        "loc_name_match": "PLC Sydney Preschool",
        "label": "PLC Sydney Preschool",
        "sub": "21% noticed · n = 124",
        "kind": "island",
        "box_pos": (3, 38),
        "box_w": 58,
    },
    {
        "loc_name_match": "Finlayson Street",
        "label": "Finlayson Street",
        "sub": "1.1% noticed · n = 2,374 co-presences",
        "kind": "canyon",
        "box_pos": (96, 92),
        "box_w": 67,
    },
    {
        "loc_name_match": "Coxs Lane",
        "label": "Coxs Lane",
        "sub": "5.3% noticed · n = 5,056 (busiest street)",
        "kind": "canyon",
        "box_pos": (96, 113),
        "box_w": 67,
    },
]


def resolve_callout(c: dict, f1_locs: list[dict], loc_idx: dict
                    ) -> tuple[float, float] | None:
    """Find atlas centroid for a callout target."""
    if "loc" in c:
        if c["loc"] in loc_idx:
            return loc_idx[c["loc"]][:2]
    if "loc_name_match" in c:
        # Find the row in f1 data whose name contains the match
        for l in f1_locs:
            if c["loc_name_match"].lower() in l["name"].lower():
                if l["loc"] in loc_idx:
                    return loc_idx[l["loc"]][:2]
    return None


def build_callouts(f1_locs: list[dict], loc_idx: dict, proj) -> str:
    """Render leader-line + white box callouts."""
    parts = []
    for c in CALLOUTS:
        coord = resolve_callout(c, f1_locs, loc_idx)
        if coord is None:
            print(f"[f1_25d] WARN: callout {c.get('label')} not resolved")
            continue
        x, y = coord
        # Lift marker to same height as data circles for visual consistency
        sx, sy = proj(x, y, z=CIRCLE_LIFT_M)
        bx, by = c["box_pos"]
        bw = c["box_w"]
        bh = 9.5

        marker_color = PINK if c["kind"] == "island" else INK
        accent_label = "AWARENESS ISLAND" if c["kind"] == "island" else "BLINDNESS CANYON"
        accent_col = PINK if c["kind"] == "island" else INK

        # Leader line emerges from box edge facing marker
        box_cx = bx + bw / 2
        leader_box_x = (bx + bw) if sx > box_cx else bx
        leader_box_y = by + bh / 2

        # Marker layer: white halo first (visibility on busy backgrounds),
        # then the coloured ring on top.
        parts.append(
            f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="3.4" '
            f'fill="none" stroke="{BG}" stroke-width="1.6" '
            f'stroke-opacity="0.95"/>'
        )
        parts.append(
            f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="3.0" '
            f'fill="none" stroke="{marker_color}" stroke-width="0.65" '
            f'stroke-opacity="1.0"/>'
        )
        # Solid dot in center of marker
        parts.append(
            f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.55" '
            f'fill="{marker_color}"/>'
        )
        # Leader line — slight stroke-width + white halo for legibility
        parts.append(
            f'<path d="M {leader_box_x:.2f} {leader_box_y:.2f} '
            f'L {sx:.2f} {sy:.2f}" '
            f'stroke="{BG}" stroke-width="1.0" stroke-opacity="0.85" fill="none"/>'
        )
        parts.append(
            f'<path d="M {leader_box_x:.2f} {leader_box_y:.2f} '
            f'L {sx:.2f} {sy:.2f}" '
            f'stroke="{marker_color}" stroke-width="0.4" '
            f'stroke-opacity="1.0" fill="none"/>'
        )
        # White rounded box
        parts.append(
            f'<rect x="{bx:.2f}" y="{by:.2f}" width="{bw:.2f}" height="{bh:.2f}" '
            f'rx="1.1" ry="1.1" fill="{LABEL_BOX_BG}" '
            f'stroke="{marker_color}" stroke-width="0.42" stroke-opacity="0.85"/>'
        )
        # Tiny accent label
        parts.append(
            f'<text x="{bx + 2.2:.2f}" y="{by + 3.3:.2f}" '
            f'font-family="Inter, Helvetica Neue, sans-serif" '
            f'font-size="1.95" font-weight="700" letter-spacing="0.2" '
            f'fill="{accent_col}">{accent_label}</text>'
        )
        parts.append(
            f'<text x="{bx + 2.2:.2f}" y="{by + 6.1:.2f}" '
            f'font-family="Inter, Helvetica Neue, sans-serif" '
            f'font-size="2.7" font-weight="700" fill="{INK}">'
            f'{c["label"]}</text>'
        )
        parts.append(
            f'<text x="{bx + 2.2:.2f}" y="{by + 8.5:.2f}" '
            f'font-family="Inter, Helvetica Neue, sans-serif" '
            f'font-size="2.2" fill="#555">'
            f'{c["sub"]}</text>'
        )
    return "\n".join(parts)


# ------------------------------------------------------------------ assemble

def assemble(base_inner: str,
             left_circles: str,
             right_circles: str,
             callouts: str) -> str:
    """Compose the final dual-panel SVG.

    Layering: muted base (opacity 0.28) → data circles (full saturation) →
    callouts on top. clipPath crops base overflow to panel rect.
    """
    header = f"""
<text x="{TOTAL_W/2:.2f}" y="13.5" text-anchor="middle"
      font-family="Inter, Helvetica Neue, sans-serif"
      font-size="6.6" font-weight="800" fill="{INK}" letter-spacing="-0.18">
  Finding 1 · The shape of default blindness
</text>
<text x="{TOTAL_W/2:.2f}" y="19.8" text-anchor="middle"
      font-family="Inter, Helvetica Neue, sans-serif"
      font-size="3.0" font-weight="500" fill="#5a5a5a" letter-spacing="0.04">
  Lane Cove · 1,000 residents · 14 days · 2 seeds pooled · no app condition
</text>

<text x="{LEFT_PANEL_X + 2:.2f}" y="30.5" text-anchor="start"
      font-family="Inter, Helvetica Neue, sans-serif"
      font-size="9.5" font-weight="800" fill="{GREY_DEEP}" letter-spacing="-0.25">
  Where they meet
</text>
<text x="{LEFT_PANEL_X + 2:.2f}" y="34.5" text-anchor="start"
      font-family="Inter, Helvetica Neue, sans-serif"
      font-size="2.65" font-weight="500" fill="#666" letter-spacing="0.02">
  ~115,000 physical co-presences · circle size = encounter volume
</text>

<text x="{RIGHT_PANEL_X + 2:.2f}" y="30.5" text-anchor="start"
      font-family="Inter, Helvetica Neue, sans-serif"
      font-size="9.5" font-weight="800" fill="{PINK}" letter-spacing="-0.25">
  Where they notice
</text>
<text x="{RIGHT_PANEL_X + 2:.2f}" y="34.5" text-anchor="start"
      font-family="Inter, Helvetica Neue, sans-serif"
      font-size="2.65" font-weight="500" fill="#666" letter-spacing="0.02">
  ~13,500 actually seen (11.6%) · circle size = noticed volume, colour = notice rate
</text>
"""

    footer_y = PANEL_Y + PANEL_H + 11.5
    footer = f"""
<text x="{TOTAL_W/2:.2f}" y="{footer_y:.2f}" text-anchor="middle"
      font-family="Charter, Georgia, serif"
      font-size="4.8" font-style="italic" font-weight="400" fill="{INK}">
  Same fortnight. Same neighbourhood. The street pulls the crowd; only homes catch the attention.
</text>
<text x="{TOTAL_W/2:.2f}" y="{footer_y + 6.8:.2f}" text-anchor="middle"
      font-family="Inter, Helvetica Neue, sans-serif"
      font-size="2.7" font-weight="500" fill="#666">
  Residential 19% · worship 17% · cafe 13% · street 7%  ·  rate gap on the same physical surface = 1 : 6
</text>
<text x="{TOTAL_W/2:.2f}" y="{footer_y + 12.0:.2f}" text-anchor="middle"
      font-family="Inter, Helvetica Neue, sans-serif"
      font-size="2.0" fill="#888" letter-spacing="0.05">
  Top ~70 locations by volume per panel · n ≥ 500 co-presences (left) · ≥ 40 noticed (right) · 2 seeds pooled
</text>
"""

    # Left panel — size legend, bottom-left inside panel area
    lx = LEFT_PANEL_X + 4
    ly = PANEL_Y + PANEL_H - 16
    legend_left = f"""
<g font-family="Inter, Helvetica Neue, sans-serif" font-size="2.2" fill="#444">
  <text x="{lx:.2f}" y="{ly:.2f}" font-weight="700"
        font-size="2.3" letter-spacing="0.14" fill="#444">CIRCLE SIZE</text>
  <circle cx="{lx + 2.0:.2f}" cy="{ly + 5.5:.2f}" r="0.9"
          fill="#7A736A" fill-opacity="0.35" stroke="#4D4640"
          stroke-opacity="0.5" stroke-width="0.15"/>
  <circle cx="{lx + 9.0:.2f}" cy="{ly + 5.5:.2f}" r="2.3"
          fill="#7A736A" fill-opacity="0.35" stroke="#4D4640"
          stroke-opacity="0.5" stroke-width="0.15"/>
  <circle cx="{lx + 18.5:.2f}" cy="{ly + 5.5:.2f}" r="4.5"
          fill="#7A736A" fill-opacity="0.35" stroke="#4D4640"
          stroke-opacity="0.5" stroke-width="0.15"/>
  <text x="{lx + 2.0:.2f}" y="{ly + 11.3:.2f}" text-anchor="middle">100</text>
  <text x="{lx + 9.0:.2f}" y="{ly + 11.3:.2f}" text-anchor="middle">1,000</text>
  <text x="{lx + 18.5:.2f}" y="{ly + 11.3:.2f}" text-anchor="middle">5,000+</text>
  <text x="{lx + 2.0:.2f}" y="{ly + 14.0:.2f}" font-size="1.8" fill="#888"
        text-anchor="start">co-presences</text>
</g>
"""
    # Right panel — colour ramp legend
    rx = RIGHT_PANEL_X + 4
    ry = PANEL_Y + PANEL_H - 16
    legend_right = f"""
<defs>
  <linearGradient id="rateRamp" x1="0%" x2="100%" y1="0%" y2="0%">
    <stop offset="0%" stop-color="{GREY_NEUTRAL}"/>
    <stop offset="50%" stop-color="#D17087"/>
    <stop offset="100%" stop-color="{PINK}"/>
  </linearGradient>
  <clipPath id="leftPanelClip">
    <rect x="0" y="0" width="{PANEL_W:.2f}" height="{PANEL_H:.2f}"/>
  </clipPath>
  <clipPath id="rightPanelClip">
    <rect x="0" y="0" width="{PANEL_W:.2f}" height="{PANEL_H:.2f}"/>
  </clipPath>
</defs>
<g font-family="Inter, Helvetica Neue, sans-serif" font-size="2.2" fill="#444">
  <text x="{rx:.2f}" y="{ry:.2f}" font-weight="700"
        font-size="2.3" letter-spacing="0.14">NOTICE RATE</text>
  <rect x="{rx:.2f}" y="{ry + 3.5:.2f}" width="26" height="2.6"
        fill="url(#rateRamp)" rx="0.3"/>
  <text x="{rx:.2f}" y="{ry + 9.5:.2f}" text-anchor="start">0%</text>
  <text x="{rx + 13:.2f}" y="{ry + 9.5:.2f}" text-anchor="middle">11%</text>
  <text x="{rx + 26:.2f}" y="{ry + 9.5:.2f}" text-anchor="end">22%+</text>
  <text x="{rx:.2f}" y="{ry + 14.0:.2f}" font-size="1.8" fill="#888"
        text-anchor="start">noticed / co-presences at this location</text>
</g>
"""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:xlink="http://www.w3.org/1999/xlink"
     width="{TOTAL_W:.1f}mm" height="{TOTAL_H:.1f}mm"
     viewBox="0 0 {TOTAL_W:.2f} {TOTAL_H:.2f}"
     preserveAspectRatio="xMidYMid meet">
  <rect width="100%" height="100%" fill="{BG}"/>

  {legend_right}
  {header}

  <!-- LEFT PANEL : WHERE THEY MEET -->
  <svg x="{LEFT_PANEL_X:.2f}" y="{PANEL_Y:.2f}"
       width="{PANEL_W:.2f}" height="{PANEL_H:.2f}"
       viewBox="0 0 {PANEL_W:.2f} {PANEL_H:.2f}"
       overflow="hidden" preserveAspectRatio="none">
    <g clip-path="url(#leftPanelClip)">
      <g opacity="0.36">
        {base_inner}
      </g>
      <g id="f1-left-circles">
        {left_circles}
      </g>
    </g>
  </svg>

  <!-- RIGHT PANEL : WHERE THEY NOTICE -->
  <svg x="{RIGHT_PANEL_X:.2f}" y="{PANEL_Y:.2f}"
       width="{PANEL_W:.2f}" height="{PANEL_H:.2f}"
       viewBox="0 0 {PANEL_W:.2f} {PANEL_H:.2f}"
       overflow="hidden" preserveAspectRatio="none">
    <g clip-path="url(#rightPanelClip)">
      <g opacity="0.36">
        {base_inner}
      </g>
      <g id="f1-right-circles">
        {right_circles}
      </g>
      <g id="f1-callouts">
        {callouts}
      </g>
    </g>
  </svg>

  {legend_left}
  {footer}
</svg>
"""


# ------------------------------------------------------------------ main

def main() -> int:
    print("[f1_25d] generating clean 2.5d base...")
    base_svg = gen_base()
    base_inner = extract_base_inner(base_svg)
    print(f"[f1_25d] base inner length: {len(base_inner):,} chars")

    print("[f1_25d] loading atlas + computing projection...")
    atlas = load_atlas()
    center = hub_center(atlas)
    proj, scale = make_proj(center)
    loc_idx = loc_centroid_index(atlas)
    print(f"[f1_25d] center=({center[0]:.0f},{center[1]:.0f}) scale={scale:.4f}")

    print("[f1_25d] loading F1 data...")
    f1 = json.loads(F1_JSON.read_text(encoding="utf-8"))
    f1_locs = f1["all_location_rates"]
    print(f"[f1_25d] {len(f1_locs)} F1 locations")

    left = build_panel_circles(f1_locs, loc_idx, proj,
                                value_key="enc", mode="neutral",
                                min_value=500)
    right = build_panel_circles(f1_locs, loc_idx, proj,
                                 value_key="noticed", mode="by_rate",
                                 min_value=40)
    n_left = sum(1 for l in f1_locs if l["enc"] >= 500)
    n_right = sum(1 for l in f1_locs if l["noticed"] >= 40)
    print(f"[f1_25d] left circles: {n_left}, right circles: {n_right}")
    callouts = build_callouts(f1_locs, loc_idx, proj)

    print("[f1_25d] assembling composite svg...")
    svg = assemble(base_inner, left, right, callouts)
    OUT_SVG.parent.mkdir(parents=True, exist_ok=True)
    OUT_SVG.write_text(svg, encoding="utf-8")
    print(f"[f1_25d] wrote {OUT_SVG} ({OUT_SVG.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
