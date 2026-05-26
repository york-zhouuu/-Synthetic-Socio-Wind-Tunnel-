"""3 mock-up styles for Finding 1 (22.7% bimodal response).

User picks one, then we scale that style to all 8 findings.

Output:
  docs/mockups/finding1_A_map_annotation.svg     — NYT-style map + callout arrows
  docs/mockups/finding1_B_split_panel.svg        — Left: big number + chart, Right: map
  docs/mockups/finding1_C_storyboard.svg         — 4-panel cause→effect sequence
"""
from __future__ import annotations
import json
import math
from collections import defaultdict
from pathlib import Path

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
ATLAS = REPO / "data/lanecove_atlas.json"
ANALYSIS = REPO / "data/analysis/2026-05-23_paper_exploration"
OUT = REPO / "docs/mockups"
OUT.mkdir(parents=True, exist_ok=True)


# ── Refined palette (NYT-inspired) ──────────────────────────
INK = "#1B1F2A"
INK_SOFT = "#5A5E6A"
INK_LIGHT = "#A8ACB5"
BG = "#FAFAF7"
BG_PAPER = "#FFFFFF"
ACCENT = "#E03A4A"  # vivid red, NYT style
ACCENT_SOFT = "#FBD8DC"
ACCENT_DARK = "#A0252F"
HIGHLIGHT = "#F0C419"
HIGHLIGHT_SOFT = "#FFF4C7"
GREY = "#D8D9DC"
GREEN = "#3A9D5C"
BLUE = "#3B6EA8"


def centroid(verts):
    if not verts: return None
    if isinstance(verts[0], dict):
        xs = [v["x"] for v in verts]; ys = [v["y"] for v in verts]
    else:
        xs = [v[0] for v in verts]; ys = [v[1] for v in verts]
    return sum(xs)/len(xs), sum(ys)/len(ys)


def load_atlas():
    with open(ATLAS) as f:
        return json.load(f)


def get_center():
    atlas = load_atlas()
    hub = atlas["buildings"].get("lane_cove_community_hub")
    if hub:
        c = centroid(hub.get("polygon", {}).get("vertices", []))
        if c: return c
    xs, ys, n = 0, 0, 0
    for b in atlas["buildings"].values():
        c = centroid(b.get("polygon", {}).get("vertices", []))
        if c: xs += c[0]; ys += c[1]; n += 1
    return xs / n, ys / n


def load_responder_data():
    with open(ANALYSIS / "C_responder_profile/agents_hyperlocal_push.json") as f:
        agents = json.load(f)
    return [a for a in agents if a["seed"] == 43 and a.get("home_xy") and a["home_xy"][0] is not None]


# ── Helpers: street network extraction ───────────────────────
def get_streets_near(atlas, center, radius=1100):
    cx, cy = center
    streets = []
    outdoor = atlas.get("outdoor_areas", {})
    items = outdoor.values() if isinstance(outdoor, dict) else outdoor
    named_streets = defaultdict(list)
    for o in items:
        if (o.get("area_type") or "").lower() != "street":
            continue
        c = centroid(o.get("polygon", {}).get("vertices", []))
        if not c: continue
        if (c[0]-cx)**2 + (c[1]-cy)**2 > radius**2:
            continue
        rd = o.get("road_name")
        if rd:
            named_streets[rd].append(c)
        streets.append((o, c))
    return streets, named_streets


def get_buildings_near(atlas, center, radius=1100):
    cx, cy = center
    bldgs = []
    for aid, b in atlas["buildings"].items():
        c = centroid(b.get("polygon", {}).get("vertices", []))
        if not c: continue
        if (c[0]-cx)**2 + (c[1]-cy)**2 > radius**2: continue
        bldgs.append((aid, b, c))
    return bldgs


