"""F1 v4 · Donut topology — single 2.5D panel hero figure.

Each location is rendered as a DONUT GLYPH:
  - Outer faded grey disk:  encounter volume (how many people walked past)
  - Inner saturated pink disk: noticed volume (how many actually saw)
  - Visible grey halo BETWEEN them = the blindness gap, made spatial

Geometric invariant: inner_r / outer_r = sqrt(notice_rate) → inner AREA /
outer AREA = notice_rate.  A 100%-rate location is a solid pink puck;
a 1%-rate canyon is a near-empty grey halo with a tiny pink core.

Base map: re-use tools/build_atlas_thumbnail.py (--style 2.5d) so the iso
projection matches docs/poster_map_baseline.svg.

Output: data/analysis/.../F1_shape/f1_25d_donut.svg
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
OUT_SVG = REPO / "data/analysis/2026-05-24_hypothesis_validation/F1_shape/f1_25d_donut.svg"
BUILD_BAT = REPO / "tools/build_atlas_thumbnail.py"
TMP_BASE = Path("/tmp/f1_donut_base.svg")

# ------------------------------------------------------------------ layout
TOTAL_W = 360.0
HEADER_H = 36.0
MAP_H = 158.0
READ_ME_H = 42.0  # horizontal explainer strip below map
FOOTER_H = 28.0
TOTAL_H = HEADER_H + MAP_H + READ_ME_H + FOOTER_H
MARGIN_X = 10.0
MAP_W = TOTAL_W - 2 * MARGIN_X
MAP_X = MARGIN_X
MAP_Y = HEADER_H
READ_ME_Y = MAP_Y + MAP_H
FOOTER_Y_BASE = READ_ME_Y + READ_ME_H

# Projection params (must mirror build_atlas_thumbnail.py exactly)
RADIUS_M = 1000.0
PAD = 2.0
HEIGHT_EXAG = 1.6
ISO_COS = math.cos(math.radians(30))
ISO_SIN = math.sin(math.radians(30))
GLYPH_LIFT_M = 8.0

# Palette
BG = "#FCFAF6"
INK = "#1B1F2A"
PINK = "#FF4D8F"
PINK_DEEP = "#C8245E"
GREY_OUTER = "#9E988C"
GREY_OUTER_STROKE = "#5F584F"
LABEL_BOX_BG = "#FFFFFF"

# Donut geometry
OUTER_R_MIN = 0.95   # mm — smallest islands stay visible
OUTER_R_MAX = 7.2    # mm — cap on busiest streets so they don't dominate
INNER_R_MIN = 0.25   # mm — even tiny noticed pools stay visible

# Filter: keep locations with at least N encounters (skip long-tail noise).
# Tuned so glyph density is readable at the hero scale (~340mm × 160mm map).
MIN_ENCOUNTERS = 200


# ------------------------------------------------------------------ base SVG

def gen_base() -> str:
    """Generate a clean 2.5d base via build_atlas_thumbnail.py."""
    cmd = [
        str(REPO / ".venv/bin/python3"),
        str(BUILD_BAT),
        "--atlas", str(ATLAS_PATH),
        "--out", str(TMP_BASE),
        "--style", "2.5d",
        "--size-mm", f"{int(MAP_W)}:{int(MAP_H)}",
        "--radius-m", str(int(RADIUS_M)),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return TMP_BASE.read_text(encoding="utf-8")


def extract_base_inner(base_svg: str) -> str:
    """Strip outer <svg> + auto chrome (text labels, ellipse ring, dwell grid)."""
    body = re.sub(r"<\?xml[^?]*\?>\s*", "", base_svg)
    m = re.search(r"<svg[^>]*>(.*)</svg>\s*$", body, re.DOTALL)
    if not m:
        raise RuntimeError("could not parse base svg")
    inner = m.group(1)
    inner = re.sub(r'<ellipse[^>]*stroke-dasharray[^>]*/>', "", inner)
    inner = re.sub(r'<g[^>]*id="dwell-grid"[^>]*>.*?</g>', "", inner, flags=re.DOTALL)
    inner = re.sub(r'<text[^>]*>.*?</text>', "", inner, flags=re.DOTALL)
    inner = re.sub(r'<g[^>]*id="scale-bar"[^>]*>.*?</g>', "", inner, flags=re.DOTALL)
    inner = re.sub(r'<g[^>]*id="legend"[^>]*>.*?</g>', "", inner, flags=re.DOTALL)
    return inner


# ------------------------------------------------------------------ atlas

def load_atlas() -> dict:
    return json.loads(ATLAS_PATH.read_text(encoding="utf-8"))


def hub_center(atlas: dict) -> tuple[float, float]:
    bldgs = atlas["buildings"]
    hub = bldgs.get("lane_cove_community_hub")
    if hub:
        vs = hub["polygon"]["vertices"]
        return (sum(v["x"] for v in vs) / len(vs),
                sum(v["y"] for v in vs) / len(vs))
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
    iso_diag_w = 2 * RADIUS_M * ISO_COS * 2
    iso_diag_h = 2 * RADIUS_M * ISO_SIN * 2 + 60 * HEIGHT_EXAG
    scale = min((MAP_W - 2 * PAD) / iso_diag_w,
                (MAP_H - 2 * PAD) / iso_diag_h)
    cx, cy = center

    def proj_iso(x: float, y: float, z: float = 0.0) -> tuple[float, float]:
        dx = x - cx
        dy = y - cy
        sx = MAP_W / 2 + (dx - dy) * ISO_COS * scale
        sy = MAP_H / 2 + (dx + dy) * ISO_SIN * scale * (-1)
        sy -= z * scale * HEIGHT_EXAG
        return sx, sy

    return proj_iso, scale


def loc_centroid_index(atlas: dict) -> dict[str, tuple[float, float, str]]:
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


# ------------------------------------------------------------------ donuts

def outer_radius(enc: int, enc_p95: int) -> float:
    """sqrt scaling, capped at p95 so megastreets don't dominate."""
    if enc <= 0:
        return 0.0
    t = min(math.sqrt(enc / enc_p95), 1.5)
    return OUTER_R_MIN + (OUTER_R_MAX - OUTER_R_MIN) * (t / 1.5)


