"""Single-agent deep story: Mary, 75-year-old retiree, discovers Shinnyo Australia.

Whole canvas dedicated to ONE story:
- Profile band with Mary's identity and a quote
- BIG Lane Cove map zoomed to her actual area, with HER actual 14-day path
  - Grey baseline routine + bold orange new discovery routes
  - Home + Shinnyo prominently marked
- 14-day timeline strip showing her location pattern day by day
- Narrative captions tied to specific days
"""
import json
import re
from pathlib import Path

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
ATLAS_PATH = REPO / "data/lanecove_atlas.json"
ANALYSIS = REPO / "data/analysis/2026-05-23_paper_exploration"
OUT_PATH = REPO / "docs/figures_v4/finding_01b_micro.svg"

POS_BL = "data/experiments/20260521_185100_publishable_v6_day4to13_fork_seed43_BACKUP_20260522_143245/variant_baseline/seed_43_positions.json"
POS_HP = "data/experiments/20260521_185100_publishable_v6_day4to13_fork_seed43_BACKUP_20260522_143245/variant_hyperlocal_push/seed_43_positions.json"

W, H = 320, 220

INK = "#1B1F2A"
INK_SOFT = "#5A5E6A"
INK_LIGHT = "#A8ACB5"
INK_LIGHTER = "#D8D9DC"
BG_PAPER = "#FFFFFF"
BG_PANEL = "#F8F5EE"
MAP_LAND = "#F4EFE5"
MAP_BLDG = "#DDD4BD"
MAP_BLDG_STROKE = "#9D906F"
MAP_STREET = "#D9D3C6"
MAP_PARK = "#CFE3C4"
ACCENT = "#E03A4A"
ACCENT_DARK = "#A0252F"
HIGHLIGHT = "#F0C419"
GREY_SHARED = "#454A52"
PEACH_OLD = "#F5B86E"
ORANGE_NEW = "#D14B12"

HERO = {
    "aid": "a_43_0405",
    "name": "Mary",
    "name_zh": "Mary",
    "age": 75,
    "occ": "退休 · 独居",
    "intro_quote": "「我以前一个人住,饭点散步、买菜、看电视。直到那天手机推送告诉我楼下真如苑下周三冥想公开课。」",
    "discovery_short": "真如苑 Lane Cove 道场",
    "discovery_eng": "Shinnyo Australia",
    "discovery_desc": "日本佛教冥想中心 · 周三周六对外开放 · 退休人群常去",
    # Day-by-day narrative — grouped into 7 milestone cards (more space per card)
    "days": [
        ("Day 1-3", "只在家方圆 500 m 散步、买菜、看电视。", "routine"),
        ("Day 4", "推送弹出: 「楼下真如苑下周三冥想公开课」", "push"),
        ("Day 5", "第一次走 2.4 km 出家门 · 抵达真如苑", "discovery"),
        ("Day 6", "课后认识退休邻居 Anne · 一起走回家", "discovery"),
        ("Day 7-8", "Anne 拉她再去一次 · 报名长期课程", "discovery"),
        ("Day 10-11", "推送停了 · 但和 Anne 已约好继续去", "post"),
        ("Day 12-14", "周三 + 周六 · 形成新的固定习惯", "post"),
    ],
}


def centroid_xy(verts):
    if not verts: return None
    xs = [v["x"] for v in verts] if isinstance(verts[0], dict) else [v[0] for v in verts]
    ys = [v["y"] for v in verts] if isinstance(verts[0], dict) else [v[1] for v in verts]
    return sum(xs)/len(xs), sum(ys)/len(ys)


print("Loading atlas...")
atlas = json.load(open(ATLAS_PATH))
LOC2XY = {}
LOC2META = {}
for bid, b in atlas["buildings"].items():
    verts = b.get("polygon", {}).get("vertices", [])
    if verts:
        c = centroid_xy(verts)
        if c:
            LOC2XY[bid] = c
            LOC2META[bid] = {"name": b.get("name") or "", "type": b.get("building_type") or ""}
outdoor = atlas.get("outdoor_areas", {})
outdoor_map = outdoor if isinstance(outdoor, dict) else {o["id"]: o for o in outdoor}
for oid, o in outdoor_map.items():
    verts = o.get("polygon", {}).get("vertices", [])
    if verts:
        c = centroid_xy(verts)
        if c:
            LOC2XY[oid] = c
            LOC2META[oid] = {"name": o.get("name") or "", "type": o.get("area_type") or ""}