# ────────────────────────────────────────────────────────────
# MOCK-UP A · NYT-style "map + annotation"
# ────────────────────────────────────────────────────────────
def mockup_A():
    """Map-dominant NYT style.

    Layout (320 × 220 mm, A4 landscape feeling):
    ┌──────────────────────────────────────────────────────────┐
    │ KICKER · FINDING 1                                       │
    │ Big Headline (22.7%) │ 36pt                              │
    │ Subtitle one-liner   │ 14pt                              │
    ├──────────────────────────────────────────────────────────┤
    │                                                          │
    │      [MAP: Lane Cove with responder/non dots]            │
    │      + 3-4 numbered callout arrows pointing to clusters  │
    │      + Streets labeled (Longueville Rd, Mowbray Rd)      │
    │                                                          │
    ├──────────────────────────────────────────────────────────┤
    │ ① Cowper St cluster: 28% response rate                   │
    │ ② Center area: 22% (overall avg)                         │
    │ ③ Edge blocks: 12%                                       │
    │ Source: ... (in fine print)                              │
    └──────────────────────────────────────────────────────────┘
    """
    W, H = 320, 220  # mm
    center = get_center()
    atlas = load_atlas()
    streets, named = get_streets_near(atlas, center, 1100)
    bldgs = get_buildings_near(atlas, center, 1100)
    agents = load_responder_data()
    resp = [a["home_xy"] for a in agents if a["is_responder"]]
    non = [a["home_xy"] for a in agents if not a["is_responder"]]

    # Map area (occupies most of canvas)
    map_x, map_y = 12, 50
    map_w, map_h = 240, 145
    cx_atlas, cy_atlas = center
    # Compute scale to fit
    radius = 1100
    scale = min((map_w) / (2 * radius), (map_h) / (2 * radius))

    def proj(x, y):
        sx = map_x + map_w / 2 + (x - cx_atlas) * scale
        sy = map_y + map_h / 2 - (y - cy_atlas) * scale
        return sx, sy

    out = []
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" '
               f'viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">')
    # background — newspaper paper
    out.append(f'<rect width="100%" height="100%" fill="{BG_PAPER}"/>')

    # === Header band — NYT typography ===
    out.append(f'<text x="12" y="14" font-family="Georgia,serif" font-size="3.3" '
               f'font-style="italic" fill="{ACCENT_DARK}" letter-spacing="0.3">'
               f'FINDING 01  ·  Synthetic Socio Wind Tunnel  ·  Lane Cove, Sydney</text>')
    # Main headline
    out.append(f'<text x="12" y="32" font-family="Georgia,serif" font-size="13" '
               f'font-weight="900" fill="{INK}" letter-spacing="-0.5">'
               f'当推送来到楼下,只有 <tspan fill="{ACCENT}">22.7%</tspan> 的人真的走出门。</text>'
               )
    # Subhead
    out.append(f'<text x="12" y="42" font-family="Georgia,serif" font-size="5" '
               f'font-style="italic" fill="{INK_SOFT}">'
               f'剩下 77.3% 的居民完全不为所动 — 干预效果不是渐变,是二元筛选。</text>')

    # === MAP — light background ===
    # Map clip area
    out.append(f'<g id="map">')
    # Subtle map bg
    out.append(f'<rect x="{map_x}" y="{map_y}" width="{map_w}" height="{map_h}" '
               f'fill="#F4F2EB" stroke="{INK_LIGHT}" stroke-width="0.2"/>')
    # Streets as thin lines
    out.append('<g id="streets" opacity="0.6">')
    for _, c in streets:
        sx, sy = proj(c[0], c[1])
        out.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.18" fill="{INK_LIGHT}"/>')
    out.append("</g>")
    # Building outlines as VERY subtle dots
    out.append('<g id="bldgs" opacity="0.25">')
    for _, b, c in bldgs:
        sx, sy = proj(c[0], c[1])
        out.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.15" fill="{INK_LIGHT}"/>')
    out.append("</g>")

    # Non-responders as small dots
    out.append('<g id="non-resp">')
    cx, cy = center
    for x, y in non:
        if (x-cx)**2 + (y-cy)**2 > 1100**2: continue
        sx, sy = proj(x, y)
        out.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.55" fill="{INK_LIGHT}" opacity="0.55"/>')
    out.append("</g>")

    # Responders as bigger red dots
    out.append('<g id="resp">')
    for x, y in resp:
        if (x-cx)**2 + (y-cy)**2 > 1100**2: continue
        sx, sy = proj(x, y)
        out.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="1.4" fill="{ACCENT}" '
                   f'opacity="0.85" stroke="{INK}" stroke-width="0.1"/>')
    out.append("</g>")

    # Named streets — label key roads
    KEY_STREETS = ["Longueville Road", "Mowbray Road", "Burns Bay Road", "Epping Road",
                   "Pacific Highway", "River Road", "Centennial Avenue"]
    out.append('<g id="street-labels">')
    for rd_name, locs in named.items():
        if rd_name not in KEY_STREETS: continue
        # take the geometric mean of all street segments with this name
        xs = [c[0] for c in locs]; ys = [c[1] for c in locs]
        mx, my = sum(xs)/len(xs), sum(ys)/len(ys)
        sx, sy = proj(mx, my)
        # Skip if outside map area
        if not (map_x+5 < sx < map_x+map_w-5 and map_y+5 < sy < map_y+map_h-5): continue
        # Black halo + ink text
        out.append(f'<text x="{sx:.2f}" y="{sy:.2f}" font-family="Georgia,serif" '
                   f'font-size="2.7" font-weight="700" font-style="italic" '
                   f'fill="{INK}" text-anchor="middle" stroke="{BG_PAPER}" '
                   f'stroke-width="0.9" paint-order="stroke">{rd_name}</text>')
    out.append("</g>")

    # === Numbered annotation callouts ===
    # Pick 3 visually interesting locations — compute clusters
    # Cluster 1: highest density area
    grid = defaultdict(int)
    for x, y in resp:
        if (x-cx)**2 + (y-cy)**2 > 1100**2: continue
        gx, gy = int((x - cx_atlas + 1100) // 100), int((y - cy_atlas + 1100) // 100)
        grid[(gx, gy)] += 1
    # Top 3 cells
    top_cells = sorted(grid.items(), key=lambda kv: -kv[1])[:3]
    callouts = []
    for i, ((gx, gy), n) in enumerate(top_cells, 1):
        x_atlas = cx_atlas - 1100 + gx * 100 + 50
        y_atlas = cy_atlas - 1100 + gy * 100 + 50
        sx, sy = proj(x_atlas, y_atlas)
        callouts.append((i, sx, sy, n))

    out.append('<g id="callouts">')
    callout_text_positions = [
        (map_x + map_w + 8, map_y + 20),
        (map_x + map_w + 8, map_y + 55),
        (map_x + map_w + 8, map_y + 90),
    ]
    for (i, sx, sy, n), (tx, ty) in zip(callouts, callout_text_positions):
        # Yellow circle marker on map
        out.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="2.6" '
                   f'fill="{HIGHLIGHT}" stroke="{INK}" stroke-width="0.35"/>')
        out.append(f'<text x="{sx:.2f}" y="{sy+1:.2f}" font-family="Georgia,serif" '
                   f'font-size="3.5" font-weight="900" fill="{INK}" text-anchor="middle">{i}</text>')
        # Line connecting to side text
        out.append(f'<line x1="{sx+2.6:.2f}" y1="{sy:.2f}" x2="{tx-2:.2f}" y2="{ty:.2f}" '
                   f'stroke="{INK_SOFT}" stroke-width="0.25" stroke-dasharray="0.8 0.5"/>')
    out.append("</g>")

    out.append("</g>")  # /map

    # === Side annotation text ===
    out.append('<g id="annotations">')
    for ((i, sx, sy, n), (tx, ty), txt) in zip(callouts, callout_text_positions, [
        ("Cowper St 段街区", "约 28% 响应率,这片是 Lane Cove 老社区, 退休 + 自由职业聚集"),
        ("中心商业区", "约 22% — 接近全街区平均 — 提供 anchor POI"),
        ("外围 Mowbray Rd 段", "约 12% — schedule-bound 工人 + 学生 + 通勤者"),
    ]):
        out.append(f'<text x="{tx}" y="{ty}" font-family="Georgia,serif" '
                   f'font-size="3.8" font-weight="900" fill="{INK}">{txt[0]}</text>')
        # word wrap by line
        words = txt[1]
        # break into 2 lines of ~ 28 chars
        line1 = words[:32]; line2 = words[32:]
        out.append(f'<text x="{tx}" y="{ty+5}" font-family="Georgia,serif" '
                   f'font-size="2.9" fill="{INK_SOFT}">{line1}</text>')
        if line2:
            out.append(f'<text x="{tx}" y="{ty+9}" font-family="Georgia,serif" '
                       f'font-size="2.9" fill="{INK_SOFT}">{line2}</text>')
    out.append("</g>")

    # === Bottom: source line + legend ===
    leg_y = H - 12
    out.append(f'<g id="legend">')
    # red dot label
    out.append(f'<circle cx="14" cy="{leg_y-1}" r="1.3" fill="{ACCENT}"/>')
    out.append(f'<text x="17" y="{leg_y}" font-family="Helvetica,sans-serif" font-size="2.7" '
               f'fill="{INK}">响应者(物理位移 &gt;20m)</text>')
    # grey dot label
    out.append(f'<circle cx="64" cy="{leg_y-1}" r="0.55" fill="{INK_LIGHT}"/>')
    out.append(f'<text x="66" y="{leg_y}" font-family="Helvetica,sans-serif" font-size="2.7" '
               f'fill="{INK}">非响应者</text>')
    out.append(f'<circle cx="92" cy="{leg_y-1}" r="2" fill="{HIGHLIGHT}" stroke="{INK}" stroke-width="0.2"/>')
    out.append(f'<text x="95" y="{leg_y}" font-family="Helvetica,sans-serif" font-size="2.7" '
               f'fill="{INK}">热点区段(取响应密度 top-3)</text>')

    out.append(f'<text x="{W-12}" y="{leg_y-1}" font-family="Georgia,serif" font-size="2.5" '
               f'font-style="italic" fill="{INK_SOFT}" text-anchor="end">'
               f'n=941 agents (seed 43)  ·  pooled rate 22.7% (n=682/3000 across 3 seeds)</text>')
    out.append(f'<text x="{W-12}" y="{leg_y+3}" font-family="Georgia,serif" font-size="2.5" '
               f'font-style="italic" fill="{INK_SOFT}" text-anchor="end">'
               f'Source: Synthetic Socio Wind Tunnel · github.com/york-zhouuu</text>')
    out.append("</g>")

    out.append("</svg>")
    (OUT / "finding1_A_map_annotation.svg").write_text("\n".join(out))
    print("  → finding1_A_map_annotation.svg")