def inner_radius(noticed: int, enc: int, outer_r: float) -> float:
    """Inner area / outer area = noticed / enc → inner_r = outer_r * sqrt(rate)."""
    if enc <= 0 or noticed <= 0:
        return 0.0
    rate = noticed / enc
    r = outer_r * math.sqrt(rate)
    if r < INNER_R_MIN:
        return 0.0  # too small to render meaningfully
    return r


def render_donut(sx: float, sy: float, outer_r: float, inner_r: float,
                 highlight: bool = False) -> str:
    """One glyph = outer faded disk + inner saturated disk."""
    parts = []
    # Outer envelope: filled faded grey + thin stroke (encounter volume)
    parts.append(
        f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{outer_r:.2f}" '
        f'fill="{GREY_OUTER}" fill-opacity="0.22" '
        f'stroke="{GREY_OUTER_STROKE}" stroke-opacity="0.55" '
        f'stroke-width="0.18"/>'
    )
    # Inner core: solid pink with darker stroke (noticed volume)
    if inner_r > 0:
        op = 0.96 if highlight else 0.90
        parts.append(
            f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{inner_r:.2f}" '
            f'fill="{PINK}" fill-opacity="{op:.2f}" '
            f'stroke="{PINK_DEEP}" stroke-opacity="0.85" '
            f'stroke-width="0.18"/>'
        )
    return "".join(parts)


