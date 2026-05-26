"""F1 v4 companion · Flat top-down donut map + building-type bar chart.

Companion to the 2.5D hero (f1_25d_donut.svg).  Same donut encoding
(outer grey = encounters, inner pink = noticed) but rendered in a flat
top-down projection so:
  - Geography is unambiguous — readers can locate Coxs Lane, Plaza, etc.
  - More callouts fit (~10 named POIs) on a flat map than on iso.
  - An inset bar chart on the right shows the building-type breakdown
    (residential 19% → street 7%) that the donut sizes already hint at.

Output: data/analysis/.../F1_shape/f1_2d_companion.svg
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
OUT_SVG = REPO / "data/analysis/2026-05-24_hypothesis_validation/F1_shape/f1_2d_companion.svg"
BUILD_BAT = REPO / "tools/build_atlas_thumbnail.py"
TMP_BASE = Path("/tmp/f1_2d_companion_base.svg")

# ------------------------------------------------------------------ layout
TOTAL_W = 360.0
HEADER_H = 32.0
MAP_W = 268.0
MAP_H = 178.0
INSET_W = 76.0  # bar chart panel on right
GAP = 6.0
FOOTER_H = 22.0
MARGIN_X = 10.0
TOTAL_H = HEADER_H + MAP_H + FOOTER_H

MAP_X = MARGIN_X
MAP_Y = HEADER_H
INSET_X = MAP_X + MAP_W + GAP
INSET_Y = MAP_Y

# Projection params (flat top-down — mirror build_atlas_thumbnail proj())
RADIUS_M = 1000.0
PAD = 2.0

# Palette (matches hero)
BG = "#FCFAF6"
INK = "#1B1F2A"
PINK = "#FF4D8F"
PINK_DEEP = "#C8245E"
GREY_OUTER = "#9E988C"
GREY_OUTER_STROKE = "#5F584F"
LABEL_BOX_BG = "#FFFFFF"

# Donut geometry
OUTER_R_MIN = 0.95
OUTER_R_MAX = 6.5
INNER_R_MIN = 0.25

MIN_ENCOUNTERS = 200


# ------------------------------------------------------------------ base

def gen_base() -> str:
    cmd = [
        str(REPO / ".venv/bin/python3"),
        str(BUILD_BAT),
        "--atlas", str(ATLAS_PATH),
        "--out", str(TMP_BASE),
        "--style", "2d",
        "--size-mm", f"{int(MAP_W)}:{int(MAP_H)}",
        "--radius-m", str(int(RADIUS_M)),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return TMP_BASE.read_text(encoding="utf-8")


def extract_base_inner(base_svg: str) -> str:
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
    sx = sy = 0.0; n = 0
    for b in bldgs.values():
        vs = b.get("polygon", {}).get("vertices", [])
        if not vs: continue
        sx += sum(v["x"] for v in vs) / len(vs)
        sy += sum(v["y"] for v in vs) / len(vs)
        n += 1
    return (sx / n, sy / n) if n else (0.0, 0.0)


def make_proj(center: tuple[float, float]):
    """Flat top-down projection: atlas meters -> SVG mm, no iso skew."""
    scale = min((MAP_W - 2 * PAD) / (2 * RADIUS_M),
                (MAP_H - 2 * PAD) / (2 * RADIUS_M))
    cx, cy = center

    def proj(x: float, y: float) -> tuple[float, float]:
        sx = MAP_W / 2 + (x - cx) * scale
        sy = MAP_H / 2 - (y - cy) * scale  # flip y (atlas north → svg up)
        return sx, sy

    return proj, scale


def loc_centroid_index(atlas: dict) -> dict[str, tuple[float, float, str]]:
    out = {}
    for bid, b in atlas["buildings"].items():
        vs = b.get("polygon", {}).get("vertices", [])
        if not vs: continue
        x = sum(v["x"] for v in vs) / len(vs)
        y = sum(v["y"] for v in vs) / len(vs)
        out[bid] = (x, y, b.get("building_type") or "")
    out_areas = atlas.get("outdoor_areas", {})
    items = out_areas.items() if isinstance(out_areas, dict) else [
        (o["id"], o) for o in out_areas
    ]
    for oid, o in items:
        vs = o.get("polygon", {}).get("vertices", [])
        if not vs: continue
        x = sum(v["x"] for v in vs) / len(vs)
        y = sum(v["y"] for v in vs) / len(vs)
        out[oid] = (x, y, o.get("area_type") or "")
    return out


# ------------------------------------------------------------------ donuts

def outer_radius(enc, enc_p95):
    if enc <= 0: return 0
    t = min(math.sqrt(enc / enc_p95), 1.5)
    return OUTER_R_MIN + (OUTER_R_MAX - OUTER_R_MIN) * (t / 1.5)


def inner_radius(noticed, enc, outer_r):
    if enc <= 0 or noticed <= 0: return 0
    rate = noticed / enc
    r = outer_r * math.sqrt(rate)
    if r < INNER_R_MIN: return 0
    return r


def render_donut(sx, sy, outer_r, inner_r):
    parts = []
    parts.append(
        f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{outer_r:.2f}" '
        f'fill="{GREY_OUTER}" fill-opacity="0.22" '
        f'stroke="{GREY_OUTER_STROKE}" stroke-opacity="0.55" '
        f'stroke-width="0.18"/>'
    )
    if inner_r > 0:
        parts.append(
            f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{inner_r:.2f}" '
            f'fill="{PINK}" fill-opacity="0.92" '
            f'stroke="{PINK_DEEP}" stroke-opacity="0.85" '
            f'stroke-width="0.18"/>'
        )
    return "".join(parts)


def build_donuts(f1_locs, loc_idx, proj):
    valid = [l for l in f1_locs
             if loc_idx.get(l["loc"]) and l["enc"] >= MIN_ENCOUNTERS]
    if not valid:
        return ""
    enc_p95 = sorted(l["enc"] for l in valid)[int(len(valid) * 0.95)]
    valid.sort(key=lambda x: -x["enc"])

    parts = []
    for l in valid:
        x, y, _ = loc_idx[l["loc"]]
        sx, sy = proj(x, y)
        if sx < -3 or sx > MAP_W + 3 or sy < -3 or sy > MAP_H + 3:
            continue
        outer_r = outer_radius(l["enc"], enc_p95)
        inner_r = inner_radius(l["noticed"], l["enc"], outer_r)
        parts.append(render_donut(sx, sy, outer_r, inner_r))
    return "\n".join(parts)


# ------------------------------------------------------------------ callouts

# 10 named callouts — more than hero because flat map fits more labels.
# 5 awareness islands (high rate) + 5 blindness canyons (high traffic, low rate).
CALLOUTS = [
    # ISLANDS (named, high-rate)
    {"name_match": "PLC Sydney Preschool",
     "label": "PLC Sydney Preschool", "sub": "21% · n=124", "kind": "island",
     "box_pos": (2, 12), "box_w": 56},
    {"name_match": "Saint Michael's Catholic Church",
     "label": "Saint Michael's Church", "sub": "21% · n=66", "kind": "island",
     "box_pos": (2, 30), "box_w": 56},
    {"name_match": "Grill'd",
     "label": "Grill'd (restaurant)", "sub": "21% · n=104", "kind": "island",
     "box_pos": (2, 48), "box_w": 56},
    {"name_match": "Marie Ramos Photography",
     "label": "Marie Ramos Photography", "sub": "26% · n=92", "kind": "island",
     "box_pos": (2, 66), "box_w": 56},
    {"name_match": "Biz-directory",
     "label": "Biz-directory (office)", "sub": "26% · n=156", "kind": "island",
     "box_pos": (MAP_W - 60, 12), "box_w": 58},
    # CANYONS (street, low-rate, high-traffic)
    {"name_match": "Coxs Lane",
     "label": "Coxs Lane", "sub": "5% · n=5,056 (busiest)", "kind": "canyon",
     "box_pos": (MAP_W - 70, MAP_H - 56), "box_w": 68},
    {"name_match": "Karilla Avenue",
     "label": "Karilla Avenue", "sub": "2% · n=3,570", "kind": "canyon",
     "box_pos": (MAP_W - 70, MAP_H - 38), "box_w": 68},
    {"name_match": "Finlayson Street",
     "label": "Finlayson Street", "sub": "1.1% · n=2,374", "kind": "canyon",
     "box_pos": (MAP_W - 70, MAP_H - 20), "box_w": 68},
    {"name_match": "Lane Cove Plaza",
     "label": "Lane Cove Plaza", "sub": "9% · n=2,622", "kind": "canyon",
     "box_pos": (2, MAP_H - 38), "box_w": 60},
    {"name_match": "Longueville Road",
     "label": "Longueville Road", "sub": "10% · n=2,200", "kind": "canyon",
     "box_pos": (2, MAP_H - 20), "box_w": 60},
]


def resolve_callout(c, f1_locs, loc_idx):
    needle = c["name_match"].lower()
    for l in f1_locs:
        if needle in l["name"].lower():
            if l["loc"] in loc_idx:
                return l["loc"], loc_idx[l["loc"]][:2]
    return None


def build_callouts(f1_locs, loc_idx, proj):
    parts = []
    for c in CALLOUTS:
        r = resolve_callout(c, f1_locs, loc_idx)
        if r is None:
            print(f"[f1_2d] WARN: callout {c['label']} not resolved")
            continue
        _, (x, y) = r
        sx, sy = proj(x, y)
        bx, by = c["box_pos"]
        bw = c["box_w"]; bh = 8.5

        accent = PINK if c["kind"] == "island" else INK
        accent_label = "AWARENESS ISLAND" if c["kind"] == "island" else "BLINDNESS CANYON"

        box_cx = bx + bw / 2
        leader_box_x = (bx + bw) if sx > box_cx else bx
        leader_box_y = by + bh / 2

        # Marker: white halo + colored ring + center dot
        parts.append(
            f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="3.0" '
            f'fill="none" stroke="{BG}" stroke-width="1.4" stroke-opacity="0.95"/>'
        )
        parts.append(
            f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="2.7" '
            f'fill="none" stroke="{accent}" stroke-width="0.6" stroke-opacity="1.0"/>'
        )
        parts.append(
            f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.5" fill="{accent}"/>'
        )
        # Leader line with white halo
        parts.append(
            f'<path d="M {leader_box_x:.2f} {leader_box_y:.2f} L {sx:.2f} {sy:.2f}" '
            f'stroke="{BG}" stroke-width="1.0" stroke-opacity="0.85" fill="none"/>'
        )
        parts.append(
            f'<path d="M {leader_box_x:.2f} {leader_box_y:.2f} L {sx:.2f} {sy:.2f}" '
            f'stroke="{accent}" stroke-width="0.35" stroke-opacity="1.0" fill="none"/>'
        )
        # White box
        parts.append(
            f'<rect x="{bx:.2f}" y="{by:.2f}" width="{bw:.2f}" height="{bh:.2f}" '
            f'rx="1.0" ry="1.0" fill="{LABEL_BOX_BG}" '
            f'stroke="{accent}" stroke-width="0.38" stroke-opacity="0.85"/>'
        )
        parts.append(
            f'<text x="{bx + 1.8:.2f}" y="{by + 2.9:.2f}" '
            f'font-family="Inter, Helvetica Neue, sans-serif" '
            f'font-size="1.8" font-weight="700" letter-spacing="0.18" '
            f'fill="{accent}">{accent_label}</text>'
        )
        parts.append(
            f'<text x="{bx + 1.8:.2f}" y="{by + 5.5:.2f}" '
            f'font-family="Inter, Helvetica Neue, sans-serif" '
            f'font-size="2.55" font-weight="700" fill="{INK}">{c["label"]}</text>'
        )
        parts.append(
            f'<text x="{bx + 1.8:.2f}" y="{by + 7.7:.2f}" '
            f'font-family="Inter, Helvetica Neue, sans-serif" '
            f'font-size="2.05" fill="#555">{c["sub"]}</text>'
        )
    return "\n".join(parts)


# ------------------------------------------------------------------ inset bar chart

def build_inset_bars(x0: float, y0: float, w: float, h: float,
                     btypes: list[dict]) -> str:
    """Horizontal bar chart of notice rate by building type."""
    parts = []
    # Card chrome
    parts.append(
        f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{w:.2f}" height="{h:.2f}" '
        f'rx="1.5" ry="1.5" fill="white" stroke="#D8D2C8" stroke-width="0.4"/>'
    )
    # Title
    parts.append(
        f'<text x="{x0 + 3:.2f}" y="{y0 + 5.0:.2f}" '
        f'font-family="Inter, Helvetica Neue, sans-serif" '
        f'font-size="3.2" font-weight="800" letter-spacing="-0.05" '
        f'fill="{INK}">Notice rate by place</text>'
    )
    parts.append(
        f'<text x="{x0 + 3:.2f}" y="{y0 + 8.5:.2f}" '
        f'font-family="Inter, Helvetica Neue, sans-serif" '
        f'font-size="2.2" fill="#666">of every 100 strangers walked past,</text>'
    )
    parts.append(
        f'<text x="{x0 + 3:.2f}" y="{y0 + 11.0:.2f}" '
        f'font-family="Inter, Helvetica Neue, sans-serif" '
        f'font-size="2.2" fill="#666">how many actually register</text>'
    )

    # Filter + sort building types
    rows = [b for b in btypes if b["total_enc"] >= 200]
    rows.sort(key=lambda x: -x["rate"])
    rows = rows[:11]  # top-N by rate

    # Bar geometry
    bar_x0 = x0 + 22
    bar_w_max = w - 22 - 12  # leave room for label + percent
    base_y = y0 + 16
    row_h = (h - 16 - 6) / len(rows)
    max_rate = max(r["rate"] for r in rows)
    # Cap rate scale at 0.25 for consistent visual
    rate_scale = max(max_rate, 0.25)

    for i, r in enumerate(rows):
        yr = base_y + row_h * i + 0.5
        # Building type label (left of bar)
        parts.append(
            f'<text x="{x0 + 3:.2f}" y="{yr + row_h * 0.55:.2f}" '
            f'font-family="Inter, Helvetica Neue, sans-serif" '
            f'font-size="2.3" font-weight="600" fill="#444">'
            f'{r["type"]}</text>'
        )
        # Bar: pink fill, length = rate / rate_scale * bar_w_max
        bar_len = r["rate"] / rate_scale * bar_w_max
        # Highlight residential as the high end + street as the low end
        is_street = r["type"] == "street"
        is_res = r["type"] == "residential"
        bar_color = PINK if (is_res or is_street) else "#B8AEA0"
        bar_op = 0.92 if (is_res or is_street) else 0.55
        parts.append(
            f'<rect x="{bar_x0:.2f}" y="{yr + row_h * 0.25:.2f}" '
            f'width="{bar_len:.2f}" height="{row_h * 0.55:.2f}" '
            f'fill="{bar_color}" fill-opacity="{bar_op}" '
            f'stroke="{PINK_DEEP if (is_res or is_street) else "#666"}" '
            f'stroke-opacity="0.65" stroke-width="0.15"/>'
        )
        # Percent label
        pct_x = bar_x0 + bar_len + 1.2
        pct_color = PINK_DEEP if (is_res or is_street) else "#666"
        pct_weight = "700" if (is_res or is_street) else "500"
        parts.append(
            f'<text x="{pct_x:.2f}" y="{yr + row_h * 0.65:.2f}" '
            f'font-family="Inter, Helvetica Neue, sans-serif" '
            f'font-size="2.3" font-weight="{pct_weight}" fill="{pct_color}">'
            f'{r["rate"] * 100:.0f}%</text>'
        )

    # Bottom annotation: punchline
    parts.append(
        f'<line x1="{x0 + 3:.2f}" y1="{y0 + h - 6:.2f}" '
        f'x2="{x0 + w - 3:.2f}" y2="{y0 + h - 6:.2f}" '
        f'stroke="#E8E0D2" stroke-width="0.3"/>'
    )
    parts.append(
        f'<text x="{x0 + 3:.2f}" y="{y0 + h - 2.8:.2f}" '
        f'font-family="Charter, Georgia, serif" font-style="italic" '
        f'font-size="2.35" fill="{INK}">'
        f'Living rooms see (19%).  Streets pass (7%).</text>'
    )

    return "\n".join(parts)


# ------------------------------------------------------------------ assemble

def assemble(base_inner: str, donuts: str, callouts: str,
             inset_bars: str) -> str:
    header = f"""