def extract_chrono(pos_path, target_aid):
    d = json.load(open(pos_path))
    per_tick = []
    for c in d["changes"]:
        if c["agent_id"] == target_aid:
            per_tick.append((c["tick"], c["location_id"], c.get("day")))
    per_tick.sort()
    seq = []; prev = None
    for tick, loc, day in per_tick:
        if loc != prev:
            xy = LOC2XY.get(loc)
            if xy:
                seq.append({"tick": tick, "day": day, "loc": loc, "x": xy[0], "y": xy[1]})
                prev = loc
    return seq


print(f"Loading Mary's trajectory ({HERO['aid']})...")
bl_path = extract_chrono(REPO / POS_BL, HERO["aid"])
hp_path = extract_chrono(REPO / POS_HP, HERO["aid"])
print(f"  BL pts: {len(bl_path)}, HP pts: {len(hp_path)}")

home_xy = (bl_path[0]["x"], bl_path[0]["y"]) if bl_path else (0, 0)

# Find discovery location (Shinnyo)
discovery_loc = None
for p in hp_path:
    meta = LOC2META.get(p["loc"], {})
    if "shinnyo" in meta.get("name", "").lower():
        discovery_loc = p["loc"]
        break
discovery_xy = LOC2XY.get(discovery_loc, home_xy) if discovery_loc else home_xy
print(f"  discovery: {LOC2META.get(discovery_loc, {}).get('name', '?')} at {discovery_xy}")


# ──────────────────────────────────────────────────────────────────────
parts = [
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" '
    f'viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">',
    f'<rect width="100%" height="100%" fill="{BG_PAPER}"/>',
]

# Header
parts.append(f'<text x="12" y="14" font-family="Georgia,serif" font-size="3.3" '
             f'font-style="italic" fill="{ACCENT_DARK}" letter-spacing="0.3">'
             f'FINDING 01b · 微观视角 · 一个退休老人的 14 天 · 1,000 居民中的一位</text>')
parts.append(f'<line x1="12" y1="17" x2="{W-12}" y2="17" stroke="{ACCENT_DARK}" stroke-width="0.3"/>')
parts.append(f'<text x="12" y="32" font-family="Georgia,serif" font-size="13" '
             f'font-weight="900" fill="{INK}" letter-spacing="-0.5">'
             f'75 岁的 <tspan fill="{ACCENT}">Mary</tspan> · 走出家方圆 500 米的世界</text>')
parts.append(f'<text x="12" y="41" font-family="Georgia,serif" font-size="4.3" '
             f'font-style="italic" fill="{INK_SOFT}">'
             f'真实 positions.json 14 天完整路径 · 看一个退休老人如何被一条推送带去 2.4 km 外的冥想中心</text>')

# Profile band (left strip)
profile_x = 12; profile_y = 48
profile_w = 80; profile_h = 50
parts.append(f'<rect x="{profile_x}" y="{profile_y}" width="{profile_w}" height="{profile_h}" '
             f'fill="{INK}" rx="0.5"/>')
parts.append(f'<text x="{profile_x+4}" y="{profile_y+8}" font-family="Georgia,serif" '
             f'font-size="7" font-weight="900" fill="white">{HERO["name_zh"]}</text>')
parts.append(f'<text x="{profile_x+4}" y="{profile_y+13.5}" font-family="Georgia,serif" '
             f'font-size="3.2" font-style="italic" fill="{INK_LIGHTER}">'
             f'{HERO["age"]} 岁 · {HERO["occ"]}</text>')
# Big stat
parts.append(f'<text x="{profile_x+profile_w-4}" y="{profile_y+8}" font-family="Georgia,serif" '
             f'font-size="7" font-weight="900" fill="{HIGHLIGHT}" text-anchor="end">+2.4 km</text>')
parts.append(f'<text x="{profile_x+profile_w-4}" y="{profile_y+12}" font-family="Georgia,serif" '
             f'font-size="2.4" font-style="italic" fill="{INK_LIGHTER}" text-anchor="end">单次最远位移</text>')

# Mary's quote
parts.append(f'<line x1="{profile_x+4}" y1="{profile_y+18}" x2="{profile_x+profile_w-4}" y2="{profile_y+18}" '
             f'stroke="{HIGHLIGHT}" stroke-width="0.4"/>')
# Quote with word wrap — bigger font + tighter wrap
quote = HERO["intro_quote"]
lines = []
line = ""
MAX_CHARS = 26
for ch in list(quote):
    line += ch
    if len(line) >= MAX_CHARS and ch in "。,、 ":
        lines.append(line)
        line = ""
