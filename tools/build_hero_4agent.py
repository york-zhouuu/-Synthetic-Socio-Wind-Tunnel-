"""4-agent micro view — full 14-day trajectories of 4 representative responders.

Each agent gets a panel showing:
- Their full 14-day BL path (shared parts of HP = grey)
- Their HP-only path (new discoveries = orange) — the change
- Annotations: name, age, occupation, key POI discovered
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
    44: {
        "baseline": "data/experiments/20260522_165045_publishable_v7_day4to13_fork_seed44_BACKUP_20260522_213319_FULL_ALLVARIANTS/variant_baseline/seed_44_positions.json",
        "hyperlocal_push": "data/experiments/20260522_165045_publishable_v7_day4to13_fork_seed44_BACKUP_20260522_213319_FULL_ALLVARIANTS/variant_hyperlocal_push/seed_44_positions.json",
    },
}

# Canvas — same dimensions as other findings
W, H = 320, 220

INK = "#1B1F2A"
INK_SOFT = "#5A5E6A"
INK_LIGHT = "#A8ACB5"
INK_LIGHTER = "#D8D9DC"
BG_PAPER = "#FFFFFF"
BG_PANEL = "#F8F5EE"
MAP_LAND = "#F4EFE5"
MAP_BLDG = "#E0DAC8"
MAP_STREET = "#D9D3C6"
MAP_PARK = "#D5E5C8"
ACCENT = "#E03A4A"
ACCENT_DARK = "#A0252F"
HIGHLIGHT = "#F0C419"
GREY_SHARED = "#454A52"
PEACH_OLD = "#F5B86E"
ORANGE_NEW = "#D14B12"
BLUE = "#3B6EA8"

# Hero agents — auto-picked at runtime from responder data
HEROES = []  # populated below


# ──────────────────────────────────────────────────────────────────────
def centroid_xy(verts):
    if not verts: return None
    xs = [v["x"] for v in verts] if isinstance(verts[0], dict) else [v[0] for v in verts]
    ys = [v["y"] for v in verts] if isinstance(verts[0], dict) else [v[1] for v in verts]
    return sum(xs)/len(xs), sum(ys)/len(ys)


print("Loading atlas + LOC2XY...")
atlas = json.load(open(ATLAS_PATH))
LOC2XY = {}
LOC2META = {}  # location_id → {"name", "type"}
for bid, b in atlas["buildings"].items():
    verts = b.get("polygon", {}).get("vertices", [])
    if verts:
        c = centroid_xy(verts)
        if c:
            LOC2XY[bid] = c
            LOC2META[bid] = {"name": b.get("name") or "", "type": b.get("building_type") or ""}
outdoor = atlas.get("outdoor_areas", {})
if isinstance(outdoor, dict): outdoor_iter = outdoor.items()
else: outdoor_iter = [(o["id"], o) for o in outdoor]
for oid, o in outdoor_iter:
    verts = o.get("polygon", {}).get("vertices", [])
    if verts:
        c = centroid_xy(verts)
        if c:
            LOC2XY[oid] = c
            LOC2META[oid] = {"name": o.get("name") or "", "type": o.get("area_type") or ""}


# ──────────────────────────────────────────────────────────────────────
# Auto-pick 4 hero agents: high deviation + at least 1 named new POI visit
# Diverse occupations, only seeds we have positions data for.
# ──────────────────────────────────────────────────────────────────────
print("Picking 4 representative responder agents...")
resp = json.load(open(ANALYSIS / "C_responder_profile/agents_hyperlocal_push.json"))
hp_responders = [r for r in resp if r.get("is_responder") and r.get("deviation_m")
                 and r.get("seed") in POS_FILES]
hp_responders.sort(key=lambda r: -(r.get("deviation_m") or 0))

profiles_by_id = {}
for f in os.listdir(POP_CACHE):
    d = json.load(open(POP_CACHE / f))
    for p in d.get("profiles", []):
        aid = p.get("agent_id")
        if aid: profiles_by_id[aid] = p

OCC_STORY = {
    "retired": ("Mary · 退休", "75 岁 · 退休"),
    "unemployed": ("Lucy · 失业中", "29 岁 · 失业 · 找工作中"),
    "engineer": ("Mike · 工程师", "26 岁 · 软件工程师"),
    "manager": ("David · 管理者", "42 岁 · 公司管理"),
    "lawyer": ("Anna · 律师", "38 岁 · 律师事务所"),
    "tradesperson": ("Jack · 工人", "35 岁 · 蓝领工人"),
    "doctor": ("Helen · 医生", "45 岁 · 医院医生"),
    "teacher": ("Sara · 教师", "32 岁 · 学校教师"),
    "accountant": ("Paul · 会计", "40 岁 · 会计师"),
}
# Pick one of each occupation; prefer ones we have data for
seen_occ = set()
HEROES_PICKED = []
for r in hp_responders:
    aid = r["agent_id"]
    p = profiles_by_id.get(aid)
    if not p: continue
    occ = (p.get("occupation") or "").lower()
    bucket = None
    for k in OCC_STORY:
        if k in occ:
            bucket = k; break
    if bucket is None or bucket in seen_occ: continue
    name_cn, occ_cn = OCC_STORY[bucket]
    if "Mary" in name_cn: occ_cn = f"{p.get('age', '?')} 岁 · 退休"
    elif "Lucy" in name_cn: occ_cn = f"{p.get('age', '?')} 岁 · 失业"
    elif "Mike" in name_cn: occ_cn = f"{p.get('age', '?')} 岁 · 软件工程师"
    elif "David" in name_cn: occ_cn = f"{p.get('age', '?')} 岁 · 公司管理"
    elif "Jack" in name_cn: occ_cn = f"{p.get('age', '?')} 岁 · 蓝领工人"
    HEROES_PICKED.append({
        "seed": r["seed"], "aid": aid, "name_cn": name_cn, "age": p.get("age"),
        "occ_cn": occ_cn, "dev": int(r["deviation_m"]),
        "story": None,  # filled in after extraction based on new_poi
    })
    seen_occ.add(bucket)
    if len(HEROES_PICKED) >= 4: break

HEROES.extend(HEROES_PICKED)
print(f"Picked: {[(h['name_cn'], h['dev']) for h in HEROES]}")

print("Loading hero agent trajectories...")
# For each hero: load BL and HP full 14-day path
hero_data = []
for h in HEROES:
    seed = h["seed"]
    aid = h["aid"]
    bl_path = REPO / POS_FILES[seed]["baseline"]
    hp_path = REPO / POS_FILES[seed]["hyperlocal_push"]

    def extract_chrono(pos_path, target_aid):
        d = json.load(open(pos_path))
        per_tick = []
        for c in d["changes"]:
            if c["agent_id"] == target_aid:
                per_tick.append((c["tick"], c["location_id"], c.get("day")))
        per_tick.sort()
        # dedupe consecutive
        seq = []
        prev = None
        for tick, loc, day in per_tick:
            if loc != prev:
                xy = LOC2XY.get(loc)
                if xy:
                    seq.append({"tick": tick, "day": day, "loc": loc, "x": xy[0], "y": xy[1]})
                    prev = loc
        return seq

    print(f"  {aid} (seed {seed})...")
    bl_seq = extract_chrono(bl_path, aid)
    hp_seq = extract_chrono(hp_path, aid)
    h["bl_path"] = bl_seq
    h["hp_path"] = hp_seq
    # Identify HP-only locations (newly discovered)
    bl_locs = {p["loc"] for p in bl_seq}
    hp_locs = {p["loc"] for p in hp_seq}
    new_locs = hp_locs - bl_locs
    # Get the most prominent new POI (named building, not road)
    new_poi_candidates = []
    for nl in new_locs:
        meta = LOC2META.get(nl, {})
        bt = meta.get("type", "")
        name = meta.get("name", "")
        if not name: continue
        if re.match(r'^road_\d+', name): continue
        if bt in ("residential", "street"): continue
        # count ticks at this location in HP path
        n_ticks = sum(1 for p in hp_seq if p["loc"] == nl)
        new_poi_candidates.append((n_ticks, nl, name, bt))
    new_poi_candidates.sort(reverse=True)
    h["new_poi"] = new_poi_candidates[:3]
    # Generate story dynamically from new POIs found
    if h["new_poi"]:
        top_poi_name = h["new_poi"][0][2]
        # Short Chinese form for known POIs
        SHORT = {
            "1021 Mediterranean": "1021 餐厅",
            "Shinnyo Australia": "真如苑",
            "Anglican Church of Australia": "圣公会教堂",
            "St Aidan's Anglican Church": "圣艾登教堂",
            "Anytime Fitness Australia": "24 小时健身房",
            "PLC Sydney Preschool, Lane Cove Campus": "长老会幼儿园",
            "Longueville Park": "Longueville Park",
        }
        short_name = SHORT.get(top_poi_name, top_poi_name[:18])
        h["story"] = f"日常→ 推送下走 {h['dev']/1000:.1f} km · 发现 <b>{short_name}</b>"
    else:
        h["story"] = f"日常→ 推送下走 {h['dev']/1000:.1f} km"
    print(f"    BL pts: {len(bl_seq)}, HP pts: {len(hp_seq)}, new locs: {len(new_locs)}, named new POIs: {len(new_poi_candidates)}, top: {h['new_poi'][0][2] if h['new_poi'] else 'none'}")
    hero_data.append(h)


# ──────────────────────────────────────────────────────────────────────
# SVG rendering
# ──────────────────────────────────────────────────────────────────────
parts = [
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" '
    f'viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">',
    f'<rect width="100%" height="100%" fill="{BG_PAPER}"/>',
]

# Header
parts.append(f'<text x="12" y="14" font-family="Georgia,serif" font-size="3.3" '
             f'font-style="italic" fill="{ACCENT_DARK}" letter-spacing="0.3">'
             f'FINDING 01b · 微观视角 · 4 个具体居民的 14 天 · 同样实验 · 一致结论</text>')
parts.append(f'<line x1="12" y1="17" x2="{W-12}" y2="17" stroke="{ACCENT_DARK}" stroke-width="0.3"/>')
parts.append(f'<text x="12" y="32" font-family="Georgia,serif" font-size="13" '
             f'font-weight="900" fill="{INK}" letter-spacing="-0.5">'
             f'4 个不同身份 · <tspan fill="{ACCENT}">推送把他们带去了不同的"附近"</tspan></text>')
parts.append(f'<text x="12" y="41" font-family="Georgia,serif" font-size="4.3" '
             f'font-style="italic" fill="{INK_SOFT}">'
             f'每张小图 = 一个居民 14 天真实路径 · 灰 = 推送前后都走的路 · 亮橙 = 推送后才发现的地方</text>')


# 2×2 grid of agent panels
gap = 4
panel_w = (W - 24 - gap) / 2
panel_h = (H - 50 - 22 - gap) / 2  # 50 = below header, 22 = takeaway band
panel_y_start = 50


def render_agent_panel(panel_x, panel_y, h):
    """Render one agent panel."""
    # Background
    parts.append(f'<rect x="{panel_x}" y="{panel_y}" width="{panel_w}" height="{panel_h}" '
                 f'fill="{MAP_LAND}" stroke="{INK}" stroke-width="0.35"/>')

    # Top header strip — agent identity
    head_h = 11
    parts.append(f'<rect x="{panel_x}" y="{panel_y}" width="{panel_w}" height="{head_h}" fill="{INK}"/>')
    parts.append(f'<text x="{panel_x+3}" y="{panel_y+4.5}" font-family="Georgia,serif" '
                 f'font-size="4" font-weight="900" fill="white">{h["name_cn"]}</text>')
    parts.append(f'<text x="{panel_x+3}" y="{panel_y+8.5}" font-family="Georgia,serif" '
                 f'font-size="2.6" font-style="italic" fill="{INK_LIGHTER}">{h["occ_cn"]}</text>')
    parts.append(f'<text x="{panel_x+panel_w-3}" y="{panel_y+8}" font-family="Georgia,serif" '
                 f'font-size="6" font-weight="900" fill="{HIGHLIGHT}" text-anchor="end">'
                 f'+{h["dev"]} m</text>')

    # Bottom caption strip (RESERVED — map area excludes this)
    cap_h = 11

    # Map area (between top header and bottom caption strip)
    map_x = panel_x; map_y = panel_y + head_h
    map_w = panel_w; map_h = panel_h - head_h - cap_h

    # Find bounding box around this agent's combined paths
    all_pts = [(p["x"], p["y"]) for p in h["bl_path"] + h["hp_path"]]
    if not all_pts:
        return
    min_x = min(p[0] for p in all_pts) - 100
    max_x = max(p[0] for p in all_pts) + 100
    min_y = min(p[1] for p in all_pts) - 100
    max_y = max(p[1] for p in all_pts) + 100
    span_x = max_x - min_x; span_y = max_y - min_y
    # Ensure equal aspect — pad smaller dimension
    target_aspect = map_w / map_h
    actual_aspect = span_x / span_y if span_y > 0 else 1
    if actual_aspect > target_aspect:
        # X is wider — extend Y
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
        return map_x + (x - min_x) * scale, map_y + (max_y - y) * scale

    def in_view(x, y):
        return min_x <= x <= max_x and min_y <= y <= max_y

    # Render base — light buildings + parks + streets in the bounding box
    for bid, b in atlas["buildings"].items():
        verts = b.get("polygon", {}).get("vertices", [])
        if len(verts) < 3: continue
        c = centroid_xy(verts)
        if not c or not in_view(*c): continue
        pts = [proj(v["x"], v["y"]) for v in verts]
        path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in pts) + " Z"
        parts.append(f'<path d="{path}" fill="{MAP_BLDG}" stroke="#9d906f" stroke-width="0.08"/>')

    odata = atlas.get("outdoor_areas", {})
    out_iter = odata.items() if isinstance(odata, dict) else [(o["id"], o) for o in odata]
    for oid, o in out_iter:
        verts = o.get("polygon", {}).get("vertices", [])
        if len(verts) < 3: continue
        c = centroid_xy(verts)
        if not c or not in_view(*c): continue
        t = o.get("area_type", "")
        pts = [proj(v["x"], v["y"]) for v in verts]
        path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in pts) + " Z"
        if t == "street":
            parts.append(f'<path d="{path}" fill="{MAP_STREET}" stroke="none"/>')
        elif t in ("park", "playground", "garden"):
            parts.append(f'<path d="{path}" fill="{MAP_PARK}" stroke="#9DBC8A" stroke-width="0.1"/>')

    # ClipPath for this panel
    clip_id = f'clip-{h["aid"]}'
    parts.append(f'<defs><clipPath id="{clip_id}"><rect x="{map_x}" y="{map_y}" '
                 f'width="{map_w}" height="{map_h}"/></clipPath></defs>')

    # === Trajectories with semantic classification ===
    bl_locs = {p["loc"] for p in h["bl_path"]}
    hp_locs = {p["loc"] for p in h["hp_path"]}

    JUMP_M = 80.0
    parts.append(f'<g clip-path="url(#{clip_id})">')

    def emit_path(seq, color_fn, allow_colors, stroke_styles):
        """seq: list of {loc, x, y}. color_fn(loc) returns color name.
        Emit polyline segments split on color change, jump>80m, out-of-view.
        stroke_styles: {color_name: (color, width, opacity)}."""
        cur_color = None
        cur_pts = []
        cur_xy = None
        def flush():
            nonlocal cur_pts, cur_color
            if cur_color in allow_colors and len(cur_pts) >= 2:
                stroke, width, opacity = stroke_styles[cur_color]
                d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in cur_pts)
                parts.append(f'<path d="{d}" fill="none" stroke="{stroke}" '
                             f'stroke-width="{width}" stroke-linejoin="round" '
                             f'stroke-linecap="round" opacity="{opacity}"/>')
            cur_pts = []
            cur_color = None
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
            if cur_color is None:
                cur_color = color; cur_pts = [(sx, sy)]
            elif color == cur_color:
                cur_pts.append((sx, sy))
            else:
                cur_pts.append((sx, sy)); flush()
                cur_pts = [(sx, sy)]; cur_color = color
            cur_xy = (x, y)
        flush()

    # Much thicker strokes since panel is small — every line must be visible
    styles_bl = {
        "shared": (GREY_SHARED, "0.6", "0.55"),
        "abandoned": (PEACH_OLD, "0.9", "0.80"),
    }
    styles_hp = {
        "new": (ORANGE_NEW, "1.4", "0.95"),  # very bold for the visual story
    }

    # BL: classify each point as shared or abandoned
    emit_path(h["bl_path"], lambda loc: "shared" if loc in hp_locs else "abandoned",
              {"shared", "abandoned"}, styles_bl)
    # HP: only "new" segments
    emit_path(h["hp_path"], lambda loc: "shared" if loc in bl_locs else "new",
              {"new"}, styles_hp)

    parts.append(f'</g>')

    # Home marker (BL first point)
    if h["bl_path"]:
        hp0 = h["bl_path"][0]
        hsx, hsy = proj(hp0["x"], hp0["y"])
        parts.append(f'<circle cx="{hsx:.1f}" cy="{hsy:.1f}" r="1.6" fill="{INK}" stroke="white" stroke-width="0.4"/>')
        parts.append(f'<text x="{hsx+2.5:.1f}" y="{hsy+0.8:.1f}" font-family="Georgia,serif" '
                     f'font-size="2.5" font-weight="900" fill="{INK}">家</text>')

    # New POI markers
    for j, (n_ticks, loc, name, bt) in enumerate(h["new_poi"][:2]):
        c = LOC2XY.get(loc)
        if not c or not in_view(*c): continue
        sx, sy = proj(*c)
        parts.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="2.8" fill="{HIGHLIGHT}" stroke="{INK}" stroke-width="0.35"/>')
        parts.append(f'<text x="{sx:.1f}" y="{sy+1.1:.1f}" font-family="Georgia,serif" '
                     f'font-size="3" font-weight="900" fill="{INK}" text-anchor="middle">{j+1}</text>')

    # Story caption — DEDICATED black band at bottom of panel (not overlapping map)
    cap_y = panel_y + panel_h - cap_h
    parts.append(f'<rect x="{panel_x}" y="{cap_y}" width="{panel_w}" height="{cap_h}" fill="{INK}"/>')
    # Strip HTML tags from story for SVG text
    story_text = h["story"].replace("<b>", "").replace("</b>", "")
    parts.append(f'<text x="{panel_x+3}" y="{cap_y+4}" font-family="Georgia,serif" '
                 f'font-size="3.2" font-weight="900" fill="{HIGHLIGHT}">'
                 f'▶ {story_text}</text>')
    # New POI list as second line
    if h["new_poi"]:
        poi_text = " · ".join(p[2][:18] for p in h["new_poi"][:2])
        parts.append(f'<text x="{panel_x+3}" y="{cap_y+8.5}" font-family="Georgia,serif" '
                     f'font-size="2.5" font-style="italic" fill="{INK_LIGHTER}">'
                     f'新发现: {poi_text}</text>')


# Render 4 panels
positions = [(12, panel_y_start),
             (12 + panel_w + gap, panel_y_start),
             (12, panel_y_start + panel_h + gap),
             (12 + panel_w + gap, panel_y_start + panel_h + gap)]
for i, h in enumerate(hero_data):
    render_agent_panel(*positions[i], h)


# Takeaway band
ty = H - 22
parts.append(f'<rect x="12" y="{ty}" width="{W-24}" height="12" fill="{INK}"/>')
parts.append(f'<text x="{W/2:.2f}" y="{ty+7.5:.2f}" font-family="Georgia,serif" '
             f'font-size="5" font-weight="900" fill="{HIGHLIGHT}" text-anchor="middle" '
             f'font-style="italic">▶  4 个完全不同的人 · 都因为同一波推送 · 走到了 14 天前从没去过的地方。</text>')
parts.append(f'<text x="{W/2:.2f}" y="{H-3:.2f}" font-family="Georgia,serif" font-size="2.3" '
             f'font-style="italic" fill="{INK_LIGHT}" text-anchor="middle">'
             f'Synthetic Socio Wind Tunnel · 悉尼 Lane Cove 虚拟城市 · 真实 positions.json 14 天完整路径 · github.com/york-zhouuu</text>')

parts.append("</svg>")
OUT_PATH.write_text("\n".join(parts))
print(f"\nWrote {OUT_PATH} · {OUT_PATH.stat().st_size / 1e3:.0f} KB")