<text x="{TOTAL_W/2:.2f}" y="13.5" text-anchor="middle"
      font-family="Inter, Helvetica Neue, sans-serif"
      font-size="6.4" font-weight="800" fill="{INK}" letter-spacing="-0.2">
  Finding 1 · Where the noticing actually lives (companion view)
</text>
<text x="{TOTAL_W/2:.2f}" y="20.0" text-anchor="middle"
      font-family="Inter, Helvetica Neue, sans-serif"
      font-size="2.8" fill="#5a5a5a">
  Flat top-down · same 142 donuts as the hero · 10 named places · bar chart shows the building-type pattern
</text>
<text x="{TOTAL_W/2:.2f}" y="26.6" text-anchor="middle"
      font-family="Charter, Georgia, serif"
      font-size="3.2" font-style="italic" fill="#444">
  Same data, flatter projection. Easier to point to a street and ask: did anyone see anyone there?
</text>
"""
    footer_y = MAP_Y + MAP_H + 7
    footer = f"""
<text x="{TOTAL_W/2:.2f}" y="{footer_y:.2f}" text-anchor="middle"
      font-family="Charter, Georgia, serif"
      font-size="4.2" font-style="italic" fill="{INK}">
  In 14 days, the busiest street (Coxs Lane) registered ~5,000 co-presences and converted 5% — about 268 nods of recognition.
