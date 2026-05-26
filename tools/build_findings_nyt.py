"""Build 8 NYT/FT-style finding figures (Mock A style).

Each figure (320 × 220 mm):
  ┌─────────────────────────────────────────────────────┐
  │ KICKER · FINDING N · Synthetic Socio Wind Tunnel    │
  │ BIG NYT HEADLINE with one accent number             │
  │ Subtitle one-liner                                  │
  ├──────────────────────────────────────┬──────────────┤
  │                                      │ ① Annotation │
  │  Lane Cove map (real polygons)       │   text       │
  │  with finding-specific overlay       │              │
  │  (dots / rings / arcs / heatmap)     │ ② Annotation │
  │  + named streets                     │   text       │
  │  + 3 numbered callouts               │              │
  │                                      │ ③ Annotation │
  ├──────────────────────────────────────┴──────────────┤
  │ Legend · Source · n=...                             │
  └─────────────────────────────────────────────────────┘
"""
from __future__ import annotations
import json
import math
from collections import defaultdict
from pathlib import Path

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
ATLAS = REPO / "data/lanecove_atlas.json"
ANALYSIS = REPO / "data/analysis/2026-05-23_paper_exploration"
OUT = REPO / "docs/figures_nyt"
OUT.mkdir(parents=True, exist_ok=True)

# Palette
INK = "#1B1F2A"
INK_SOFT = "#5A5E6A"
INK_LIGHT = "#A8ACB5"
BG_PAPER = "#FFFFFF"
BG_MAP = "#F5F2EA"
ACCENT = "#E03A4A"
ACCENT_SOFT = "#FBD8DC"
ACCENT_DARK = "#A0252F"
HIGHLIGHT = "#F0C419"
HIGHLIGHT_SOFT = "#FFF4C7"
GREY = "#D8D9DC"
BLUE = "#3B6EA8"
BLUE_SOFT = "#C7D5E5"
GREEN = "#3A9D5C"

W, H = 320, 220  # mm, ~A4 landscape feel,4 fit on A1 portrait

KEY_STREETS = ["Longueville Road", "Mowbray Road", "Burns Bay Road",
               "Epping Road", "Pacific Highway", "River Road",
               "Centennial Avenue", "Cowper Street", "Pottery Lane"]


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


def in_radius(x, y, cx, cy, r):
    return (x-cx)**2 + (y-cy)**2 <= r**2


# ──────────────────────────────────────────────────────────────────────
# Map renderer — uses real polygons, not centroids
# ──────────────────────────────────────────────────────────────────────
class FlatMap:
    """Renders Lane Cove as 2D top-down map with real building/street polygons."""
    def __init__(self, x, y, w, h, center, radius=1100):
        self.x = x; self.y = y; self.w = w; self.h = h
        self.cx, self.cy = center
        self.r = radius
        # Scale to fit
        self.scale = min(w / (2 * radius), h / (2 * radius))

    def proj(self, atlas_x, atlas_y):
        sx = self.x + self.w / 2 + (atlas_x - self.cx) * self.scale
        sy = self.y + self.h / 2 - (atlas_y - self.cy) * self.scale
        return sx, sy

    def in_view(self, atlas_x, atlas_y):
        sx, sy = self.proj(atlas_x, atlas_y)
        return self.x <= sx <= self.x+self.w and self.y <= sy <= self.y+self.h

    def render_base(self, atlas):
        parts = []
        # Background panel
        parts.append(f'<rect x="{self.x}" y="{self.y}" width="{self.w}" height="{self.h}" '
                     f'fill="{BG_MAP}"/>')
        # Streets as light grey lines (using polygon path of street strips)
        parts.append('<g id="streets">')
        outdoor = atlas.get("outdoor_areas", {})
        items = outdoor.values() if isinstance(outdoor, dict) else outdoor
        for o in items:
            atype = (o.get("area_type") or "").lower()
            if atype != "street": continue
            verts = o.get("polygon", {}).get("vertices", [])
            if len(verts) < 3: continue
            c = centroid(verts)
            if not c or not in_radius(c[0], c[1], self.cx, self.cy, self.r + 100):
                continue
            pts = [self.proj(v["x"], v["y"]) for v in verts]
            path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in pts) + " Z"
            parts.append(f'<path d="{path}" fill="{INK_LIGHT}" fill-opacity="0.5" stroke="none"/>')
        parts.append("</g>")

        # Parks/playgrounds as soft green
        parts.append('<g id="parks">')
        for o in items:
            atype = (o.get("area_type") or "").lower()
            if atype not in ("park", "playground", "garden"): continue
            verts = o.get("polygon", {}).get("vertices", [])
            if len(verts) < 3: continue
            c = centroid(verts)
            if not c or not in_radius(c[0], c[1], self.cx, self.cy, self.r + 100):
                continue
            pts = [self.proj(v["x"], v["y"]) for v in verts]
            path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in pts) + " Z"
            parts.append(f'<path d="{path}" fill="#D5E8C8" fill-opacity="0.7" stroke="none"/>')
        parts.append("</g>")

        # Buildings as very light grey polygons
        parts.append('<g id="bldgs">')
        for aid, b in atlas["buildings"].items():
            verts = b.get("polygon", {}).get("vertices", [])
            if len(verts) < 3: continue
            c = centroid(verts)
            if not c or not in_radius(c[0], c[1], self.cx, self.cy, self.r):
                continue
            pts = [self.proj(v["x"], v["y"]) for v in verts]
            path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in pts) + " Z"
            btype = (b.get("building_type") or "").lower()
            if btype == "residential":
                fill = "#E8E2D8"
            elif btype in ("school","hospital","worship","community","entertainment"):
                fill = "#D4C5E0"
            elif btype in ("cafe","restaurant","bar","shop","commercial"):
                fill = "#F0D9C0"
            else:
                fill = "#E0E0DC"
            parts.append(f'<path d="{path}" fill="{fill}" stroke="{INK_LIGHT}" stroke-width="0.04" fill-opacity="0.95"/>')
        parts.append("</g>")
        return parts

    def render_streets_labels(self, atlas):
        """Label key streets as italic serif text with halo."""
        parts = ['<g id="street-labels">']
        outdoor = atlas.get("outdoor_areas", {})
        items = outdoor.values() if isinstance(outdoor, dict) else outdoor
        named = defaultdict(list)
        for o in items:
            if (o.get("area_type") or "").lower() != "street": continue
            rd = o.get("road_name")
            if not rd or rd not in KEY_STREETS: continue
            c = centroid(o.get("polygon", {}).get("vertices", []))
            if c and in_radius(c[0], c[1], self.cx, self.cy, self.r - 50):
                named[rd].append(c)
        for rd_name, locs in named.items():
            xs = [c[0] for c in locs]; ys = [c[1] for c in locs]
            mx, my = sum(xs)/len(xs), sum(ys)/len(ys)
            sx, sy = self.proj(mx, my)
            if not (self.x+5 < sx < self.x+self.w-5 and self.y+5 < sy < self.y+self.h-5):
                continue
            # White halo + ink text
            parts.append(f'<text x="{sx:.2f}" y="{sy:.2f}" font-family="Georgia,serif" '
                         f'font-size="2.5" font-weight="700" font-style="italic" '
                         f'fill="{INK}" text-anchor="middle" stroke="{BG_MAP}" '
                         f'stroke-width="0.7" paint-order="stroke" opacity="0.85">{rd_name}</text>')
        parts.append("</g>")
        return parts