# ────────────────────────────────────────────────────────────
# MOCK-UP B · Split panel: big stat + chart on right, map on left
# ────────────────────────────────────────────────────────────
def mockup_B():
    """Split panel layout, FT-style.

    ┌─────────────────────┬────────────────────────────────────┐
    │                     │  FINDING 01 · BIG headline         │
    │                     │  Subtitle one-liner                │
    │                     │                                    │
    │   MAP with dots     │  ─────────────────────────────     │
    │                     │  22.7%                             │
    │                     │  (huge typographic display)        │
    │                     │  of 1000 residents physically      │
    │                     │  responded; 77.3% did not.         │
    │                     │                                    │
    │                     │  ───────── BREAKDOWN ──────        │
    │                     │  By occupation (top 6 bar chart)   │
    │                     │  By age (5 bar chart)              │
    │                     │                                    │
    │                     │  KEY: nobody partially responded   │
    │                     │  — all 682 respond ALL 6 days      │
    └─────────────────────┴────────────────────────────────────┘
    """
    W, H = 320, 220
    center = get_center()
    atlas = load_atlas()
    bldgs = get_buildings_near(atlas, center, 1000)
    streets, named = get_streets_near(atlas, center, 1000)
    agents = load_responder_data()
    resp = [a["home_xy"] for a in agents if a["is_responder"]]
    non = [a["home_xy"] for a in agents if not a["is_responder"]]

    out = []
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" '
               f'viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">')
    out.append(f'<rect width="100%" height="100%" fill="{BG_PAPER}"/>')

    # === LEFT: Map ===
    map_x, map_y, map_w, map_h = 10, 10, 160, 200
    cx_atlas, cy_atlas = center
    radius = 1000
    scale = min(map_w / (2 * radius), map_h / (2 * radius))
    def proj(x, y):
        sx = map_x + map_w / 2 + (x - cx_atlas) * scale
        sy = map_y + map_h / 2 - (y - cy_atlas) * scale
        return sx, sy

    out.append(f'<rect x="{map_x}" y="{map_y}" width="{map_w}" height="{map_h}" '
               f'fill="#F4F2EB" stroke="{INK_LIGHT}" stroke-width="0.2"/>')
    # streets
    out.append('<g opacity="0.55">')
    for _, c in streets:
        sx, sy = proj(c[0], c[1])
        out.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.22" fill="{INK_LIGHT}"/>')
    out.append("</g>")
    # buildings
    out.append('<g opacity="0.18">')
    for _, b, c in bldgs:
        sx, sy = proj(c[0], c[1])
        out.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.2" fill="{INK_LIGHT}"/>')
    out.append("</g>")
    # non-responders (grey dots)
    cx, cy = center
    out.append('<g>')
    for x, y in non:
        if (x-cx)**2 + (y-cy)**2 > 1000**2: continue
        sx, sy = proj(x, y)
        out.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.6" fill="{INK_LIGHT}" opacity="0.55"/>')
    out.append("</g>")
    # responders (red dots with halo)
    out.append('<g>')
    for x, y in resp:
        if (x-cx)**2 + (y-cy)**2 > 1000**2: continue
        sx, sy = proj(x, y)
        out.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="1.7" fill="{ACCENT_SOFT}" stroke="none"/>')
        out.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.9" fill="{ACCENT}" stroke="{INK}" stroke-width="0.08"/>')
    out.append("</g>")

    # map caption — bottom of map
    out.append(f'<text x="{map_x+2}" y="{map_y+map_h-2}" font-family="Georgia,serif" '
               f'font-size="2.5" font-style="italic" fill="{INK_SOFT}">'
               f'Lane Cove · 1000 居民的家 · 红 = 响应者 灰 = 非响应者 · seed 43</text>')

    # === RIGHT: Stats panel ===
    px = 180
    out.append(f'<text x="{px}" y="20" font-family="Georgia,serif" font-size="3.3" '
               f'font-style="italic" fill="{ACCENT_DARK}" letter-spacing="0.3">'
               f'FINDING 01 · 物理响应分布</text>')
    out.append(f'<text x="{px}" y="38" font-family="Georgia,serif" font-size="11" '
               f'font-weight="900" fill="{INK}" letter-spacing="-0.5">'
               f'推送来到楼下,人</text>')
    out.append(f'<text x="{px}" y="50" font-family="Georgia,serif" font-size="11" '
               f'font-weight="900" fill="{INK}" letter-spacing="-0.5">'
               f'会真的走出门吗?</text>')

    # HUGE STAT
    out.append(f'<line x1="{px}" y1="60" x2="{W-12}" y2="60" stroke="{INK}" stroke-width="0.5"/>')
    out.append(f'<text x="{px}" y="92" font-family="Georgia,serif" font-size="36" '
               f'font-weight="900" fill="{ACCENT}" letter-spacing="-2">22.7%</text>')
    out.append(f'<text x="{px}" y="102" font-family="Georgia,serif" font-size="4.5" '
               f'fill="{INK}">的居民物理位移 &gt; 20 米</text>')
    out.append(f'<text x="{px}" y="108" font-family="Georgia,serif" font-size="3.5" '
               f'fill="{INK_SOFT}" font-style="italic">中位 850 米 · 最大 3,121 米</text>')

    # Smaller contrast stat
    out.append(f'<text x="{px+90}" y="92" font-family="Georgia,serif" font-size="22" '
               f'font-weight="900" fill="{INK_LIGHT}" letter-spacing="-1">77.3%</text>')
    out.append(f'<text x="{px+90}" y="100" font-family="Georgia,serif" font-size="3.5" '
               f'fill="{INK_SOFT}">完全不为所动</text>')
    out.append(f'<text x="{px+90}" y="105" font-family="Georgia,serif" font-size="3" '
               f'fill="{INK_LIGHT}" font-style="italic">轨迹与基线完全重合</text>')

    out.append(f'<line x1="{px}" y1="115" x2="{W-12}" y2="115" stroke="{INK_LIGHT}" stroke-width="0.2"/>')

    # === BREAKDOWN bar chart ===
    out.append(f'<text x="{px}" y="123" font-family="Georgia,serif" font-size="3.3" '
               f'font-weight="700" fill="{INK}" letter-spacing="0.3">'
               f'谁是那 22.7%?</text>')
    out.append(f'<text x="{px}" y="128" font-family="Georgia,serif" font-size="2.8" '
               f'fill="{INK_SOFT}" font-style="italic">响应率(响应人数 / 该群体总人数)</text>')

    occs = [
        ("失业", 39.2, 97),
        ("退休", 37.2, 403),
        ("软件工程师", 24.2, 124),
        ("学生", 18.3, 668),
        ("零售员工", 11.0, 100),
        ("工程师", 8.0, 88),
    ]
    chart_x = px; chart_w = W - px - 12
    bar_x = chart_x + 30
    bar_max_w = chart_w - 35
    by = 135
    for occ, rate, n in occs:
        # name
        out.append(f'<text x="{chart_x+28}" y="{by+2.5}" font-family="Helvetica,sans-serif" '
                   f'font-size="3" fill="{INK}" text-anchor="end">{occ}</text>')
        # bar
        bw = (rate / 45) * bar_max_w
        color = ACCENT if rate > 25 else HIGHLIGHT if rate > 18 else INK_LIGHT
        out.append(f'<rect x="{bar_x}" y="{by}" width="{bw:.2f}" height="3" fill="{color}"/>')
        # value
        out.append(f'<text x="{bar_x + bw + 1.5}" y="{by+2.5}" font-family="Georgia,serif" '
                   f'font-size="3" font-weight="900" fill="{INK}">{rate:.1f}%</text>')
        out.append(f'<text x="{bar_x + bw + 11}" y="{by+2.5}" font-family="Georgia,serif" '
                   f'font-size="2.4" fill="{INK_LIGHT}">(n={n})</text>')
        by += 5.5

    # Key insight
    by = 175
    out.append(f'<line x1="{px}" y1="{by-3}" x2="{W-12}" y2="{by-3}" stroke="{INK_LIGHT}" stroke-width="0.2"/>')
    out.append(f'<text x="{px}" y="{by}" font-family="Georgia,serif" font-size="3.3" '
               f'font-weight="700" fill="{INK}" letter-spacing="0.3">'
               f'关键发现 · 响应是二元的,不是连续的</text>')
    out.append(f'<text x="{px}" y="{by+5}" font-family="Georgia,serif" font-size="3" '
               f'fill="{INK_SOFT}">同一个 agent 在 6 天干预期里:</text>')
    out.append(f'<text x="{px+3}" y="{by+10}" font-family="Helvetica,sans-serif" font-size="2.8" '
               f'fill="{INK}">  ·  <tspan fill="{ACCENT}" font-weight="900">682 人(22.7%)</tspan> 每一天都响应</text>')
    out.append(f'<text x="{px+3}" y="{by+14}" font-family="Helvetica,sans-serif" font-size="2.8" '
               f'fill="{INK}">  ·  <tspan fill="{INK_LIGHT}" font-weight="900">2,318 人(77.3%)</tspan> 每一天都不响应</text>')
    out.append(f'<text x="{px+3}" y="{by+18}" font-family="Helvetica,sans-serif" font-size="2.8" '
               f'fill="{INK}">  ·  <tspan fill="{ACCENT}" font-weight="900">0 人</tspan> 部分响应(1-5 天)</text>')

    # Source
    out.append(f'<text x="{W-12}" y="{H-3}" font-family="Georgia,serif" font-size="2.4" '
               f'font-style="italic" fill="{INK_SOFT}" text-anchor="end">'
               f'n=3,000 (pooled 3 seeds) · Synthetic Socio Wind Tunnel</text>')

    out.append("</svg>")
    (OUT / "finding1_B_split_panel.svg").write_text("\n".join(out))
    print("  → finding1_B_split_panel.svg")