</text>
<text x="{TOTAL_W/2:.2f}" y="{footer_y + 6.0:.2f}" text-anchor="middle"
      font-family="Inter, Helvetica Neue, sans-serif"
      font-size="2.4" fill="#666">
  A single church chapel registered only 66 co-presences but converted 21% — 14 of them genuine mutual recognition.
</text>
<text x="{TOTAL_W/2:.2f}" y="{footer_y + 10.5:.2f}" text-anchor="middle"
      font-family="Inter, Helvetica Neue, sans-serif"
      font-size="1.9" fill="#888" letter-spacing="0.04">
  Top {{n_donuts}} locations · n ≥ {MIN_ENCOUNTERS} · 2 seeds pooled · noticed = encounter event past attention gate
</text>
"""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     width="{TOTAL_W:.1f}mm" height="{TOTAL_H:.1f}mm"
     viewBox="0 0 {TOTAL_W:.2f} {TOTAL_H:.2f}"
     preserveAspectRatio="xMidYMid meet">
  <rect width="100%" height="100%" fill="{BG}"/>
  <defs>
    <clipPath id="mapClip2d">
      <rect x="0" y="0" width="{MAP_W:.2f}" height="{MAP_H:.2f}"/>
    </clipPath>
  </defs>

  {header}

  <svg x="{MAP_X:.2f}" y="{MAP_Y:.2f}"
       width="{MAP_W:.2f}" height="{MAP_H:.2f}"
       viewBox="0 0 {MAP_W:.2f} {MAP_H:.2f}"
       overflow="hidden" preserveAspectRatio="none">
    <g clip-path="url(#mapClip2d)">
      <g opacity="0.38">
        {base_inner}
      </g>
      <g id="f1-donuts-2d">
        {donuts}
      </g>
      <g id="f1-callouts-2d">
        {callouts}
      </g>
    </g>
  </svg>

  <g id="f1-inset-bars">
    {inset_bars}
  </g>

  {footer}
</svg>
"""


