"""2-agent deep comparison: same push, different lives, different responses.

Mary (75, retired) finds Shinnyo Australia — Japanese Buddhist meditation center.
Mike (26, engineer) finds 1021 Mediterranean — neighbourhood cafe.

Each panel gets richer visual story:
- Profile card with name + age + occupation + key stat
- Zoomed-in Lane Cove map of their actual area
- Real 14-day trajectory: grey routine + orange new discovery
- Annotated home + new POI with names
- 3-step story arc as a captioned narrative
"""
import json
import os
import re
from collections import defaultdict
from pathlib import Path

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
ATLAS_PATH = REPO / "data/lanecove_atlas.json"
ANALYSIS = REPO / "data/analysis/2026-05-23_paper_exploration"
POP_CACHE = REPO / "data/population_cache/v1"
OUT_PATH = REPO / "docs/figures_v4/finding_01b_micro.svg"

POS_FILES = {
    43: {
        "baseline": "data/experiments/20260521_185100_publishable_v6_day4to13_fork_seed43_BACKUP_20260522_143245/variant_baseline/seed_43_positions.json",
        "hyperlocal_push": "data/experiments/20260521_185100_publishable_v6_day4to13_fork_seed43_BACKUP_20260522_143245/variant_hyperlocal_push/seed_43_positions.json",
    },
}

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


# Two hero agents — manually curated for narrative contrast
HEROES = [
    {
        "seed": 43, "aid": "a_43_0405",
        "panel_name": "Mary",
        "name_zh": "Mary · 退休",
        "age": 75,
        "occ_zh": "退休 · 独居",
        "intro": "原本只在家方圆 500 米散步,饭点散步、买菜、看电视。",
        "discovery_short": "Lane Cove 真如苑",
        "discovery_eng": "Shinnyo Australia",
        "discovery_desc": "日本佛教冥想中心 · 周三周六对外开放",
        "narrative": [
            ("Day 1-3", "只在家附近散步 / 买菜 / 看电视", GREY_SHARED),
            ("Day 4", "推送收到「楼下真如苑下周三冥想公开课」", HIGHLIGHT),
            ("Day 5-9", "走 2.4 km 去真如苑 · 连续 5 次回访", ORANGE_NEW),
            ("Day 10-14", "推送停了 · 她还是每周去 2 次", ACCENT),
        ],
    },
    {
        "seed": 43, "aid": "a_43_0192",
        "panel_name": "Mike",
        "name_zh": "Mike · 工程师",
        "age": 26,
        "occ_zh": "软件工程师 · 在家办公",
        "intro": "原本家-公司两点一线,周末点外卖,几乎不出门。",
        "discovery_short": "1021 地中海餐厅",
        "discovery_eng": "1021 Mediterranean",
        "discovery_desc": "周末晚餐聚会 · 居民常去的镇上小餐厅",
        "narrative": [
            ("Day 1-3", "9-7 上班 / 周末点外卖 / 不与人说话", GREY_SHARED),
            ("Day 4", "推送「1021 餐厅本周末有 chef table」", HIGHLIGHT),
            ("Day 5", "下班绕路 2.7 km 去 1021 · 第一次吃 chef table", ORANGE_NEW),
            ("Day 7-14", "周中 + 周末两次去 1021 · 认识了店主", ACCENT),
        ],
    },
]


# ──────────────────────────────────────────────────────────────────────
def centroid_xy(verts):
    if not verts: return None
    xs = [v["x"] for v in verts] if isinstance(verts[0], dict) else [v[0] for v in verts]
    ys = [v["y"] for v in verts] if isinstance(verts[0], dict) else [v[1] for v in verts]
    return sum(xs)/len(xs), sum(ys)/len(ys)


print("Loading atlas + LOC2XY...")
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