if line: lines.append(line)
for i, ln in enumerate(lines):
    parts.append(f'<text x="{profile_x+4}" y="{profile_y+22.5+i*4.8}" font-family="Georgia,serif" '
                 f'font-size="3.2" font-style="italic" fill="white">{ln}</text>')


# === Big map area (right of profile) ===
map_x = profile_x + profile_w + 6
map_y = profile_y
map_w = W - 12 - map_x
map_h = 100

# Bounding box
pts = [(home_xy[0], home_xy[1]), (discovery_xy[0], discovery_xy[1])]
pts.extend([(p["x"], p["y"]) for p in bl_path + hp_path])
min_x = min(p[0] for p in pts) - 50
max_x = max(p[0] for p in pts) + 50
min_y = min(p[1] for p in pts) - 50
max_y = max(p[1] for p in pts) + 50
span_x = max_x - min_x; span_y = max_y - min_y
target_aspect = map_w / map_h
actual_aspect = span_x / span_y if span_y > 0 else 1
if actual_aspect > target_aspect:
    new_y = span_x / target_aspect
    pad = (new_y - span_y) / 2
    min_y -= pad; max_y += pad
else:
    new_x = span_y * target_aspect
    pad = (new_x - span_x) / 2
    min_x -= pad; max_x += pad
span_x = max_x - min_x; span_y = max_y - min_y
scale = map_w / span_x

def proj(x, y):
    return map_x + (x - min_x) * scale, map_y + (max_y - y) * scale

def in_view(x, y):
    return min_x <= x <= max_x and min_y <= y <= max_y

clip_id = "mary-clip"
parts.append(f'<defs><clipPath id="{clip_id}"><rect x="{map_x}" y="{map_y}" '
             f'width="{map_w}" height="{map_h}"/></clipPath></defs>')

# Render base
parts.append(f'<g clip-path="url(#{clip_id})">')
parts.append(f'<rect x="{map_x}" y="{map_y}" width="{map_w}" height="{map_h}" '
             f'fill="{MAP_LAND}" stroke="{INK}" stroke-width="0.4"/>')
# Parks
for oid, o in outdoor_map.items():
    verts = o.get("polygon", {}).get("vertices", [])
    if len(verts) < 3: continue
    c = centroid_xy(verts)
    if not c or not in_view(*c): continue
    t = o.get("area_type", "")
    if t in ("park", "playground", "garden"):
        path_pts = [proj(v["x"], v["y"]) for v in verts]
        path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in path_pts) + " Z"
        parts.append(f'<path d="{path}" fill="{MAP_PARK}" stroke="#9DBC8A" stroke-width="0.15"/>')
# Streets
for oid, o in outdoor_map.items():
    verts = o.get("polygon", {}).get("vertices", [])
    if len(verts) < 3: continue
    c = centroid_xy(verts)
    if not c or not in_view(*c): continue
    if o.get("area_type") == "street":
        path_pts = [proj(v["x"], v["y"]) for v in verts]
        path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in path_pts) + " Z"
        parts.append(f'<path d="{path}" fill="{MAP_STREET}" stroke="none"/>')
# Buildings
for bid, b in atlas["buildings"].items():
    verts = b.get("polygon", {}).get("vertices", [])
    if len(verts) < 3: continue
    c = centroid_xy(verts)
    if not c or not in_view(*c): continue
    path_pts = [proj(v["x"], v["y"]) for v in verts]
    path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in path_pts) + " Z"
    parts.append(f'<path d="{path}" fill="{MAP_BLDG}" stroke="{MAP_BLDG_STROKE}" stroke-width="0.1"/>')

# Trajectories
bl_locs = {p["loc"] for p in bl_path}
hp_locs = {p["loc"] for p in hp_path}
JUMP_M = 80.0

def emit_path(seq, color_fn, allow_colors, stroke_styles):
    cur_color = None; cur_pts = []; cur_xy = None
    def flush():
        nonlocal cur_pts, cur_color
        if cur_color in allow_colors and len(cur_pts) >= 2:
            stroke, width, opacity = stroke_styles[cur_color]
            d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in cur_pts)
            parts.append(f'<path d="{d}" fill="none" stroke="{stroke}" '
                         f'stroke-width="{width}" stroke-linejoin="round" '
                         f'stroke-linecap="round" opacity="{opacity}"/>')
        cur_pts = []; cur_color = None
    for p in seq:
        x, y = p["x"], p["y"]
        if not in_view(x, y):
            flush(); cur_xy = None; continue
        if cur_xy is not None:
            dx = x - cur_xy[0]; dy = y - cur_xy[1]
            if dx*dx + dy*dy > JUMP_M*JUMP_M:
                flush()
        sx, sy = proj(x, y)
        color = color_fn(p["loc"])
        if cur_color is None: cur_color = color; cur_pts = [(sx, sy)]
        elif color == cur_color: cur_pts.append((sx, sy))
        else:
            cur_pts.append((sx, sy)); flush()
            cur_pts = [(sx, sy)]; cur_color = color
        cur_xy = (x, y)
    flush()