# ──────────────────────────────────────────────────────────────────────
# Shared header/footer
# ──────────────────────────────────────────────────────────────────────
def svg_open():
    return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" '
            f'viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">',
            f'<rect width="100%" height="100%" fill="{BG_PAPER}"/>']


def header(idx, accent_word, headline_left, headline_right, subhead):
    """Top header band: kicker + 2-line headline + subhead.

    headline format: "<plain> <ACCENT WORD> <plain>" with ACCENT word in red.
    """
    parts = []
    # Kicker line
    parts.append(f'<text x="12" y="14" font-family="Georgia,serif" font-size="3.3" '
                 f'font-style="italic" fill="{ACCENT_DARK}" letter-spacing="0.3">'
                 f'FINDING {idx:02d}  ·  Synthetic Socio Wind Tunnel  ·  Lane Cove, Sydney</text>')
    parts.append(f'<line x1="12" y1="17" x2="{W-12}" y2="17" stroke="{ACCENT_DARK}" stroke-width="0.3"/>')
    # Big headline (could span 2 lines)
    parts.append(f'<text x="12" y="32" font-family="Georgia,serif" font-size="13" '
                 f'font-weight="900" fill="{INK}" letter-spacing="-0.5">'
                 f'{headline_left} <tspan fill="{ACCENT}">{accent_word}</tspan> {headline_right}</text>')
    # Subhead
    parts.append(f'<text x="12" y="42" font-family="Georgia,serif" font-size="4.5" '
                 f'font-style="italic" fill="{INK_SOFT}">{subhead}</text>')
    return parts


def footer(legend_items, source_text):
    """Bottom footer: legend on left, source on right.

    legend_items: list of (color, label) tuples
    """
    parts = []
    fy = H - 10
    lx = 12
    for color, label in legend_items:
        if color.startswith("ring"):
            # special: dashed ring
            parts.append(f'<circle cx="{lx+1.5}" cy="{fy-1}" r="1.5" fill="none" '
                         f'stroke="{color[5:]}" stroke-width="0.3" stroke-dasharray="0.7 0.4"/>')
        elif color.startswith("triangle"):
            parts.append(f'<polygon points="{lx},{fy-2.2} {lx+2.5},{fy-2.2} {lx+1.25},{fy+0.2}" fill="{color[9:]}"/>')
        else:
            parts.append(f'<circle cx="{lx+1.3}" cy="{fy-1}" r="1.3" fill="{color}"/>')
        parts.append(f'<text x="{lx+4}" y="{fy}" font-family="Helvetica,sans-serif" font-size="2.7" '
                     f'fill="{INK}">{label}</text>')
        lx += 6 + 3.5 * len(label) * 0.45  # rough advance per char
    parts.append(f'<text x="{W-12}" y="{fy}" font-family="Georgia,serif" font-size="2.6" '
                 f'font-style="italic" fill="{INK_SOFT}" text-anchor="end">{source_text}</text>')
    parts.append(f'<text x="{W-12}" y="{fy+3.5}" font-family="Georgia,serif" font-size="2.4" '
                 f'font-style="italic" fill="{INK_LIGHT}" text-anchor="end">'
                 f'Source: Synthetic Socio Wind Tunnel · github.com/york-zhouuu</text>')
    return parts


def annotation_block(idx, x, y, title, body_lines):
    """Numbered annotation block on the side. body_lines: list of strings."""
    parts = []
    # Yellow circle marker
    parts.append(f'<circle cx="{x+3}" cy="{y}" r="2.8" fill="{HIGHLIGHT}" stroke="{INK}" stroke-width="0.35"/>')
    parts.append(f'<text x="{x+3}" y="{y+1}" font-family="Georgia,serif" font-size="3.6" '
                 f'font-weight="900" fill="{INK}" text-anchor="middle">{idx}</text>')
    # Title
    parts.append(f'<text x="{x+8}" y="{y-1}" font-family="Georgia,serif" font-size="4" '
                 f'font-weight="900" fill="{INK}">{title}</text>')
    # Body lines
    for i, line in enumerate(body_lines):
        parts.append(f'<text x="{x+8}" y="{y+3 + i*3.5}" font-family="Georgia,serif" font-size="3" '
                     f'fill="{INK_SOFT}">{line}</text>')
    return parts


def callout_marker(map: FlatMap, idx, atlas_x, atlas_y, target_text_xy=None):
    """Yellow numbered circle on map + optional dashed line to side text."""
    sx, sy = map.proj(atlas_x, atlas_y)
    parts = []
    parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="3" '
                 f'fill="{HIGHLIGHT}" stroke="{INK}" stroke-width="0.4"/>')
    parts.append(f'<text x="{sx:.2f}" y="{sy+1.1:.2f}" font-family="Georgia,serif" '
                 f'font-size="3.8" font-weight="900" fill="{INK}" text-anchor="middle">{idx}</text>')
    if target_text_xy:
        tx, ty = target_text_xy
        parts.append(f'<line x1="{sx+3:.2f}" y1="{sy:.2f}" x2="{tx-2:.2f}" y2="{ty:.2f}" '
                     f'stroke="{INK_SOFT}" stroke-width="0.25" stroke-dasharray="0.8 0.5"/>')
    return parts


# ──────────────────────────────────────────────────────────────────────
# Common: load responder data (seed 43 for richest visual)
# ──────────────────────────────────────────────────────────────────────
def load_responders_seed(seed=43):
    with open(ANALYSIS / "C_responder_profile/agents_hyperlocal_push.json") as f:
        agents = json.load(f)
    return [a for a in agents if a["seed"] == seed and a.get("home_xy") and a["home_xy"][0] is not None]


def write(name, parts):
    parts.append("</svg>")
    path = OUT / name
    path.write_text("\n".join(parts))
    print(f"  → {path.name}")