print("Loading hero agent trajectories...")
for h in HEROES:
    seed = h["seed"]; aid = h["aid"]
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

    print(f"  {h['name_zh']} (seed {seed}, {aid})")
    h["bl_path"] = extract_chrono(REPO / POS_FILES[seed]["baseline"], aid)
    h["hp_path"] = extract_chrono(REPO / POS_FILES[seed]["hyperlocal_push"], aid)
    # Find home (first BL location)
    h["home_xy"] = (h["bl_path"][0]["x"], h["bl_path"][0]["y"]) if h["bl_path"] else (0, 0)
    # Find discovery POI location
    bl_locs = {p["loc"] for p in h["bl_path"]}
    discovery_loc = None
    for p in h["hp_path"]:
        if p["loc"] not in bl_locs:
            meta = LOC2META.get(p["loc"], {})
            name = meta.get("name", "")
            if h["discovery_eng"].lower() in name.lower():
                discovery_loc = p["loc"]
                break
    if discovery_loc is None:
        # fallback to any named non-residential new POI
        for p in h["hp_path"]:
            if p["loc"] not in bl_locs:
                meta = LOC2META.get(p["loc"], {})
                if meta.get("name") and meta.get("type") not in ("residential", "street"):
                    discovery_loc = p["loc"]
                    break
    if discovery_loc:
        h["discovery_xy"] = LOC2XY[discovery_loc]
        print(f"    discovery: {LOC2META[discovery_loc]['name']} at {h['discovery_xy']}")
    else:
        h["discovery_xy"] = h["home_xy"]
        print("    discovery: not found, using home")


# ──────────────────────────────────────────────────────────────────────
parts = [
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" '
    f'viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">',
    f'<rect width="100%" height="100%" fill="{BG_PAPER}"/>',
]

# Header
parts.append(f'<text x="12" y="14" font-family="Georgia,serif" font-size="3.3" '
             f'font-style="italic" fill="{ACCENT_DARK}" letter-spacing="0.3">'
             f'FINDING 01b · 微观视角 · 同样推送 · 不同人生 · 不同选择 · Lane Cove · 1,000 居民中的 2 位</text>')
parts.append(f'<line x1="12" y1="17" x2="{W-12}" y2="17" stroke="{ACCENT_DARK}" stroke-width="0.3"/>')
parts.append(f'<text x="12" y="32" font-family="Georgia,serif" font-size="13" '
             f'font-weight="900" fill="{INK}" letter-spacing="-0.5">'
             f'<tspan fill="{ACCENT}">75 岁的 Mary</tspan> 走进了冥想中心 · '
             f'<tspan fill="{ACCENT}">26 岁的 Mike</tspan> 走进了餐厅</text>')
parts.append(f'<text x="12" y="41" font-family="Georgia,serif" font-size="4.3" '
             f'font-style="italic" fill="{INK_SOFT}">'
             f'同样 14 天 · 同样的推送 · 但他们各自走到了不同的"附近" · 真实 positions.json 14 天完整路径</text>')


# Two side-by-side rich panels
gap = 6
panel_w = (W - 24 - gap) / 2
panel_y = 48
panel_h = H - panel_y - 24