emit_path(bl_path, lambda loc: "shared" if loc in hp_locs else "abandoned",
          {"shared", "abandoned"}, {
              "shared": (GREY_SHARED, "1.6", "0.65"),
              "abandoned": (PEACH_OLD, "2.0", "0.85"),
          })
emit_path(hp_path, lambda loc: "shared" if loc in bl_locs else "new",
          {"new"}, {"new": (ORANGE_NEW, "3.5", "0.98")})

parts.append(f'</g>')

# Home marker (large)
hsx, hsy = proj(*home_xy)
parts.append(f'<circle cx="{hsx:.1f}" cy="{hsy:.1f}" r="6" fill="{INK}" opacity="0.18"/>')
parts.append(f'<circle cx="{hsx:.1f}" cy="{hsy:.1f}" r="3.5" fill="{INK}" stroke="white" stroke-width="0.7"/>')
parts.append(f'<text x="{hsx:.1f}" y="{hsy+1.3:.1f}" font-family="Georgia,serif" '
             f'font-size="3.6" font-weight="900" fill="white" text-anchor="middle">家</text>')
# Home label
parts.append(f'<text x="{hsx:.1f}" y="{hsy-6:.1f}" font-family="Georgia,serif" '
             f'font-size="3" font-weight="900" fill="{INK}" text-anchor="middle">Mary 的家</text>')

# Discovery marker (extra large)
dsx, dsy = proj(*discovery_xy)
parts.append(f'<circle cx="{dsx:.1f}" cy="{dsy:.1f}" r="13" fill="{HIGHLIGHT}" opacity="0.18"/>')
parts.append(f'<circle cx="{dsx:.1f}" cy="{dsy:.1f}" r="7" fill="{HIGHLIGHT}" opacity="0.45"/>')
parts.append(f'<circle cx="{dsx:.1f}" cy="{dsy:.1f}" r="4" fill="{HIGHLIGHT}" stroke="{INK}" stroke-width="0.7"/>')
parts.append(f'<text x="{dsx:.1f}" y="{dsy+1.5:.1f}" font-family="Georgia,serif" '
             f'font-size="4.2" font-weight="900" fill="{INK}" text-anchor="middle">★</text>')
# Big callout for discovery
cb_y = dsy - 18 if dsy > map_y + 40 else dsy + 10
parts.append(f'<line x1="{dsx:.1f}" y1="{dsy-(5 if cb_y < dsy else -5):.1f}" x2="{dsx:.1f}" y2="{cb_y+(8 if cb_y < dsy else 0):.1f}" '
             f'stroke="{INK}" stroke-width="0.4"/>')
parts.append(f'<rect x="{dsx-30:.1f}" y="{cb_y:.1f}" width="60" height="9" fill="white" stroke="{INK}" stroke-width="0.4" rx="0.5"/>')
parts.append(f'<text x="{dsx:.1f}" y="{cb_y+3.5:.1f}" font-family="Georgia,serif" '
             f'font-size="3.2" font-weight="900" fill="{INK}" text-anchor="middle">{HERO["discovery_short"]}</text>')
parts.append(f'<text x="{dsx:.1f}" y="{cb_y+7:.1f}" font-family="Georgia,serif" '
             f'font-size="2.4" font-style="italic" fill="{INK_SOFT}" text-anchor="middle">{HERO["discovery_eng"]} · {HERO["discovery_desc"]}</text>')

# Map legend (bottom-left of map)
leg_y = map_y + map_h - 10
parts.append(f'<rect x="{map_x+2}" y="{leg_y}" width="56" height="8" fill="white" opacity="0.95" stroke="{INK_LIGHT}" stroke-width="0.2"/>')
parts.append(f'<line x1="{map_x+4}" y1="{leg_y+2.5}" x2="{map_x+10}" y2="{leg_y+2.5}" stroke="{GREY_SHARED}" stroke-width="1.0"/>')
parts.append(f'<text x="{map_x+11.5}" y="{leg_y+3.3}" font-family="Georgia,serif" font-size="2.4" '
             f'font-weight="700" fill="{INK}">推送前 14 天日常路径</text>')