# ──────────────────────────────────────────────────────────────────────
# Finding 1: Bimodal 22.7%
# ──────────────────────────────────────────────────────────────────────
def fig1():
    center = get_center()
    atlas = load_atlas()
    agents = load_responders_seed(43)
    resp = [a["home_xy"] for a in agents if a["is_responder"]]
    non = [a["home_xy"] for a in agents if not a["is_responder"]]

    parts = svg_open()
    parts.extend(header(1, "22.7%",
        "当推送来到楼下,只有",
        "的人真的走出门。",
        "剩下 77.3% 的居民完全不为所动 — 干预效果不是渐变,是二元筛选。"))

    fm = FlatMap(12, 50, 200, 145, center, radius=1100)
    parts.extend(fm.render_base(atlas))

    # Non-responders as soft grey dots
    parts.append('<g id="non-resp">')
    cx, cy = center
    for x, y in non:
        if not in_radius(x, y, cx, cy, 1100): continue
        sx, sy = fm.proj(x, y)
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.55" fill="{INK_SOFT}" opacity="0.45"/>')
    parts.append("</g>")

    # Responders as red dots with halo
    parts.append('<g id="resp">')
    for x, y in resp:
        if not in_radius(x, y, cx, cy, 1100): continue
        sx, sy = fm.proj(x, y)
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="2" fill="{ACCENT_SOFT}" opacity="0.7"/>')
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="1.1" fill="{ACCENT}" stroke="{INK}" stroke-width="0.12"/>')
    parts.append("</g>")

    parts.extend(fm.render_streets_labels(atlas))

    # Find top 3 cluster centers
    grid = defaultdict(list)
    for x, y in resp:
        if not in_radius(x, y, cx, cy, 1100): continue
        gx, gy = int((x - cx + 1100) // 150), int((y - cy + 1100) // 150)
        grid[(gx, gy)].append((x, y))
    top3 = sorted(grid.items(), key=lambda kv: -len(kv[1]))[:3]
    callout_text_y = [60, 95, 130]
    text_x = 220
    for i, ((gx, gy), pts), ty in zip(range(1, 4), top3, callout_text_y):
        mx = sum(p[0] for p in pts)/len(pts)
        my = sum(p[1] for p in pts)/len(pts)
        parts.extend(callout_marker(fm, i, mx, my, target_text_xy=(text_x, ty)))

    # Side annotations
    annots = [
        ("响应密集区", ["响应率约 28% — 远高于", "整体平均 22.7%", "退休 + 自由职业聚集"]),
        ("中心商业区", ["响应率约 22% — 接近", "整体平均水平", "anchor POI 周围"]),
        ("外围街区", ["响应率约 12%", "schedule-bound 工人 +", "学生 + 通勤者占多数"]),
    ]
    for idx, (title, body), ty in zip(range(1, 4), annots, callout_text_y):
        parts.extend(annotation_block(idx, text_x, ty, title, body))

    parts.extend(footer([
        (ACCENT, "响应者 (位移>20m,n=490)"),
        (INK_SOFT, "非响应者 (n=451)"),
        (HIGHLIGHT, "热点区段 (响应密度 top-3)"),
    ], "n=941 (seed 43) · pooled 22.7% across 3 seeds"))

    write("finding_01_bimodal.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# Finding 2: Spillover 200m
# ──────────────────────────────────────────────────────────────────────
def fig2():
    center = get_center()
    atlas = load_atlas()
    agents = load_responders_seed(43)
    cx, cy = center

    parts = svg_open()
    parts.extend(header(2, "8 倍",
        "不收推送的邻居,因为响应者在身边而",
        "更可能响应。",
        "200 米内有响应者邻居 → 响应率 26%;200 米外 → 4%。空间机制清晰。"))

    fm = FlatMap(12, 50, 200, 145, center, radius=1000)
    parts.extend(fm.render_base(atlas))
    parts.extend(fm.render_streets_labels(atlas))

    # Top 15 protag-responders by neighbor density — draw 200m rings
    protag_resp = [a for a in agents if a["is_protagonist"] and a["is_responder"]]
    scored = []
    for c in protag_resp:
        x, y = c["home_xy"]
        n_near = sum(1 for o in protag_resp if o is not c
                     and (o["home_xy"][0]-x)**2 + (o["home_xy"][1]-y)**2 <= 200**2)
        scored.append((n_near, c))
    scored.sort(key=lambda t: -t[0])
    top = [c for _, c in scored[:18]]

    parts.append('<g id="rings">')
    for c in top:
        x, y = c["home_xy"]
        if not in_radius(x, y, cx, cy, 950): continue
        sx, sy = fm.proj(x, y)
        rr = 200 * fm.scale
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{rr:.2f}" '
                     f'fill="{ACCENT}" fill-opacity="0.06" stroke="{ACCENT}" '
                     f'stroke-width="0.3" stroke-dasharray="1.2 0.8"/>')
    parts.append("</g>")

    # Protag-responder dots
    parts.append('<g id="protag-resp">')
    for c in top:
        x, y = c["home_xy"]
        if not in_radius(x, y, cx, cy, 950): continue
        sx, sy = fm.proj(x, y)
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="1.5" '
                     f'fill="{ACCENT}" stroke="{INK}" stroke-width="0.2"/>')
    parts.append("</g>")

    # 3 callouts: pick 3 high-density rings
    text_x = 220
    callout_text_y = [60, 100, 140]
    for i, c, ty in zip(range(1, 4), top[:3], callout_text_y):
        x, y = c["home_xy"]
        parts.extend(callout_marker(fm, i, x, y, target_text_xy=(text_x, ty)))

    # Inset: distance-decay mini bar chart
    bi_x, bi_y, bi_w, bi_h = 220, 105, 90, 70
    parts.append(f'<rect x="{bi_x}" y="{bi_y}" width="{bi_w}" height="{bi_h}" '
                 f'fill="{BG_PAPER}" stroke="{INK_LIGHT}" stroke-width="0.2"/>')
    parts.append(f'<text x="{bi_x + bi_w/2}" y="{bi_y+5}" font-family="Georgia,serif" '
                 f'font-size="3" font-weight="900" fill="{INK}" text-anchor="middle">'
                 f'距离衰减 · 邻居响应率</text>')
    parts.append(f'<text x="{bi_x + bi_w/2}" y="{bi_y+8.5}" font-family="Georgia,serif" '
                 f'font-size="2.4" font-style="italic" fill="{INK_SOFT}" text-anchor="middle">'
                 f'非 protag 离最近响应者的距离 vs 响应率</text>')

    bars = [("0-50", 26.2, ACCENT), ("50-100", 20.6, ACCENT),
            ("100-150", 11.4, ACCENT_DARK), ("150-200", 4.3, INK_SOFT),
            ("200-300", 4.4, INK_SOFT), ("300-400", 2.0, INK_SOFT),
            ("400+", 0.0, INK_LIGHT)]
    plot_x = bi_x + 4; plot_w = bi_w - 8
    plot_y = bi_y + 13; plot_h = bi_h - 22
    bar_w = plot_w / len(bars) - 0.4
    max_v = 30
    for j, (lbl, v, color) in enumerate(bars):
        h = (v / max_v) * plot_h
        x0 = plot_x + j * (plot_w / len(bars))
        y0 = plot_y + plot_h - h
        parts.append(f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{bar_w:.2f}" height="{h:.2f}" fill="{color}"/>')
        parts.append(f'<text x="{x0 + bar_w/2:.2f}" y="{y0-0.3:.2f}" font-family="Helvetica,sans-serif" '
                     f'font-size="1.9" font-weight="700" fill="{INK}" text-anchor="middle">{v:.0f}%</text>')
        parts.append(f'<text x="{x0 + bar_w/2:.2f}" y="{plot_y + plot_h + 2.5:.2f}" font-family="Helvetica,sans-serif" '
                     f'font-size="1.6" fill="{INK_LIGHT}" text-anchor="middle">{lbl}</text>')
    # Annotation arrow on the inset
    cliff_x = plot_x + 3.5 * (plot_w / len(bars))
    parts.append(f'<line x1="{cliff_x-3:.2f}" y1="{plot_y+plot_h-12:.2f}" x2="{cliff_x:.2f}" y2="{plot_y+plot_h-3:.2f}" '
                 f'stroke="{ACCENT_DARK}" stroke-width="0.4"/>')
    parts.append(f'<text x="{cliff_x-5:.2f}" y="{plot_y+plot_h-14:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.2" font-style="italic" font-weight="700" fill="{ACCENT_DARK}" text-anchor="end">'
                 f'cliff at 150m</text>')

    # Side annotations
    annots = [
        ("一个示例环", ["响应者中心,200米虚线环", "环内 ~57% 居民也响应了"]),
        ("环外密度对比", ["200-600米范围内", "响应率降到 ~49%"]),
        ("机制清晰", ["邻居响应 → 楼下事件相遇 →", "可见 + 模仿 → 自己也响应"]),
    ]
    for idx, (title, body), ty in zip(range(1, 4), annots, callout_text_y):
        parts.extend(annotation_block(idx, text_x, ty, title, body))

    parts.extend(footer([
        (ACCENT, "Protag-responder (n=18 示例)"),
        ("ringE03A4A", "200 米邻居传染半径"),
    ], "n=1,392 non-protag analyzed · 3 seeds pooled"))

    write("finding_02_spillover.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# Finding 3: Repeat encounters 4.1×
# ──────────────────────────────────────────────────────────────────────
def fig3():
    center = get_center()
    atlas = load_atlas()
    cx, cy = center

    parts = svg_open()
    parts.extend(header(3, "4.1 倍",
        "同一对邻居在 14 天里见到对方的次数",
        "— 弱关系沉淀为强关系。",
        "推送不让你认识新陌生人。它让你和已经在附近的人,见面更频繁。"))

    fm = FlatMap(12, 50, 200, 145, center, radius=1100)
    parts.extend(fm.render_base(atlas))
    parts.extend(fm.render_streets_labels(atlas))

    # Top hot dwell locations from activation data
    with open(ANALYSIS / "A_poi_activation/activation_per_location.json") as f:
        a_data = json.load(f)
    hp_acts = [a for a in a_data["activation_vs_baseline"]["hyperlocal_push"].values()
               if a["variant_mean"] > 5000]
    hp_acts.sort(key=lambda r: -r["variant_mean"])

    # Heatmap circles at hot locations
    parts.append('<g id="hot-spots">')
    max_d = max(a["variant_mean"] for a in hp_acts[:40])
    for a in hp_acts[:40]:
        if a["x"] is None: continue
        x, y = a["x"], a["y"]
        if not in_radius(x, y, cx, cy, 1100): continue
        sx, sy = fm.proj(x, y)
        ratio = a["variant_mean"] / max_d
        r = 1 + ratio * 5
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{r*1.5:.2f}" fill="{ACCENT}" fill-opacity="0.18"/>')
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{r:.2f}" fill="{ACCENT}" fill-opacity="0.55" stroke="{INK}" stroke-width="0.12"/>')
    parts.append("</g>")

    # Callouts for top 3 with real names
    with open(ANALYSIS / "DEEP_MINING/specific_pois.json") as f:
        sp = json.load(f)
    top_named = sp["top_activated"][:5]
    text_x = 220
    callout_text_y = [60, 95, 130]
    idx = 1
    pos_used = []
    for p in top_named:
        if idx > 3: break
        loc = p["loc_id"]
        b = atlas["buildings"].get(loc) or (atlas["outdoor_areas"].get(loc) if isinstance(atlas["outdoor_areas"], dict) else None)
        if not b: continue
        c = centroid(b.get("polygon", {}).get("vertices", []))
        if not c or not in_radius(c[0], c[1], cx, cy, 1050): continue
        parts.extend(callout_marker(fm, idx, c[0], c[1], target_text_xy=(text_x, callout_text_y[idx-1])))
        pos_used.append((idx, p))
        idx += 1

    annots = []
    for i, p in pos_used:
        name = p.get("name") or p["loc_id"]
        if len(name) > 24: name = name[:22] + "…"
        annots.append((name, [
            f'{p.get("type","?")} · {p["activation_pct"]:+.0f}% 激活',
            f'基线 {p["bl_dwell_ticks"]:,} → HP {p["hp_dwell_ticks"]:,}',
            "高频共处 → 关系沉淀",
        ]))
    while len(annots) < 3:
        annots.append(("—", []))
    for idx, (title, body), ty in zip(range(1, 4), annots, callout_text_y):
        parts.extend(annotation_block(idx, text_x, ty, title, body))

    # Inset: 4-variant bar chart
    bi_x, bi_y, bi_w, bi_h = 220, 165, 90, 30
    parts.append(f'<rect x="{bi_x}" y="{bi_y}" width="{bi_w}" height="{bi_h}" '
                 f'fill="{BG_PAPER}" stroke="{INK_LIGHT}" stroke-width="0.2"/>')
    parts.append(f'<text x="{bi_x + bi_w/2}" y="{bi_y+4}" font-family="Georgia,serif" '
                 f'font-size="3" font-weight="900" fill="{INK}" text-anchor="middle">'
                 f'平均每对邻居 14 天相遇次数</text>')
    bars = [("BL", 17.3, INK_SOFT), ("HP", 71.1, ACCENT),
            ("GD", 23.8, BLUE), ("PF", 69.1, GREEN)]
    plot_x = bi_x + 5; plot_w = bi_w - 10
    plot_y = bi_y + 7; plot_h = bi_h - 13
    bar_w = plot_w / len(bars) - 1
    max_v = 80
    for j, (lbl, v, color) in enumerate(bars):
        h = (v / max_v) * plot_h
        x0 = plot_x + j * (plot_w / len(bars))
        y0 = plot_y + plot_h - h
        parts.append(f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{bar_w:.2f}" height="{h:.2f}" fill="{color}"/>')
        parts.append(f'<text x="{x0 + bar_w/2:.2f}" y="{y0-0.3:.2f}" font-family="Helvetica,sans-serif" '
                     f'font-size="2.4" font-weight="900" fill="{INK}" text-anchor="middle">{v:.1f}</text>')
        parts.append(f'<text x="{x0 + bar_w/2:.2f}" y="{plot_y + plot_h + 2.5:.2f}" font-family="Helvetica,sans-serif" '
                     f'font-size="2" font-weight="700" fill="{INK}" text-anchor="middle">{lbl}</text>')

    parts.extend(footer([
        (ACCENT, "高频共处地点 (半径 ∝ dwell ticks)"),
    ], "Top 40 locations · HP variant · 3 seeds pooled"))

    write("finding_03_repeat.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# Finding 4: Post-period compounding
# ──────────────────────────────────────────────────────────────────────
def fig4():
    center = get_center()
    atlas = load_atlas()

    parts = svg_open()
    parts.extend(header(4, "1.32×",
        "推送停了之后,偶遇量仍在",
        "增长。",
        "干预 day 4-9,后撤 day 10-13。后撤期 HP 偶遇量是干预期的 1.32 倍 — 网络效应自维持。"))

    # Left: small map with day 13 final responder positions
    fm = FlatMap(12, 50, 120, 145, center, radius=1100)
    parts.extend(fm.render_base(atlas))

    agents = load_responders_seed(43)
    cx, cy = center
    # Plot non as small dots, responders as bright
    for x, y in [a["home_xy"] for a in agents if not a["is_responder"]]:
        if not in_radius(x, y, cx, cy, 1100): continue
        sx, sy = fm.proj(x, y)
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.45" fill="{INK_LIGHT}" opacity="0.5"/>')
    for x, y in [a["home_xy"] for a in agents if a["is_responder"]]:
        if not in_radius(x, y, cx, cy, 1100): continue
        sx, sy = fm.proj(x, y)
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="1.4" fill="{ACCENT}" stroke="{INK}" stroke-width="0.1" opacity="0.85"/>')

    parts.extend(fm.render_streets_labels(atlas))

    # Map caption
    parts.append(f'<text x="{fm.x + fm.w/2:.2f}" y="{fm.y + fm.h + 5:.2f}" font-family="Georgia,serif" '
                 f'font-size="3" font-weight="700" fill="{INK}" text-anchor="middle">'
                 f'Day 13 (后撤期末) · 响应者还在新位置</text>')
    parts.append(f'<text x="{fm.x + fm.w/2:.2f}" y="{fm.y + fm.h + 8.5:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.6" font-style="italic" fill="{INK_SOFT}" text-anchor="middle">'
                 f'空间偏移不退,网络继续生长</text>')

    # Right: line chart 14-day
    with open(ANALYSIS / "B_temporal_curves/per_day_series.json") as f:
        tc = json.load(f)

    chart_x = 145; chart_y = 55
    chart_w = 165; chart_h = 130
    parts.append(f'<rect x="{chart_x}" y="{chart_y}" width="{chart_w}" height="{chart_h}" '
                 f'fill="{BG_PAPER}" stroke="{INK_LIGHT}" stroke-width="0.2"/>')

    # Phase shading
    plot_x = chart_x + 12; plot_w = chart_w - 18
    plot_y = chart_y + 8; plot_h = chart_h - 22
    # Baseline (day 0-3)
    parts.append(f'<rect x="{plot_x}" y="{plot_y}" width="{plot_w * 4/14:.2f}" height="{plot_h}" '
                 f'fill="{INK_LIGHT}" opacity="0.18"/>')
    # Intervention (day 4-9)
    parts.append(f'<rect x="{plot_x + plot_w*4/14:.2f}" y="{plot_y}" width="{plot_w * 6/14:.2f}" height="{plot_h}" '
                 f'fill="{ACCENT}" opacity="0.10"/>')
    # Post (day 10-13)
    parts.append(f'<rect x="{plot_x + plot_w*10/14:.2f}" y="{plot_y}" width="{plot_w * 4/14:.2f}" height="{plot_h}" '
                 f'fill="{HIGHLIGHT}" opacity="0.15"/>')

    # Phase labels
    parts.append(f'<text x="{plot_x + plot_w*2/14:.2f}" y="{plot_y-1:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.5" font-weight="700" fill="{INK_SOFT}" text-anchor="middle">基线 day 0-3</text>')
    parts.append(f'<text x="{plot_x + plot_w*7/14:.2f}" y="{plot_y-1:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.5" font-weight="900" fill="{ACCENT}" text-anchor="middle">干预 day 4-9</text>')
    parts.append(f'<text x="{plot_x + plot_w*12/14:.2f}" y="{plot_y-1:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.5" font-weight="900" fill="{ACCENT_DARK}" text-anchor="middle">后撤 day 10-13</text>')

    # Line chart
    max_v = 5.0
    variants = [
        ("hyperlocal_push", ACCENT, "HP"),
        ("phone_friction", GREEN, "PF"),
        ("global_distraction", BLUE, "GD"),
        ("baseline", INK_SOFT, "BL"),
    ]
    for vkey, color, lbl in variants:
        series = tc["data"][f"{vkey}|encounter_count_total"]
        pts = []
        for d, s in enumerate(series[:14]):
            v = (s["mean"] or 0) / 1e6
            px = plot_x + (d / 13) * plot_w
            py = plot_y + plot_h - (v / max_v) * plot_h
            pts.append((px, py))
        path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in pts)
        parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="0.7"/>')
        for x, y in pts:
            parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="0.7" fill="{color}"/>')
        last_x, last_y = pts[-1]
        parts.append(f'<text x="{last_x+1.2:.2f}" y="{last_y+1:.2f}" font-family="Georgia,serif" '
                     f'font-size="3" font-weight="900" fill="{color}">{lbl}</text>')

    # Y axis labels
    for v in [0, 1, 2, 3, 4, 5]:
        py = plot_y + plot_h - (v/max_v) * plot_h
        parts.append(f'<text x="{plot_x-1.5:.2f}" y="{py+0.7:.2f}" font-family="Helvetica,sans-serif" '
                     f'font-size="2.2" fill="{INK_SOFT}" text-anchor="end">{v}M</text>')
    parts.append(f'<text x="{plot_x-7:.2f}" y="{plot_y + plot_h/2:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.5" font-style="italic" fill="{INK_SOFT}" text-anchor="middle" '
                 f'transform="rotate(-90, {plot_x-7:.2f}, {plot_y + plot_h/2:.2f})">百万 偶遇</text>')
    # X labels
    for d in [0, 4, 9, 13]:
        px = plot_x + (d / 13) * plot_w
        parts.append(f'<text x="{px:.2f}" y="{plot_y + plot_h + 2.5:.2f}" font-family="Georgia,serif" '
                     f'font-size="2.3" font-weight="700" fill="{INK}" text-anchor="middle">d{d}</text>')

    # KEY ANNOTATION: arrow + text
    end_x = plot_x + plot_w
    parts.append(f'<line x1="{end_x-22:.2f}" y1="{plot_y+5:.2f}" x2="{end_x-3:.2f}" y2="{plot_y+1:.2f}" '
                 f'stroke="{ACCENT_DARK}" stroke-width="0.55"/>')
    parts.append(f'<polygon points="{end_x-3:.2f},{plot_y+1:.2f} {end_x-5:.2f},{plot_y+2:.2f} '
                 f'{end_x-4.5:.2f},{plot_y-0.5:.2f}" fill="{ACCENT_DARK}"/>')
    parts.append(f'<text x="{end_x-25:.2f}" y="{plot_y+7.5:.2f}" font-family="Georgia,serif" '
                 f'font-size="3.2" font-weight="900" fill="{ACCENT_DARK}">post 仍在涨</text>')
    parts.append(f'<text x="{end_x-25:.2f}" y="{plot_y+11.5:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.6" font-style="italic" fill="{ACCENT_DARK}">1.32× (HP) · 1.62× (PF)</text>')

    # Chart caption
    parts.append(f'<text x="{chart_x + chart_w/2:.2f}" y="{chart_y + chart_h - 2:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.6" font-style="italic" fill="{INK_SOFT}" text-anchor="middle">'
                 f'14 天每日偶遇总数(百万),mean across 3 seeds</text>')

    parts.extend(footer([
        (ACCENT, "HP 推送"),
        (GREEN, "PF 反技术"),
        (BLUE, "GD 镜像"),
        (INK_SOFT, "BL 对照"),
    ], "1000 agents × 14 days × 3 seeds"))

    write("finding_04_compounding.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# Finding 5: Mirror HP vs GD
# ──────────────────────────────────────────────────────────────────────
def fig5():
    center = get_center()
    atlas = load_atlas()
    cx, cy = center

    parts = svg_open()
    parts.extend(header(5, "+377% vs +33%",
        "同样 5 条推送/天,",
        "差距 11 倍。",
        "左:超在地推送 HP — 偶遇 +377%。右:镜像组 GD(全球新闻)— 偶遇仅 +33%。"))

    with open(ANALYSIS / "A_poi_activation/activation_per_location.json") as f:
        a_data = json.load(f)

    # Left: HP map
    map_w = 145; map_h = 140
    fm_hp = FlatMap(12, 50, map_w, map_h, center, radius=900)
    parts.extend(fm_hp.render_base(atlas))

    hp_acts = sorted(list(a_data["activation_vs_baseline"]["hyperlocal_push"].values()),
                     key=lambda r: -r["abs_delta"])[:50]
    parts.append('<g id="hp-dots">')
    max_d = max(a["abs_delta"] for a in hp_acts) if hp_acts else 1
    for a in hp_acts:
        if a["x"] is None: continue
        x, y = a["x"], a["y"]
        if not in_radius(x, y, cx, cy, 900): continue
        sx, sy = fm_hp.proj(x, y)
        ratio = a["abs_delta"] / max_d
        r = 1.2 + ratio * 4.5
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{r*1.6:.2f}" fill="{ACCENT}" fill-opacity="0.15"/>')
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{r:.2f}" fill="{ACCENT}" fill-opacity="0.65" stroke="{INK}" stroke-width="0.1"/>')
    parts.append("</g>")
    parts.extend(fm_hp.render_streets_labels(atlas))

    # HP map heading
    parts.append(f'<rect x="{fm_hp.x}" y="{fm_hp.y-7}" width="{map_w}" height="7" fill="{ACCENT}"/>')
    parts.append(f'<text x="{fm_hp.x + 4}" y="{fm_hp.y-2}" font-family="Georgia,serif" '
                 f'font-size="4.5" font-weight="900" fill="white">超在地推送 HP</text>')
    parts.append(f'<text x="{fm_hp.x + map_w - 4}" y="{fm_hp.y-2}" font-family="Georgia,serif" '
                 f'font-size="5" font-weight="900" fill="white" text-anchor="end">+377%</text>')

    # Right: GD map
    fm_gd = FlatMap(165, 50, map_w, map_h, center, radius=900)
    parts.extend(fm_gd.render_base(atlas))

    gd_acts = sorted(list(a_data["activation_vs_baseline"]["global_distraction"].values()),
                     key=lambda r: -r["abs_delta"])[:50]
    parts.append('<g id="gd-dots">')
    max_d_gd = max(a["abs_delta"] for a in gd_acts) if gd_acts else 1
    for a in gd_acts:
        if a.get("x") is None: continue
        x, y = a["x"], a["y"]
        if not in_radius(x, y, cx, cy, 900): continue
        sx, sy = fm_gd.proj(x, y)
        ratio = max(0, a["abs_delta"]) / max_d_gd
        r = 0.8 + ratio * 2.8
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{r:.2f}" fill="{BLUE}" fill-opacity="0.6" stroke="{INK}" stroke-width="0.08"/>')
    parts.append("</g>")
    parts.extend(fm_gd.render_streets_labels(atlas))

    # GD map heading
    parts.append(f'<rect x="{fm_gd.x}" y="{fm_gd.y-7}" width="{map_w}" height="7" fill="{BLUE}"/>')
    parts.append(f'<text x="{fm_gd.x + 4}" y="{fm_gd.y-2}" font-family="Georgia,serif" '
                 f'font-size="4.5" font-weight="900" fill="white">镜像组 GD · 推全球新闻</text>')
    parts.append(f'<text x="{fm_gd.x + map_w - 4}" y="{fm_gd.y-2}" font-family="Georgia,serif" '
                 f'font-size="5" font-weight="900" fill="white" text-anchor="end">+33%</text>')

    # Below maps: 5-metric comparison row
    by = fm_hp.y + map_h + 8
    metrics = [
        ("偶遇增加", "4.77×", "1.33×"),
        ("响应率", "22.7%", "~13%"),
        ("轨迹偏移", "108 m", "51 m"),
        ("每对相遇", "71.1 次", "23.8 次"),
        ("重规划数", "1,990", "447"),
    ]
    cell_w = (W - 24) / len(metrics)
    for i, (m, hp, gd) in enumerate(metrics):
        x0 = 12 + i * cell_w
        parts.append(f'<rect x="{x0}" y="{by}" width="{cell_w-1}" height="22" fill="{BG_MAP}" stroke="{INK_LIGHT}" stroke-width="0.15"/>')
        parts.append(f'<text x="{x0 + cell_w/2:.2f}" y="{by+4.5:.2f}" font-family="Georgia,serif" '
                     f'font-size="2.5" font-weight="700" fill="{INK_SOFT}" text-anchor="middle" letter-spacing="0.3">{m}</text>')
        parts.append(f'<text x="{x0 + cell_w/2:.2f}" y="{by+11:.2f}" font-family="Georgia,serif" '
                     f'font-size="6" font-weight="900" fill="{ACCENT}" text-anchor="middle">{hp}</text>')
        parts.append(f'<text x="{x0 + cell_w/2:.2f}" y="{by+16.5:.2f}" font-family="Georgia,serif" '
                     f'font-size="2.4" fill="{INK_LIGHT}" text-anchor="middle">vs GD</text>')
        parts.append(f'<text x="{x0 + cell_w/2:.2f}" y="{by+20:.2f}" font-family="Georgia,serif" '
                     f'font-size="3.5" font-weight="700" fill="{BLUE}" text-anchor="middle">{gd}</text>')

    parts.extend(footer([
        (ACCENT, "HP 激活地点"),
        (BLUE, "GD 激活地点"),
    ], "Top 50 POIs by Δdwell ticks · seed 43 reference"))

    write("finding_05_mirror.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# Finding 6: POI activation with real names
# ──────────────────────────────────────────────────────────────────────
def fig6():
    center = get_center()
    atlas = load_atlas()
    cx, cy = center

    parts = svg_open()
    parts.extend(header(6, "0 → 21,000",
        "Longueville Park 从无人去,变成 14 天里 10 天有人来。这只是",
        "ticks 的一个例子。",
        "推送让抽象的「附近」变成具体的「Cowper 街口、Longueville 公园、Mowbray 街角」。"))

    fm = FlatMap(12, 50, 200, 145, center, radius=1100)
    parts.extend(fm.render_base(atlas))
    parts.extend(fm.render_streets_labels(atlas))

    # Top 12 POIs with real names
    with open(ANALYSIS / "DEEP_MINING/specific_pois.json") as f:
        sp = json.load(f)
    top = sp["top_activated"][:12]

    # Plot all 12 as colored markers
    label_targets = []  # (idx, sx, sy, p)
    parts.append('<g id="pois">')
    max_d = max(p["abs_delta_ticks"] for p in top)
    for i, p in enumerate(top):
        b = atlas["buildings"].get(p["loc_id"])
        if not b:
            outdoor = atlas["outdoor_areas"]
            b = outdoor.get(p["loc_id"]) if isinstance(outdoor, dict) else None
        if not b: continue
        c = centroid(b.get("polygon", {}).get("vertices", []))
        if not c or not in_radius(c[0], c[1], cx, cy, 1100): continue
        sx, sy = fm.proj(c[0], c[1])
        ratio = p["abs_delta_ticks"] / max_d
        r = 2 + ratio * 4
        # Halo
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{r*1.6:.2f}" fill="{ACCENT}" fill-opacity="0.12"/>')
        # Triangle marker (NYT style "pin")
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{r:.2f}" fill="{ACCENT}" stroke="{INK}" stroke-width="0.25"/>')
        if i < 3:
            label_targets.append((i+1, sx, sy, p))
    parts.append("</g>")

    # Top 3 callouts
    text_x = 220
    callout_text_y = [60, 95, 130]
    for (idx, sx, sy, p), ty in zip(label_targets, callout_text_y):
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="3" fill="{HIGHLIGHT}" stroke="{INK}" stroke-width="0.4"/>')
        parts.append(f'<text x="{sx:.2f}" y="{sy+1.1:.2f}" font-family="Georgia,serif" '
                     f'font-size="3.8" font-weight="900" fill="{INK}" text-anchor="middle">{idx}</text>')
        parts.append(f'<line x1="{sx+3:.2f}" y1="{sy:.2f}" x2="{text_x-2:.2f}" y2="{ty:.2f}" '
                     f'stroke="{INK_SOFT}" stroke-width="0.25" stroke-dasharray="0.8 0.5"/>')

    # Side annotations using real names
    for (idx, sx, sy, p), ty in zip(label_targets, callout_text_y):
        name = p.get("name") or p["loc_id"]
        if len(name) > 26: name = name[:24] + "…"
        parts.extend(annotation_block(idx, text_x, ty, name, [
            f'{p.get("type","?")} · 类型',
            f'基线 {p["bl_dwell_ticks"]:,} ticks',
            f'HP {p["hp_dwell_ticks"]:,} ticks',
            f'增量 +{p["abs_delta_ticks"]:,} (+{p["activation_pct"]:.0f}%)',
        ])[:5])  # keep block compact

    # Inset: top 10 ranked list (text-only ranking)
    bi_x, bi_y, bi_w, bi_h = 220, 145, 90, 50
    parts.append(f'<rect x="{bi_x}" y="{bi_y}" width="{bi_w}" height="{bi_h}" '
                 f'fill="{BG_PAPER}" stroke="{INK_LIGHT}" stroke-width="0.2"/>')
    parts.append(f'<text x="{bi_x + 3}" y="{bi_y+4}" font-family="Georgia,serif" '
                 f'font-size="3" font-weight="900" fill="{INK}">Top 10 被激活地点</text>')
    for i, p in enumerate(top[:10]):
        name = (p.get("name") or "?")
        if len(name) > 25: name = name[:23] + "…"
        ty = bi_y + 8 + i * 4
        parts.append(f'<text x="{bi_x + 3}" y="{ty}" font-family="Georgia,serif" '
                     f'font-size="2.2" font-weight="700" fill="{INK}">{i+1}. {name}</text>')
        parts.append(f'<text x="{bi_x + bi_w - 3}" y="{ty}" font-family="Helvetica,sans-serif" '
                     f'font-size="2.2" fill="{ACCENT}" font-weight="900" text-anchor="end">+{p["abs_delta_ticks"]//1000}K</text>')

    parts.extend(footer([
        (ACCENT, "被激活 POI (圆大小 ∝ dwell ticks 增量)"),
    ], "Top 12 of 2,200 POIs ranked by absolute ticks gained"))

    write("finding_06_pois.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# Finding 7: Cross-occupation bridges
# ──────────────────────────────────────────────────────────────────────
def fig7():
    center = get_center()
    atlas = load_atlas()
    cx, cy = center

    parts = svg_open()
    parts.extend(header(7, "0 → 1,029",
        "学生与工人之间共处次数,",
        "次。",
        "基线下从不相遇的职业对 — 工人、建筑工、工程师、律师 — 在 HP 下都开始与学生共处。"))

    fm = FlatMap(12, 50, 200, 145, center, radius=1100)
    parts.extend(fm.render_base(atlas))
    parts.extend(fm.render_streets_labels(atlas))

    # Load profiles to find representative agents per occupation
    with open(REPO / "data/population_cache/v1/08d79c69cc045b32.json") as f:
        d = json.load(f)
    profs = list(d["profiles"])
    by_occ = defaultdict(list)
    for p in profs:
        by_occ[p.get("occupation", "?")].append(p)

    def occ_home_xy(occ):
        for p in by_occ.get(occ, []):
            h = p.get("home_location")
            for src in (atlas["buildings"], atlas["outdoor_areas"] if isinstance(atlas["outdoor_areas"], dict) else {}):
                if h and h in src:
                    c = centroid(src[h].get("polygon", {}).get("vertices", []))
                    if c and in_radius(c[0], c[1], cx, cy, 1000):
                        return c
        return None

    student_home = occ_home_xy("student") or center
    arcs = [
        ("学生 → 工人", "tradesperson", 1029, 0, 1),
        ("学生 → 建筑工", "construction", 709, 0, 2),
        ("学生 → 工程师", "engineer", 580, 0, 3),
        ("学生 → 管理者", "manager", 514, 0, 4),
        ("学生 → 律师", "lawyer", 490, 0, 5),
    ]

    sx_s, sy_s = fm.proj(student_home[0], student_home[1])

    # Draw arcs and end markers
    text_x = 220
    callout_text_y = [60, 87, 114, 141, 168]
    for label, occ, hp, bl, idx in arcs:
        tgt = occ_home_xy(occ)
        if not tgt: continue
        tx, ty = fm.proj(tgt[0], tgt[1])
        # Arc - quadratic bezier
        mx, my = (sx_s + tx) / 2, (sy_s + ty) / 2 - 15
        parts.append(f'<path d="M {sx_s:.2f} {sy_s:.2f} Q {mx:.2f} {my:.2f} {tx:.2f} {ty:.2f}" '
                     f'fill="none" stroke="{ACCENT}" stroke-width="0.5" opacity="0.7"/>')
        # End yellow circle
        parts.append(f'<circle cx="{tx:.2f}" cy="{ty:.2f}" r="2.8" fill="{HIGHLIGHT}" stroke="{INK}" stroke-width="0.35"/>')
        parts.append(f'<text x="{tx:.2f}" y="{ty+1.1:.2f}" font-family="Georgia,serif" '
                     f'font-size="3.6" font-weight="900" fill="{INK}" text-anchor="middle">{idx}</text>')
        # Dashed line to side annotation
        if idx <= 5:
            ttx_y = callout_text_y[idx-1]
            parts.append(f'<line x1="{tx+3:.2f}" y1="{ty:.2f}" x2="{text_x-2:.2f}" y2="{ttx_y:.2f}" '
                         f'stroke="{INK_SOFT}" stroke-width="0.2" stroke-dasharray="0.7 0.4"/>')

    # Student home as big blue marker
    parts.append(f'<circle cx="{sx_s:.2f}" cy="{sy_s:.2f}" r="4.5" fill="{BLUE_SOFT}" stroke="none"/>')
    parts.append(f'<circle cx="{sx_s:.2f}" cy="{sy_s:.2f}" r="2.8" fill="{BLUE}" stroke="{INK}" stroke-width="0.3"/>')
    parts.append(f'<text x="{sx_s:.2f}" y="{sy_s-5:.2f}" font-family="Georgia,serif" '
                 f'font-size="3.2" font-weight="900" fill="{BLUE}" text-anchor="middle" stroke="{BG_MAP}" '
                 f'stroke-width="1" paint-order="stroke">学生群体</text>')

    # Side annotations
    for label, occ, hp, bl, idx in arcs:
        ty = callout_text_y[idx-1]
        parts.extend(annotation_block(idx, text_x, ty, label, [
            f'基线 {bl} → HP {hp:,} 次共处',
            f'(end-of-day same-location pair count)',
        ])[:5])

    parts.extend(footer([
        (BLUE, "学生群体(起点)"),
        (HIGHLIGHT, "其他职业(终点)"),
    ], "Top 5 cross-occupation pairs by Δ co-location count · 3 seeds"))

    write("finding_07_bridges.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# Finding 8: Hub Pareto
# ──────────────────────────────────────────────────────────────────────
def fig8():
    center = get_center()
    atlas = load_atlas()
    cx, cy = center

    parts = svg_open()
    parts.extend(header(8, "52%",
        "Top 10% 的 agent 承担了",
        "的总共处量。",
        "基线下 top 10% 占 25%,HP 下涨到 52% — 推送把社交活动集中在少数枢纽 agent 身上。"))

    fm = FlatMap(12, 50, 200, 145, center, radius=1100)
    parts.extend(fm.render_base(atlas))
    parts.extend(fm.render_streets_labels(atlas))

    # Top 30 hub agents by deviation
    agents = load_responders_seed(43)
    hubs = sorted([a for a in agents if a["is_responder"]],
                  key=lambda a: -a["deviation_m"])[:30]

    # Draw all responders as small red, hubs as bigger glowing
    others = [a for a in agents if a["is_responder"] and a not in hubs]
    for a in others:
        x, y = a["home_xy"]
        if not in_radius(x, y, cx, cy, 1100): continue
        sx, sy = fm.proj(x, y)
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.8" fill="{ACCENT}" opacity="0.5"/>')

    max_dev = hubs[0]["deviation_m"] if hubs else 1
    for i, a in enumerate(hubs):
        x, y = a["home_xy"]
        if not in_radius(x, y, cx, cy, 1100): continue
        sx, sy = fm.proj(x, y)
        ratio = a["deviation_m"] / max_dev
        r = 1.5 + ratio * 3
        # Glow
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{r*2:.2f}" fill="{HIGHLIGHT}" fill-opacity="0.3"/>')
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{r:.2f}" fill="{ACCENT}" stroke="{INK}" stroke-width="0.25"/>')

    # 3 callouts: top 3 hubs
    text_x = 220
    callout_text_y = [60, 95, 130]
    for i, a in enumerate(hubs[:3]):
        x, y = a["home_xy"]
        if not in_radius(x, y, cx, cy, 1100): continue
        parts.extend(callout_marker(fm, i+1, x, y, target_text_xy=(text_x, callout_text_y[i])))

    # Annotations
    annots = []
    for i, a in enumerate(hubs[:3]):
        annots.append((f"Hub agent #{i+1}", [
            f'位移幅度 {a["deviation_m"]:.0f} 米',
            'protag: ' + ('是' if a["is_protagonist"] else '否'),
            '所在地区是社交集散点',
        ]))
    for idx, (title, body), ty in zip(range(1, 4), annots, callout_text_y):
        parts.extend(annotation_block(idx, text_x, ty, title, body))

    # Inset: Pareto curve
    bi_x, bi_y, bi_w, bi_h = 220, 145, 90, 50
    parts.append(f'<rect x="{bi_x}" y="{bi_y}" width="{bi_w}" height="{bi_h}" '
                 f'fill="{BG_PAPER}" stroke="{INK_LIGHT}" stroke-width="0.2"/>')
    parts.append(f'<text x="{bi_x + bi_w/2}" y="{bi_y+4}" font-family="Georgia,serif" '
                 f'font-size="3" font-weight="900" fill="{INK}" text-anchor="middle">'
                 f'Top X% agent 占总共处量份额</text>')
    px = bi_x + 8; py = bi_y + 8; pw = bi_w - 12; ph = bi_h - 18
    pcts = ["1","5","10","25","50"]
    bl_vals = [3.3, 13.9, 24.7, 48.9, 76.6]
    hp_vals = [5.9, 28.4, 52.4, 84.8, 94.2]
    parts.append(f'<line x1="{px}" y1="{py+ph}" x2="{px+pw}" y2="{py+ph}" stroke="{INK}" stroke-width="0.2"/>')
    parts.append(f'<line x1="{px}" y1="{py}" x2="{px}" y2="{py+ph}" stroke="{INK}" stroke-width="0.2"/>')
    for vals, color, lbl in [(bl_vals, INK_SOFT, "BL"), (hp_vals, ACCENT, "HP")]:
        pts = []
        for i, v in enumerate(vals):
            x = px + (i / (len(vals)-1)) * pw
            y = py + ph - (v/100) * ph
            pts.append((x, y))
        path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in pts)
        parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="0.55"/>')
        for x, y in pts:
            parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="0.7" fill="{color}"/>')
        last_x, last_y = pts[-1]
        parts.append(f'<text x="{last_x+1.2:.2f}" y="{last_y+0.5:.2f}" font-family="Georgia,serif" '
                     f'font-size="2.4" font-weight="900" fill="{color}">{lbl}</text>')
    for i, p in enumerate(pcts):
        x = px + (i / (len(pcts)-1)) * pw
        parts.append(f'<text x="{x:.2f}" y="{py+ph+2.8:.2f}" font-family="Helvetica,sans-serif" '
                     f'font-size="2" fill="{INK_SOFT}" text-anchor="middle">{p}%</text>')

    # 52% callout on inset
    p10_x = px + (2 / (len(pcts)-1)) * pw  # at index 2 = 10%
    p52_y = py + ph - (52/100) * ph
    parts.append(f'<line x1="{p10_x-7:.2f}" y1="{p52_y-7:.2f}" x2="{p10_x-1:.2f}" y2="{p52_y-1:.2f}" '
                 f'stroke="{ACCENT_DARK}" stroke-width="0.35"/>')
    parts.append(f'<text x="{p10_x-7:.2f}" y="{p52_y-8:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.6" font-weight="900" fill="{ACCENT_DARK}" text-anchor="end">52% under HP</text>')

    parts.extend(footer([
        (ACCENT, "Hub agent (柱高/光晕 ∝ 位移幅度)"),
        (HIGHLIGHT, "Top 3 hubs"),
    ], "Top 30 hubs by trajectory deviation · seed 43"))

    write("finding_08_hubs.svg", parts)


# ──────────────────────────────────────────────────────────────────────
def main():
    print("Building 8 NYT-style finding figures (Mock A scaled)...")
    print(f"Output: {OUT}/")
    for fn in [fig1, fig2, fig3, fig4, fig5, fig6, fig7, fig8]:
        try: fn()
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"FAILED: {fn.__name__}: {e}")
    print("Done")


if __name__ == "__main__":
    main()