# ────────────────────────────────────────────────────────────
# MOCK-UP C · 4-panel storyboard (cause → effect sequence)
# ────────────────────────────────────────────────────────────
def mockup_C():
    """4-panel horizontal storyboard.

    ┌────────┬────────┬────────┬────────┐
    │ DAY 0  │ DAY 4  │ DAY 7  │ DAY 9  │
    │ Pre    │ Push   │ Effect │ Plateau│
    │ all    │ starts │ 23% out│ stable │
    │ home   │        │        │        │
    └────────┴────────┴────────┴────────┘
    Below: data — small map row + stat row
    """
    W, H = 320, 220
    center = get_center()
    atlas = load_atlas()
    bldgs = get_buildings_near(atlas, center, 1100)
    agents = load_responder_data()
    resp = [a["home_xy"] for a in agents if a["is_responder"]]
    non = [a["home_xy"] for a in agents if not a["is_responder"]]

    out = []
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" '
               f'viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">')
    out.append(f'<rect width="100%" height="100%" fill="{BG_PAPER}"/>')

    # Header
    out.append(f'<text x="12" y="14" font-family="Georgia,serif" font-size="3.3" '
               f'font-style="italic" fill="{ACCENT_DARK}" letter-spacing="0.3">'
               f'FINDING 01 · 14 天里发生了什么</text>')
    out.append(f'<text x="12" y="30" font-family="Georgia,serif" font-size="11" '
               f'font-weight="900" fill="{INK}" letter-spacing="-0.5">'
               f'推送 → 23% 走出门 → 6 天内稳定 → 不再变化</text>')
    out.append(f'<text x="12" y="38" font-family="Georgia,serif" font-size="4" '
               f'font-style="italic" fill="{INK_SOFT}">'
               f'同一群 1000 居民,4 个时间快照,看「响应人群」如何形成 + 锁定</text>')

    out.append(f'<line x1="12" y1="44" x2="{W-12}" y2="44" stroke="{INK}" stroke-width="0.4"/>')

    # 4 panels
    panel_y = 50
    panel_h = 130
    panel_w = (W - 24 - 9) / 4  # 3 gaps of 3mm
    days = [(0, "DAY 0", "BASELINE", "all 1000 agents follow their baseline schedule"),
            (4, "DAY 4", "INTERVENTION DAY 1", "push begins — 5 hyperlocal items / day"),
            (7, "DAY 7", "INTERVENTION DAY 4", "682 agents have shifted; 2318 unchanged"),
            (9, "DAY 9", "INTERVENTION DAY 6", "system at new equilibrium; same 682 every day")]
    cx_atlas, cy_atlas = center
    cx, cy = center

    for i, (day, label_top, label_sub, label_desc) in enumerate(days):
        px = 12 + i * (panel_w + 3)

        # Panel border
        out.append(f'<rect x="{px}" y="{panel_y}" width="{panel_w}" height="{panel_h}" '
                   f'fill="#F4F2EB" stroke="{INK_LIGHT}" stroke-width="0.2"/>')

        # Panel header
        out.append(f'<rect x="{px}" y="{panel_y}" width="{panel_w}" height="11" fill="{INK}"/>')
        out.append(f'<text x="{px+panel_w/2}" y="{panel_y+5}" font-family="Georgia,serif" '
                   f'font-size="3.3" font-style="italic" fill="{HIGHLIGHT}" letter-spacing="0.3" text-anchor="middle">'
                   f'{label_sub}</text>')
        out.append(f'<text x="{px+panel_w/2}" y="{panel_y+9.5}" font-family="Georgia,serif" '
                   f'font-size="5.5" font-weight="900" fill="white" text-anchor="middle">{label_top}</text>')

        # Map mini area
        mx = px + 2; my = panel_y + 13
        mw = panel_w - 4; mh = 80
        out.append(f'<rect x="{mx}" y="{my}" width="{mw}" height="{mh}" fill="white"/>')
        scale = min(mw / (2200), mh / (2200))
        def proj_p(x, y):
            sx = mx + mw/2 + (x - cx_atlas) * scale
            sy = my + mh/2 - (y - cy_atlas) * scale
            return sx, sy

        # buildings as light dots
        for _, b, c in bldgs[::4]:
            sx, sy = proj_p(c[0], c[1])
            out.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.15" fill="{INK_LIGHT}" opacity="0.5"/>')

        # Dots logic per day
        if day == 0:
            # all agents grey (no response yet)
            for x, y in resp + non:
                if (x-cx)**2 + (y-cy)**2 > 1100**2: continue
                sx, sy = proj_p(x, y)
                out.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.45" fill="{INK_LIGHT}" opacity="0.7"/>')
        elif day == 4:
            # mix: some starting to turn pink
            for x, y in non:
                if (x-cx)**2 + (y-cy)**2 > 1100**2: continue
                sx, sy = proj_p(x, y)
                out.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.45" fill="{INK_LIGHT}" opacity="0.6"/>')
            # half of responders pink, half still grey (transition state)
            for j, (x, y) in enumerate(resp):
                if (x-cx)**2 + (y-cy)**2 > 1100**2: continue
                sx, sy = proj_p(x, y)
                if j % 2:
                    out.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.7" fill="{ACCENT}" opacity="0.85"/>')
                else:
                    out.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.55" fill="{INK_LIGHT}" opacity="0.65"/>')
        else:
            # day 7+ full bimodal
            for x, y in non:
                if (x-cx)**2 + (y-cy)**2 > 1100**2: continue
                sx, sy = proj_p(x, y)
                out.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.4" fill="{INK_LIGHT}" opacity="0.55"/>')
            for x, y in resp:
                if (x-cx)**2 + (y-cy)**2 > 1100**2: continue
                sx, sy = proj_p(x, y)
                out.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.8" fill="{ACCENT}" opacity="0.9"/>')

        # Below map: stats for that day
        sy_text = my + mh + 5
        stats = [
            (0, "100%", "正在 home base", "0%", "未响应"),
            (4, "—", "推送启动", "~12%", "首批离家"),
            (7, "23%", "在新位置", "0%", "新响应者"),
            (9, "23%", "锁定", "0%", "无新响应"),
        ]
        for d_t, big_l, big_lbl, small_v, small_lbl in stats:
            if d_t != day: continue
            color = ACCENT if d_t >= 7 else HIGHLIGHT if d_t == 4 else INK_LIGHT
            out.append(f'<text x="{px+panel_w/2}" y="{sy_text+5}" font-family="Georgia,serif" '
                       f'font-size="11" font-weight="900" fill="{color}" text-anchor="middle">{big_l}</text>')
            out.append(f'<text x="{px+panel_w/2}" y="{sy_text+10}" font-family="Georgia,serif" '
                       f'font-size="2.5" fill="{INK}" text-anchor="middle">{big_lbl}</text>')
            # 1-line descriptor
            out.append(f'<text x="{px+panel_w/2}" y="{sy_text+20}" font-family="Georgia,serif" '
                       f'font-size="2.6" fill="{INK_SOFT}" font-style="italic" text-anchor="middle">{label_desc[:32]}</text>')
            if len(label_desc) > 32:
                out.append(f'<text x="{px+panel_w/2}" y="{sy_text+24}" font-family="Georgia,serif" '
                           f'font-size="2.6" fill="{INK_SOFT}" font-style="italic" text-anchor="middle">{label_desc[32:64]}</text>')

    # Below 4 panels: key conclusion banner
    by = panel_y + panel_h + 8
    out.append(f'<rect x="12" y="{by}" width="{W-24}" height="14" fill="{ACCENT}"/>')
    out.append(f'<text x="{W/2}" y="{by+6}" font-family="Georgia,serif" font-size="4.5" '
               f'font-style="italic" fill="white" text-anchor="middle">⏎  KEY OBSERVATION</text>')
    out.append(f'<text x="{W/2}" y="{by+12}" font-family="Georgia,serif" font-size="5.5" '
               f'font-weight="900" fill="white" text-anchor="middle">'
               f'同一群人,每天响应;新的响应者从未加入。22.7% 是稳定 cohort,不是滚动样本。</text>')

    # Source
    out.append(f'<text x="{W-12}" y="{H-2}" font-family="Georgia,serif" font-size="2.4" '
               f'font-style="italic" fill="{INK_SOFT}" text-anchor="end">'
               f'1,000 agents × 3 seeds (n=3,000 pooled) · Lane Cove · Synthetic Socio Wind Tunnel</text>')

    out.append("</svg>")
    (OUT / "finding1_C_storyboard.svg").write_text("\n".join(out))
    print("  → finding1_C_storyboard.svg")


def main():
    print("Building 3 mock-ups for Finding 1 (22.7% bimodal response)...")
    print(f"Output: {OUT}/")
    mockup_A()
    mockup_B()
    mockup_C()
    print("\nDone. Open each in browser to compare:")
    print(f"  open {OUT}/finding1_A_map_annotation.svg")
    print(f"  open {OUT}/finding1_B_split_panel.svg")
    print(f"  open {OUT}/finding1_C_storyboard.svg")


if __name__ == "__main__":
    main()