parts.append(f'<line x1="{map_x+4}" y1="{leg_y+6}" x2="{map_x+10}" y2="{leg_y+6}" stroke="{ORANGE_NEW}" stroke-width="2.0"/>')
parts.append(f'<text x="{map_x+11.5}" y="{leg_y+6.8}" font-family="Georgia,serif" font-size="2.4" '
             f'font-weight="700" fill="{ACCENT_DARK}">推送后新走出的路</text>')


# === 14-day timeline (bottom strip) ===
tl_x = 12; tl_y = map_y + map_h + 6
tl_w = W - 24; tl_h = 50

parts.append(f'<rect x="{tl_x}" y="{tl_y}" width="{tl_w}" height="{tl_h}" '
             f'fill="{BG_PANEL}" stroke="{INK}" stroke-width="0.4"/>')
parts.append(f'<text x="{tl_x+4}" y="{tl_y+5}" font-family="Georgia,serif" font-size="4.5" '
             f'font-weight="900" fill="{INK}">14 天故事时间线</text>')
parts.append(f'<text x="{tl_x+4}" y="{tl_y+9}" font-family="Georgia,serif" font-size="2.8" '
             f'font-style="italic" fill="{INK_SOFT}">'
             f'每个方块 = 一天 Mary 真实做的事 · 同色块共享一个阶段</text>')

# Phase colors
phase_color = {
    "routine": GREY_SHARED,
    "push": HIGHLIGHT,
    "discovery": ORANGE_NEW,
    "post": ACCENT,
}

# Compute day card layout (7 milestone cards in a row, more text space per card)
n_cards = len(HERO["days"])
card_w = (tl_w - 8) / n_cards - 1.5
card_x_start = tl_x + 4
card_y = tl_y + 13
card_h = tl_h - 18

for i, (day_label, action, phase) in enumerate(HERO["days"]):
    cx = card_x_start + i * (card_w + 1.5)
    cy = card_y
    color = phase_color[phase]
    # Day header strip
    header_h = 7
    parts.append(f'<rect x="{cx:.2f}" y="{cy:.2f}" width="{card_w:.2f}" height="{header_h}" fill="{color}"/>')
    parts.append(f'<text x="{cx + card_w/2:.2f}" y="{cy+5:.2f}" font-family="Georgia,serif" '
                 f'font-size="3.4" font-weight="900" fill="white" text-anchor="middle">{day_label}</text>')
    # Body (white)
    body_h = card_h - header_h
    parts.append(f'<rect x="{cx:.2f}" y="{cy+header_h:.2f}" width="{card_w:.2f}" height="{body_h:.2f}" '
                 f'fill="white" stroke="{color}" stroke-width="0.4"/>')
    # Word-wrap action text (bigger font now)
    max_chars_per_line = max(int(card_w / 2.8), 6)
    words = list(action)
    lines = []
    line = ""
    for ch in words:
        if len(line) + 1 > max_chars_per_line:
            lines.append(line)
            line = ch
        else:
            line += ch
    if line: lines.append(line)
    for j, ln in enumerate(lines[:6]):
        parts.append(f'<text x="{cx+1.5:.2f}" y="{cy+header_h+3.5+j*3.2:.2f}" font-family="Georgia,serif" '
                     f'font-size="2.7" fill="{INK}">{ln}</text>')


# Takeaway
ty = H - 22
parts.append(f'<rect x="12" y="{ty}" width="{W-24}" height="12" fill="{INK}"/>')
parts.append(f'<text x="{W/2:.2f}" y="{ty+7.5:.2f}" font-family="Georgia,serif" '
             f'font-size="4.8" font-weight="900" fill="{HIGHLIGHT}" text-anchor="middle" '
             f'font-style="italic">▶  一条推送 · 让 Mary 从家方圆 500 米的世界,走进了 2.4 km 外的冥想中心 · 还认识了 Anne。</text>')
parts.append(f'<text x="{W/2:.2f}" y="{H-3:.2f}" font-family="Georgia,serif" font-size="2.3" '
             f'font-style="italic" fill="{INK_LIGHT}" text-anchor="middle">'
             f'Synthetic Socio Wind Tunnel · 悉尼 Lane Cove · 真实 positions.json 14 天完整路径 · github.com/york-zhouuu</text>')

parts.append("</svg>")
OUT_PATH.write_text("\n".join(parts))
print(f"\nWrote {OUT_PATH} · {OUT_PATH.stat().st_size / 1e3:.0f} KB")