def build_donuts(f1_locs: list[dict], loc_idx: dict, proj,
                 callout_loc_ids: set[str]) -> tuple[str, dict]:
    """Render all donut glyphs; return (svg_string, per-glyph-info-dict)."""
    valid = [l for l in f1_locs
             if loc_idx.get(l["loc"]) and l["enc"] >= MIN_ENCOUNTERS]
    if not valid:
        return "", {}
    enc_p95 = sorted(l["enc"] for l in valid)[int(len(valid) * 0.95)]

    # Draw largest first so smaller glyphs layer above
    valid.sort(key=lambda x: -x["enc"])

    parts = []
    info = {}
    for l in valid:
        x, y, _ = loc_idx[l["loc"]]
        sx, sy = proj(x, y, z=GLYPH_LIFT_M)
        if sx < -3 or sx > MAP_W + 3 or sy < -3 or sy > MAP_H + 3:
            continue
        outer_r = outer_radius(l["enc"], enc_p95)
        inner_r = inner_radius(l["noticed"], l["enc"], outer_r)
        is_callout = l["loc"] in callout_loc_ids
        parts.append(render_donut(sx, sy, outer_r, inner_r,
                                  highlight=is_callout))
        info[l["loc"]] = {"sx": sx, "sy": sy, "outer_r": outer_r,
                          "inner_r": inner_r, "rate": l.get("rate"),
                          "enc": l["enc"], "noticed": l["noticed"]}
    return "\n".join(parts), info


# ------------------------------------------------------------------ callouts

CALLOUTS = [
    # 3 awareness islands (high rate, small volume — homes / worship / cafe)
    {
        "name_match": "Saint Michael's Catholic Church",
        "label": "Saint Michael's Catholic Church",
        "sub": "21% noticed · 66 co-presences",
        "kind": "island",
        "box_pos": (2, 22),
        "box_w": 60,
    },
    {
        "name_match": "PLC Sydney Preschool",
        "label": "PLC Sydney Preschool",
        "sub": "21% noticed · 124 co-presences",
        "kind": "island",
        "box_pos": (2, 44),
        "box_w": 60,
    },
    {
        "name_match": "Grill'd",
        "label": "Grill'd (restaurant)",
        "sub": "21% noticed · 104 co-presences",
        "kind": "island",
        "box_pos": (MAP_W - 64, 22),
        "box_w": 62,
    },
    # 3 blindness canyons (low rate, huge volume — main streets)
    {
        "name_match": "Coxs Lane",
        "label": "Coxs Lane",
        "sub": "5.3% noticed · 5,056 co-presences (busiest street)",
        "kind": "canyon",
        "box_pos": (MAP_W - 92, MAP_H - 32),
        "box_w": 90,
    },
    {
        "name_match": "Karilla Avenue",
        "label": "Karilla Avenue",
        "sub": "2.0% noticed · 3,570 co-presences",
        "kind": "canyon",
        "box_pos": (MAP_W - 92, MAP_H - 14),
        "box_w": 90,
    },
    {
        "name_match": "Finlayson Street",
        "label": "Finlayson Street",
        "sub": "1.1% noticed · 2,374 co-presences",
        "kind": "canyon",
        "box_pos": (2, MAP_H - 14),
        "box_w": 90,
    },
]


def resolve_callout(c: dict, f1_locs: list[dict], loc_idx: dict
                    ) -> tuple[str, tuple[float, float]] | None:
    needle = c["name_match"].lower()
    for l in f1_locs:
        if needle in l["name"].lower():
            if l["loc"] in loc_idx:
                return l["loc"], loc_idx[l["loc"]][:2]
    return None