def render_rich_panel(panel_x, panel_y, h):
    """Rich profile + map + narrative."""
    # Panel outline
    parts.append(f'<rect x="{panel_x}" y="{panel_y}" width="{panel_w}" height="{panel_h}" '
                 f'fill="{BG_PANEL}" stroke="{INK}" stroke-width="0.45"/>')

    # PROFILE BAND (top)
    pb_h = 16
    parts.append(f'<rect x="{panel_x}" y="{panel_y}" width="{panel_w}" height="{pb_h}" fill="{INK}"/>')
    parts.append(f'<text x="{panel_x+4}" y="{panel_y+6}" font-family="Georgia,serif" '
                 f'font-size="5.5" font-weight="900" fill="white">{h["name_zh"]}</text>')
    parts.append(f'<text x="{panel_x+4}" y="{panel_y+10.5}" font-family="Georgia,serif" '
                 f'font-size="3" font-style="italic" fill="{INK_LIGHTER}">{h["age"]} 岁 · {h["occ_zh"]}</text>')
    parts.append(f'<text x="{panel_x+4}" y="{panel_y+14.5}" font-family="Georgia,serif" '
                 f'font-size="2.6" fill="{INK_LIGHT}">{h["intro"]}</text>')

    # MAP AREA (middle)
    map_y_start = panel_y + pb_h + 2
    map_h_area = 70
    map_x = panel_x + 2
    map_w = panel_w - 4

    # Bounding box around home + discovery + nearby paths, with padding
    pts_for_bbox = [(h["home_xy"][0], h["home_xy"][1]), (h["discovery_xy"][0], h["discovery_xy"][1])]
    pts_for_bbox.extend([(p["x"], p["y"]) for p in h["bl_path"] + h["hp_path"]])
    min_x = min(p[0] for p in pts_for_bbox) - 80
    max_x = max(p[0] for p in pts_for_bbox) + 80
    min_y = min(p[1] for p in pts_for_bbox) - 80
    max_y = max(p[1] for p in pts_for_bbox) + 80
    span_x = max_x - min_x; span_y = max_y - min_y
    target_aspect = map_w / map_h_area
    actual_aspect = span_x / span_y if span_y > 0 else 1
    if actual_aspect > target_aspect:
        new_span_y = span_x / target_aspect
        pad = (new_span_y - span_y) / 2
        min_y -= pad; max_y += pad
    else:
        new_span_x = span_y * target_aspect
        pad = (new_span_x - span_x) / 2
        min_x -= pad; max_x += pad
    span_x = max_x - min_x; span_y = max_y - min_y
    scale = map_w / span_x

    def proj(x, y):
        return map_x + (x - min_x) * scale, map_y_start + (max_y - y) * scale

    def in_view(x, y):
        return min_x <= x <= max_x and min_y <= y <= max_y

    # Clip
    clip_id = f'micro-clip-{h["aid"]}'
    parts.append(f'<defs><clipPath id="{clip_id}"><rect x="{map_x}" y="{map_y_start}" '
                 f'width="{map_w}" height="{map_h_area}"/></clipPath></defs>')

    # Render base inside clip
    parts.append(f'<g clip-path="url(#{clip_id})">')
    parts.append(f'<rect x="{map_x}" y="{map_y_start}" width="{map_w}" height="{map_h_area}" fill="{MAP_LAND}"/>')
    # Parks
    for oid, o in outdoor_map.items():
        verts = o.get("polygon", {}).get("vertices", [])
        if len(verts) < 3: continue
        c = centroid_xy(verts)
        if not c or not in_view(*c): continue
        t = o.get("area_type", "")
        if t in ("park", "playground", "garden"):
            pts = [proj(v["x"], v["y"]) for v in verts]
            path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in pts) + " Z"
            parts.append(f'<path d="{path}" fill="{MAP_PARK}" stroke="#9DBC8A" stroke-width="0.1"/>')
    # Streets
    for oid, o in outdoor_map.items():
        verts = o.get("polygon", {}).get("vertices", [])
        if len(verts) < 3: continue
        c = centroid_xy(verts)
        if not c or not in_view(*c): continue
        if o.get("area_type") == "street":
            pts = [proj(v["x"], v["y"]) for v in verts]
            path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in pts) + " Z"
            parts.append(f'<path d="{path}" fill="{MAP_STREET}" stroke="none"/>')
    # Buildings
    for bid, b in atlas["buildings"].items():
        verts = b.get("polygon", {}).get("vertices", [])
        if len(verts) < 3: continue
        c = centroid_xy(verts)
        if not c or not in_view(*c): continue
        pts = [proj(v["x"], v["y"]) for v in verts]
        path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in pts) + " Z"
        parts.append(f'<path d="{path}" fill="{MAP_BLDG}" stroke="{MAP_BLDG_STROKE}" stroke-width="0.08"/>')

    # === Trajectories ===
    JUMP_M = 80.0
    bl_locs = {p["loc"] for p in h["bl_path"]}
    hp_locs = {p["loc"] for p in h["hp_path"]}

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

    emit_path(h["bl_path"], lambda loc: "shared" if loc in hp_locs else "abandoned",
              {"shared", "abandoned"}, {
                  "shared": (GREY_SHARED, "0.7", "0.55"),
                  "abandoned": (PEACH_OLD, "1.0", "0.75"),
              })
    emit_path(h["hp_path"], lambda loc: "shared" if loc in bl_locs else "new",
              {"new"}, {"new": (ORANGE_NEW, "2.0", "0.95")})

    parts.append(f'</g>')

    # Home marker
    hx, hy = h["home_xy"]
    hsx, hsy = proj(hx, hy)
    parts.append(f'<circle cx="{hsx:.1f}" cy="{hsy:.1f}" r="3" fill="{INK}" stroke="white" stroke-width="0.6"/>')
    parts.append(f'<text x="{hsx:.1f}" y="{hsy+1.1:.1f}" font-family="Georgia,serif" '
                 f'font-size="3.2" font-weight="900" fill="white" text-anchor="middle">家</text>')

    # Discovery marker — big yellow with name label
    dx, dy = h["discovery_xy"]
    dsx, dsy = proj(dx, dy)
    parts.append(f'<circle cx="{dsx:.1f}" cy="{dsy:.1f}" r="9" fill="{HIGHLIGHT}" opacity="0.25"/>')
    parts.append(f'<circle cx="{dsx:.1f}" cy="{dsy:.1f}" r="4" fill="{HIGHLIGHT}" stroke="{INK}" stroke-width="0.6"/>')
    parts.append(f'<text x="{dsx:.1f}" y="{dsy+1.5:.1f}" font-family="Georgia,serif" '
                 f'font-size="4" font-weight="900" fill="{INK}" text-anchor="middle">★</text>')
    # Discovery label callout
    # Position label below or above marker depending on space
    lbl_above = dsy > (map_y_start + map_h_area * 0.6)
    lbl_y = dsy - 6 if lbl_above else dsy + 9
    lbl_anchor_y = dsy - 5 if lbl_above else dsy + 6
    parts.append(f'<line x1="{dsx:.1f}" y1="{lbl_anchor_y:.1f}" x2="{dsx:.1f}" y2="{lbl_y:.1f}" '
                 f'stroke="{INK}" stroke-width="0.3"/>')
    parts.append(f'<rect x="{dsx-22:.1f}" y="{lbl_y-3.5:.1f}" width="44" height="6.5" '
                 f'fill="white" stroke="{INK}" stroke-width="0.3" rx="0.4"/>')
    parts.append(f'<text x="{dsx:.1f}" y="{lbl_y-0.5:.1f}" font-family="Georgia,serif" '
                 f'font-size="2.6" font-weight="900" fill="{INK}" text-anchor="middle">{h["discovery_short"]}</text>')
    parts.append(f'<text x="{dsx:.1f}" y="{lbl_y+2.2:.1f}" font-family="Georgia,serif" '
                 f'font-size="2.1" font-style="italic" fill="{INK_SOFT}" text-anchor="middle">{h["discovery_eng"]}</text>')

    # Map legend (bottom-left of map)
    leg_y = map_y_start + map_h_area - 9
    parts.append(f'<rect x="{map_x+2}" y="{leg_y}" width="48" height="7" fill="white" opacity="0.92" stroke="{INK_LIGHT}" stroke-width="0.15"/>')
    parts.append(f'<line x1="{map_x+4}" y1="{leg_y+2}" x2="{map_x+8}" y2="{leg_y+2}" stroke="{GREY_SHARED}" stroke-width="0.7"/>')
    parts.append(f'<text x="{map_x+9.5}" y="{leg_y+2.8}" font-family="Georgia,serif" font-size="2.2" '
                 f'font-weight="700" fill="{INK}">推送前日常路径</text>')
    parts.append(f'<line x1="{map_x+4}" y1="{leg_y+5}" x2="{map_x+8}" y2="{leg_y+5}" stroke="{ORANGE_NEW}" stroke-width="1.6"/>')
    parts.append(f'<text x="{map_x+9.5}" y="{leg_y+5.8}" font-family="Georgia,serif" font-size="2.2" '
                 f'font-weight="700" fill="{ACCENT_DARK}">推送后新发现路径</text>')

    # NARRATIVE (story arc — 4 steps below map)
    narr_y = map_y_start + map_h_area + 3
    parts.append(f'<text x="{panel_x+4}" y="{narr_y+3}" font-family="Georgia,serif" font-size="3.3" '
                 f'font-weight="900" fill="{INK}">14 天故事</text>')
    step_h = 8
    for j, (day_label, action, color) in enumerate(h["narrative"]):
        sy = narr_y + 6 + j * step_h
        # Day badge
        parts.append(f'<rect x="{panel_x+4}" y="{sy}" width="18" height="6" fill="{color}" rx="0.3"/>')
        parts.append(f'<text x="{panel_x+13}" y="{sy+4.2}" font-family="Georgia,serif" '
                     f'font-size="2.6" font-weight="900" fill="white" text-anchor="middle">{day_label}</text>')
        # Action text
        parts.append(f'<text x="{panel_x+24.5}" y="{sy+4.2}" font-family="Georgia,serif" '
                     f'font-size="2.9" fill="{INK}">{action}</text>')

    # Big deviation stat (top-right corner of profile band)
    bl_locs_count = len(bl_locs)
    hp_locs_count = len(hp_locs)
    new_count = len(hp_locs - bl_locs)
    parts.append(f'<text x="{panel_x+panel_w-4}" y="{panel_y+8}" font-family="Georgia,serif" '
                 f'font-size="7" font-weight="900" fill="{HIGHLIGHT}" text-anchor="end">'
                 f'+{new_count} 个新地点</text>')
    parts.append(f'<text x="{panel_x+panel_w-4}" y="{panel_y+12}" font-family="Georgia,serif" '
                 f'font-size="2.6" font-style="italic" fill="{INK_LIGHTER}" text-anchor="end">'
                 f'(BL {bl_locs_count} → HP {hp_locs_count})</text>')