# ------------------------------------------------------------------ main

def main() -> int:
    print("[f1_2d] generating flat top-down base...")
    base_svg = gen_base()
    base_inner = extract_base_inner(base_svg)

    atlas = load_atlas()
    center = hub_center(atlas)
    proj, scale = make_proj(center)
    loc_idx = loc_centroid_index(atlas)
    print(f"[f1_2d] center=({center[0]:.0f},{center[1]:.0f}) scale={scale:.4f}")

    f1 = json.loads(F1_JSON.read_text(encoding="utf-8"))
    f1_locs = f1["all_location_rates"]
    btypes = f1["location_by_building_type"]

    donuts = build_donuts(f1_locs, loc_idx, proj)
    callouts = build_callouts(f1_locs, loc_idx, proj)
    inset_bars = build_inset_bars(INSET_X, INSET_Y, INSET_W, MAP_H, btypes)

    n_donuts = sum(1 for l in f1_locs
                   if loc_idx.get(l["loc"]) and l["enc"] >= MIN_ENCOUNTERS)
    print(f"[f1_2d] rendered {n_donuts} donuts")

    svg = assemble(base_inner, donuts, callouts, inset_bars)
    svg = svg.replace("{n_donuts}", str(n_donuts))
    OUT_SVG.parent.mkdir(parents=True, exist_ok=True)
    OUT_SVG.write_text(svg, encoding="utf-8")
    print(f"[f1_2d] wrote {OUT_SVG} ({OUT_SVG.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