def build_callouts(f1_locs: list[dict], loc_idx: dict, proj,
                   glyph_info: dict) -> tuple[str, set[str]]:
    parts = []
    callout_ids = set()
    for c in CALLOUTS:
        r = resolve_callout(c, f1_locs, loc_idx)
        if r is None:
            print(f"[f1_donut] WARN: callout {c['label']} not resolved")
            continue
        loc_id, (x, y) = r
        sx, sy = proj(x, y, z=GLYPH_LIFT_M)
        callout_ids.add(loc_id)
        bx, by = c["box_pos"]
        bw = c["box_w"]
        bh = 10.0

        accent = PINK if c["kind"] == "island" else INK
        accent_label = ("AWARENESS ISLAND" if c["kind"] == "island"
                        else "BLINDNESS CANYON")

        box_cx = bx + bw / 2
        leader_box_x = (bx + bw) if sx > box_cx else bx
        leader_box_y = by + bh / 2

        # Marker: white halo + colored ring + center dot
        parts.append(
            f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="3.6" '
            f'fill="none" stroke="{BG}" stroke-width="1.7" '
            f'stroke-opacity="0.95"/>'
        )
        parts.append(
            f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="3.2" '
            f'fill="none" stroke="{accent}" stroke-width="0.7" '
            f'stroke-opacity="1.0"/>'
        )
        parts.append(
            f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.6" '
            f'fill="{accent}"/>'
        )
        # Leader line with white halo
        parts.append(
            f'<path d="M {leader_box_x:.2f} {leader_box_y:.2f} '
            f'L {sx:.2f} {sy:.2f}" '
            f'stroke="{BG}" stroke-width="1.1" stroke-opacity="0.85" fill="none"/>'
        )
        parts.append(
            f'<path d="M {leader_box_x:.2f} {leader_box_y:.2f} '
            f'L {sx:.2f} {sy:.2f}" '
            f'stroke="{accent}" stroke-width="0.42" '
            f'stroke-opacity="1.0" fill="none"/>'
        )
        # White box with accent border
        parts.append(
            f'<rect x="{bx:.2f}" y="{by:.2f}" width="{bw:.2f}" height="{bh:.2f}" '
            f'rx="1.2" ry="1.2" fill="{LABEL_BOX_BG}" '
            f'stroke="{accent}" stroke-width="0.45" stroke-opacity="0.85"/>'
        )
        parts.append(
            f'<text x="{bx + 2.3:.2f}" y="{by + 3.5:.2f}" '
            f'font-family="Inter, Helvetica Neue, sans-serif" '
            f'font-size="2.1" font-weight="700" letter-spacing="0.22" '
            f'fill="{accent}">{accent_label}</text>'
        )
        parts.append(
            f'<text x="{bx + 2.3:.2f}" y="{by + 6.4:.2f}" '
            f'font-family="Inter, Helvetica Neue, sans-serif" '
            f'font-size="2.85" font-weight="700" fill="{INK}">'
            f'{c["label"]}</text>'
        )
        parts.append(
            f'<text x="{bx + 2.3:.2f}" y="{by + 8.9:.2f}" '
            f'font-family="Inter, Helvetica Neue, sans-serif" '
            f'font-size="2.25" fill="#555">'
            f'{c["sub"]}</text>'
        )
    return "\n".join(parts), callout_ids


# ------------------------------------------------------------------ legend / inset