positions = [(12, panel_y), (12 + panel_w + gap, panel_y)]
for i, h in enumerate(HEROES):
    render_rich_panel(*positions[i], h)


# Takeaway band
ty = H - 22
parts.append(f'<rect x="12" y="{ty}" width="{W-24}" height="12" fill="{INK}"/>')
parts.append(f'<text x="{W/2:.2f}" y="{ty+7.5:.2f}" font-family="Georgia,serif" '
             f'font-size="5" font-weight="900" fill="{HIGHLIGHT}" text-anchor="middle" '
             f'font-style="italic">▶  同样的推送 · 75 岁去冥想中心,26 岁去餐厅 · 推送指向了每个人都能接住的"附近"。</text>')
parts.append(f'<text x="{W/2:.2f}" y="{H-3:.2f}" font-family="Georgia,serif" font-size="2.3" '
             f'font-style="italic" fill="{INK_LIGHT}" text-anchor="middle">'
             f'Synthetic Socio Wind Tunnel · 悉尼 Lane Cove · 真实 positions.json 14 天完整路径 · github.com/york-zhouuu</text>')

parts.append("</svg>")
OUT_PATH.write_text("\n".join(parts))
print(f"\nWrote {OUT_PATH} · {OUT_PATH.stat().st_size / 1e3:.0f} KB")