def build_read_me_strip(x0: float, y0: float, w: float, h: float) -> str:
    """A horizontal explainer strip placed below the map.

    Layout: [TITLE bar] | [annotated example donut] | [3 archetypes]
    Placed in PARENT svg coords so it lives outside the map clip and stays
    visible regardless of map content density.
    """
    parts = []

    # Top thin pink divider + tiny tab label (replaces a heavy card border)
    parts.append(
        f'<line x1="{x0:.2f}" y1="{y0:.2f}" x2="{x0 + w:.2f}" y2="{y0:.2f}" '
        f'stroke="{PINK}" stroke-width="0.5" stroke-opacity="0.7"/>'
    )
    parts.append(
        f'<text x="{x0:.2f}" y="{y0 + 3.6:.2f}" '
        f'font-family="Inter, Helvetica Neue, sans-serif" '
        f'font-size="2.6" font-weight="800" letter-spacing="0.28" '
        f'fill="{PINK_DEEP}">HOW TO READ THIS MAP</text>'
    )

    # Content y baseline (below the title)
    content_y = y0 + 7

    # ---------- SECTION A : annotated example (left, ~125mm wide) ----------
    sec_a_x = x0
    sec_a_w = 130
    ex_cx = sec_a_x + 11
    ex_cy = content_y + 14
    ex_outer = 8.5
    ex_inner = ex_outer * math.sqrt(0.11)
    # Outer disk
    parts.append(
        f'<circle cx="{ex_cx:.2f}" cy="{ex_cy:.2f}" r="{ex_outer:.2f}" '
        f'fill="{GREY_OUTER}" fill-opacity="0.30" '
        f'stroke="{GREY_OUTER_STROKE}" stroke-opacity="0.7" '
        f'stroke-width="0.25"/>'
    )
    # Inner core
    parts.append(
        f'<circle cx="{ex_cx:.2f}" cy="{ex_cy:.2f}" r="{ex_inner:.2f}" '
        f'fill="{PINK}" fill-opacity="0.95" '
        f'stroke="{PINK_DEEP}" stroke-opacity="0.85" stroke-width="0.2"/>'
    )

    # 3 stacked annotation rows to the right of the example donut
    label_x = sec_a_x + 26
    label_text_x = label_x + 0.6
    rows = [
        # (anchor_x_on_donut, anchor_y_on_donut, label_y, color, head, body)
        (ex_cx + ex_outer * 0.94, ex_cy - ex_outer * 0.34,
         content_y + 3.2, GREY_OUTER_STROKE,
         "OUTER  ·  co-presences", "people who walked past"),
        (ex_cx + ex_inner * 0.85, ex_cy + 0.0,
         content_y + 12.0, PINK_DEEP,
         "INNER  ·  noticed", "people who actually saw"),
        (ex_cx + ex_outer * 0.50, ex_cy + ex_outer * 0.78,
         content_y + 20.8, INK,
         "HOLE  ·  the blindness gap", "bigger hole = more unseen"),
    ]
    for ax, ay, ly, col, head, body in rows:
        # Leader line (with dash for the HOLE row to distinguish)
        dash = ' stroke-dasharray="0.8 0.5"' if "HOLE" in head else ""
        parts.append(
            f'<path d="M {ax:.2f} {ay:.2f} L {label_x - 1.0:.2f} {ly - 0.5:.2f}" '
            f'stroke="{col}" stroke-width="0.4" fill="none" stroke-opacity="0.95"{dash}/>'
        )
        parts.append(
            f'<text x="{label_text_x:.2f}" y="{ly:.2f}" '
            f'font-family="Inter, Helvetica Neue, sans-serif" '
            f'font-size="2.55" font-weight="700" fill="{col}">{head}</text>'
        )
        parts.append(
            f'<text x="{label_text_x:.2f}" y="{ly + 2.8:.2f}" '
            f'font-family="Inter, Helvetica Neue, sans-serif" '
            f'font-size="2.15" fill="#666">{body}</text>'
        )

    # ---------- vertical divider between A and B ----------
    div_x = sec_a_x + sec_a_w
    parts.append(
        f'<line x1="{div_x:.2f}" y1="{y0 + 5:.2f}" '
        f'x2="{div_x:.2f}" y2="{y0 + h - 1:.2f}" '
        f'stroke="#E8E0D2" stroke-width="0.4"/>'
    )

    # ---------- SECTION B : 3 archetypes (right) ----------
    sec_b_x = div_x + 4
    sec_b_w = (x0 + w) - sec_b_x
    parts.append(
        f'<text x="{sec_b_x:.2f}" y="{content_y + 1.5:.2f}" '
        f'font-family="Inter, Helvetica Neue, sans-serif" '
        f'font-size="2.55" font-weight="700" letter-spacing="0.22" '
        f'fill="#444">THREE ARCHETYPES YOU’LL SEE</text>'
    )
    archetypes = [
        {"label": "ISLAND",  "rate_lbl": "~21% noticed", "outer": 3.0,
         "rate": 0.21, "color": PINK,
         "desc": "small pool of regulars: homes,",
         "desc2": "churches, neighbourhood cafes"},
        {"label": "TYPICAL", "rate_lbl": "~11% noticed", "outer": 4.4,
         "rate": 0.11, "color": "#444",
         "desc": "everyday corner: shops, parks,",
         "desc2": "quiet lanes — partial recognition"},
        {"label": "CANYON", "rate_lbl": "~2% noticed", "outer": 6.0,
         "rate": 0.02, "color": INK,
         "desc": "high-traffic strangers: main streets,",
         "desc2": "thoroughfares — heads down, phones up"},
    ]
    col_w = sec_b_w / 3
    archetype_y = content_y + 13
    for i, a in enumerate(archetypes):
        cx_col = sec_b_x + col_w * (i + 0.5)
        inner_r = a["outer"] * math.sqrt(a["rate"])
        if inner_r < 0.18:
            inner_r = 0.18
        # Outer disk
        parts.append(
            f'<circle cx="{cx_col - col_w * 0.35:.2f}" cy="{archetype_y:.2f}" '
            f'r="{a["outer"]:.2f}" '
            f'fill="{GREY_OUTER}" fill-opacity="0.30" '
            f'stroke="{GREY_OUTER_STROKE}" stroke-opacity="0.7" '
            f'stroke-width="0.22"/>'
        )
        # Inner core
        parts.append(
            f'<circle cx="{cx_col - col_w * 0.35:.2f}" cy="{archetype_y:.2f}" '
            f'r="{inner_r:.2f}" '
            f'fill="{PINK}" fill-opacity="0.95" '
            f'stroke="{PINK_DEEP}" stroke-opacity="0.85" stroke-width="0.18"/>'
        )
        # Text block to the right of the donut
        text_x = cx_col - col_w * 0.35 + a["outer"] + 2.5
        parts.append(
            f'<text x="{text_x:.2f}" y="{archetype_y - 2.2:.2f}" '
            f'font-family="Inter, Helvetica Neue, sans-serif" '
            f'font-size="2.85" font-weight="800" letter-spacing="0.2" '
            f'fill="{a["color"]}">{a["label"]}</text>'
        )
        parts.append(
            f'<text x="{text_x:.2f}" y="{archetype_y + 0.7:.2f}" '
            f'font-family="Inter, Helvetica Neue, sans-serif" '
            f'font-size="2.3" font-weight="600" fill="#444">'
            f'{a["rate_lbl"]}</text>'
        )
        parts.append(
            f'<text x="{text_x:.2f}" y="{archetype_y + 3.6:.2f}" '
            f'font-family="Inter, Helvetica Neue, sans-serif" '
            f'font-size="2.05" fill="#777">{a["desc"]}</text>'
        )
        parts.append(
            f'<text x="{text_x:.2f}" y="{archetype_y + 5.9:.2f}" '
            f'font-family="Inter, Helvetica Neue, sans-serif" '
            f'font-size="2.05" fill="#777">{a["desc2"]}</text>'
        )

    return "\n".join(parts)


# ------------------------------------------------------------------ assemble

def assemble(base_inner: str, donuts: str, callouts: str) -> str:
    # Headline + sub
    header = f"""
<text x="{TOTAL_W/2:.2f}" y="14" text-anchor="middle"
      font-family="Inter, Helvetica Neue, sans-serif"
      font-size="7.4" font-weight="800" fill="{INK}" letter-spacing="-0.22">
  Finding 1 · The shape of default blindness
</text>
<text x="{TOTAL_W/2:.2f}" y="20.5" text-anchor="middle"
      font-family="Inter, Helvetica Neue, sans-serif"
      font-size="3.0" font-weight="500" fill="#5a5a5a" letter-spacing="0.05">
  Lane Cove · 1,000 residents · 14 days · 2 seeds pooled · no app condition
</text>
<text x="{TOTAL_W/2:.2f}" y="29.5" text-anchor="middle"
      font-family="Charter, Georgia, serif"
      font-size="3.7" font-style="italic" font-weight="500" fill="#3a3a3a">
  Of every 100 strangers walked past, only 11 register. The gap is geographic.
</text>
"""

    # Explainer strip below the map (in PARENT svg coords — not clipped)
    read_me = build_read_me_strip(MAP_X, READ_ME_Y, MAP_W, READ_ME_H)

    # Footer pullquote + stats (below the read-me strip)
    footer_y = FOOTER_Y_BASE + 7
    footer = f"""
<text x="{TOTAL_W/2:.2f}" y="{footer_y:.2f}" text-anchor="middle"
      font-family="Charter, Georgia, serif"
      font-size="4.6" font-style="italic" fill="{INK}">
  The donut hole is the blindness.  The biggest holes are streets; the smallest are homes.
</text>
<text x="{TOTAL_W/2:.2f}" y="{footer_y + 6.6:.2f}" text-anchor="middle"
      font-family="Inter, Helvetica Neue, sans-serif"
      font-size="2.6" fill="#666" font-weight="500">
  Residential 19% · worship 17% · cafe 13% · street 7%  ·  rate gap on the same physical surface = 1 : 6
</text>
<text x="{TOTAL_W/2:.2f}" y="{footer_y + 11.5:.2f}" text-anchor="middle"
      font-family="Inter, Helvetica Neue, sans-serif"
      font-size="1.95" fill="#888" letter-spacing="0.04">
  Top {{n_donuts}} locations by encounter volume (n ≥ {MIN_ENCOUNTERS}) · noticed = encounter event with attention-gate flag set
</text>
"""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:xlink="http://www.w3.org/1999/xlink"
     width="{TOTAL_W:.1f}mm" height="{TOTAL_H:.1f}mm"
     viewBox="0 0 {TOTAL_W:.2f} {TOTAL_H:.2f}"
     preserveAspectRatio="xMidYMid meet">
  <rect width="100%" height="100%" fill="{BG}"/>
  <defs>
    <clipPath id="mapClip">
      <rect x="0" y="0" width="{MAP_W:.2f}" height="{MAP_H:.2f}"/>
    </clipPath>
  </defs>

  {header}

  <svg x="{MAP_X:.2f}" y="{MAP_Y:.2f}"
       width="{MAP_W:.2f}" height="{MAP_H:.2f}"
       viewBox="0 0 {MAP_W:.2f} {MAP_H:.2f}"
       overflow="hidden" preserveAspectRatio="none">
    <g clip-path="url(#mapClip)">
      <g opacity="0.34">
        {base_inner}
      </g>
      <g id="f1-donuts">
        {donuts}
      </g>
      <g id="f1-callouts">
        {callouts}
      </g>
    </g>
  </svg>

  <g id="f1-read-me">
    {read_me}
  </g>

  {footer}
</svg>
"""


# ------------------------------------------------------------------ main

def main() -> int:
    print("[f1_donut] generating 2.5d base...")
    base_svg = gen_base()
    base_inner = extract_base_inner(base_svg)
    print(f"[f1_donut] base inner: {len(base_inner):,} chars")

    atlas = load_atlas()
    center = hub_center(atlas)
    proj, scale = make_proj(center)
    loc_idx = loc_centroid_index(atlas)
    print(f"[f1_donut] center=({center[0]:.0f},{center[1]:.0f}) scale={scale:.4f}")

    f1 = json.loads(F1_JSON.read_text(encoding="utf-8"))
    f1_locs = f1["all_location_rates"]
    print(f"[f1_donut] {len(f1_locs)} F1 locations")

    # First pass: resolve callout location IDs (so render_donut can highlight them)
    callout_ids = set()
    for c in CALLOUTS:
        r = resolve_callout(c, f1_locs, loc_idx)
        if r:
            callout_ids.add(r[0])

    donuts, glyph_info = build_donuts(f1_locs, loc_idx, proj, callout_ids)
    callouts, _ = build_callouts(f1_locs, loc_idx, proj, glyph_info)

    n_donuts = sum(1 for l in f1_locs
                   if loc_idx.get(l["loc"]) and l["enc"] >= MIN_ENCOUNTERS)
    print(f"[f1_donut] rendered {n_donuts} donuts")

    svg = assemble(base_inner, donuts, callouts)
    svg = svg.replace("{n_donuts}", str(n_donuts))
    OUT_SVG.parent.mkdir(parents=True, exist_ok=True)
    OUT_SVG.write_text(svg, encoding="utf-8")
    print(f"[f1_donut] wrote {OUT_SVG} ({OUT_SVG.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
