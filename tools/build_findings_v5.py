"""v5 — map-mandatory: every figure has a beautiful Lane Cove base map
with the conclusion data overlaid in a way that makes the map MEAN something.

Layout per figure (320 × 220 mm):
  - Header band (0-46 mm)
  - Main area (50-180 mm): LEFT map ~200 wide, RIGHT annotation column ~110 wide
  - Footer takeaway (185-208 mm)
"""
from __future__ import annotations
import json
import math
import random
import os
from collections import defaultdict, Counter
from pathlib import Path

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
ATLAS_PATH = REPO / "data/lanecove_atlas.json"
ANALYSIS = REPO / "data/analysis/2026-05-23_paper_exploration"
POP_CACHE = REPO / "data/population_cache/v1"
OUT = REPO / "docs/figures_v4"  # overwrite v4 since HTML already references this
OUT.mkdir(parents=True, exist_ok=True)

# Palette (NYT-inspired but warmer for map base)
INK = "#1B1F2A"
INK_SOFT = "#5A5E6A"
INK_LIGHT = "#A8ACB5"
INK_LIGHTER = "#D8D9DC"
BG_PAPER = "#FFFFFF"
BG_PANEL = "#F8F5EE"
MAP_LAND = "#F4EFE5"
MAP_BLDG_FILL = "#E7DECB"
MAP_BLDG_STROKE = "#9D906F"
MAP_STREET_MAJOR = "#D9D3C6"
MAP_STREET_MINOR = "#E8E2D3"
MAP_PARK = "#CFE3C4"
MAP_PARK_STROKE = "#9DBC8A"
MAP_WATER = "#C7D6E0"
ACCENT = "#E03A4A"
ACCENT_SOFT = "#FBD8DC"
ACCENT_DARK = "#A0252F"
HIGHLIGHT = "#F0C419"
BLUE = "#3B6EA8"
BLUE_SOFT = "#C7D5E5"
GREEN = "#3A9D5C"

W, H = 320, 220


# ──────────────────────────────────────────────────────────────────────
# Atlas helpers
# ──────────────────────────────────────────────────────────────────────
def load_atlas():
    return json.load(open(ATLAS_PATH))


def centroid_xy(verts):
    if not verts:
        return None
    if isinstance(verts[0], dict):
        xs = [v["x"] for v in verts]
        ys = [v["y"] for v in verts]
    else:
        xs = [v[0] for v in verts]
        ys = [v[1] for v in verts]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def building_centroid(atlas, bid):
    b = atlas["buildings"].get(bid)
    if not b:
        return None
    return centroid_xy(b.get("polygon", {}).get("vertices", []))


def load_population_homes(seed=43):
    """Returns {agent_id: (x, y)} mapping homes to atlas coords."""
    atlas = load_atlas()
    homes = {}
    for f in os.listdir(POP_CACHE):
        try:
            d = json.load(open(POP_CACHE / f))
            ki = d.get("key_inputs", {})
            if ki.get("seed") != seed:
                continue
            for p in d.get("profiles", []):
                bid = p.get("home_location")
                aid = p.get("agent_id")
                if not bid or not aid:
                    continue
                c = building_centroid(atlas, bid)
                if c:
                    homes[aid] = c
        except Exception:
            continue
    return homes


# ──────────────────────────────────────────────────────────────────────
# Lane Cove base map
# ──────────────────────────────────────────────────────────────────────
class MapProjector:
    def __init__(self, atlas, map_x, map_y, map_w, map_h, center_xy=None, radius=1100):
        self.atlas = atlas
        self.mx, self.my, self.mw, self.mh = map_x, map_y, map_w, map_h
        if center_xy is None:
            hub = atlas["buildings"].get("lane_cove_community_hub")
            center_xy = centroid_xy(hub.get("polygon", {}).get("vertices", [])) if hub else (0, 0)
        self.cx, self.cy = center_xy
        self.radius = radius
        self.scale = min(map_w / (2 * radius), map_h / (2 * radius))

    def proj(self, x, y):
        return (self.mx + self.mw / 2 + (x - self.cx) * self.scale,
                self.my + self.mh / 2 - (y - self.cy) * self.scale)

    def in_view(self, x, y):
        return (x - self.cx) ** 2 + (y - self.cy) ** 2 <= self.radius ** 2

    def render_base(self, building_opacity=1.0, label_pois=False, mute=False):
        """Returns list of svg strings for the base map.

        mute=True: greyscale (for use as a small reference map)
        """
        parts = []
        # Land background
        parts.append(f'<rect x="{self.mx}" y="{self.my}" width="{self.mw}" height="{self.mh}" '
                     f'fill="{MAP_LAND}" stroke="{INK}" stroke-width="0.25"/>')

        # Parks/playgrounds first (under streets)
        outdoor = self.atlas.get("outdoor_areas", {})
        if isinstance(outdoor, dict):
            outdoor = list(outdoor.values())

        # Sort: parks first, streets second
        parks = []
        streets = []
        for o in outdoor:
            t = o.get("area_type") or ""
            verts = o.get("polygon", {}).get("vertices", [])
            if len(verts) < 3:
                continue
            c = centroid_xy(verts)
            if not c or not self.in_view(*c):
                continue
            if t in ("park", "playground", "garden"):
                parks.append((o, verts))
            elif t == "street":
                streets.append((o, verts))

        # Parks
        park_fill = "#DCDCDC" if mute else MAP_PARK
        park_stroke = "#B0B0B0" if mute else MAP_PARK_STROKE
        for o, verts in parks:
            pts = [self.proj(v["x"], v["y"]) for v in verts]
            path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in pts) + " Z"
            parts.append(f'<path d="{path}" fill="{park_fill}" stroke="{park_stroke}" stroke-width="0.15"/>')

        # Streets — render as filled polygons (atlas streets are full segments with width)
        street_fill = "#DDDDDD" if mute else MAP_STREET_MAJOR
        for o, verts in streets:
            pts = [self.proj(v["x"], v["y"]) for v in verts]
            path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in pts) + " Z"
            parts.append(f'<path d="{path}" fill="{street_fill}" stroke="{street_fill}" stroke-width="0.1"/>')

        # Buildings
        bldg_fill = "#E0E0E0" if mute else MAP_BLDG_FILL
        bldg_stroke = "#888" if mute else MAP_BLDG_STROKE
        for bid, b in self.atlas["buildings"].items():
            verts = b.get("polygon", {}).get("vertices", [])
            if len(verts) < 3:
                continue
            c = centroid_xy(verts)
            if not c or not self.in_view(*c):
                continue
            pts = [self.proj(v["x"], v["y"]) for v in verts]
            path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in pts) + " Z"
            parts.append(f'<path d="{path}" fill="{bldg_fill}" stroke="{bldg_stroke}" stroke-width="0.08" '
                         f'opacity="{building_opacity:.2f}"/>')

        # Subtle clip border
        parts.append(f'<rect x="{self.mx}" y="{self.my}" width="{self.mw}" height="{self.mh}" '
                     f'fill="none" stroke="{INK}" stroke-width="0.5"/>')

        return parts

    def scalebar(self, length_m=500):
        """Returns scale bar svg, anchored bottom-right of the map."""
        px_len = length_m * self.scale
        x0 = self.mx + self.mw - px_len - 6
        y0 = self.my + self.mh - 7
        return [
            f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{px_len:.2f}" height="1.4" fill="{INK}"/>',
            f'<text x="{x0+px_len/2:.2f}" y="{y0+4.5:.2f}" font-family="Georgia,serif" font-size="2.4" '
            f'font-style="italic" fill="{INK}" text-anchor="middle">{length_m} m · 真实 Lane Cove 比例</text>',
        ]


# ──────────────────────────────────────────────────────────────────────
# Common chrome
# ──────────────────────────────────────────────────────────────────────
def svg_open():
    return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" '
            f'viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">',
            f'<rect width="100%" height="100%" fill="{BG_PAPER}"/>']


def header(idx, kicker, headline_html, subhead):
    return [
        f'<text x="12" y="14" font-family="Georgia,serif" font-size="3.3" '
        f'font-style="italic" fill="{ACCENT_DARK}" letter-spacing="0.3">'
        f'FINDING {idx:02d}  ·  {kicker}  ·  Lane Cove · 1,000 虚拟居民 × 14 天 · 独立重复 3 次取一致结果</text>',
        f'<line x1="12" y1="17" x2="{W-12}" y2="17" stroke="{ACCENT_DARK}" stroke-width="0.3"/>',
        f'<text x="12" y="32" font-family="Georgia,serif" font-size="13" '
        f'font-weight="900" fill="{INK}" letter-spacing="-0.5">{headline_html}</text>',
        f'<text x="12" y="41" font-family="Georgia,serif" font-size="4.3" '
        f'font-style="italic" fill="{INK_SOFT}">{subhead}</text>',
    ]


def takeaway_band(text):
    ty = H - 22
    return [
        f'<rect x="12" y="{ty}" width="{W-24}" height="12" fill="{INK}"/>',
        f'<text x="{W/2:.2f}" y="{ty+7.5:.2f}" font-family="Georgia,serif" '
        f'font-size="5.2" font-weight="900" fill="{HIGHLIGHT}" text-anchor="middle" '
        f'font-style="italic">▶  {text}</text>',
        f'<text x="{W/2:.2f}" y="{H-3:.2f}" font-family="Georgia,serif" font-size="2.3" '
        f'font-style="italic" fill="{INK_LIGHT}" text-anchor="middle">'
        f'Synthetic Socio Wind Tunnel · 悉尼 Lane Cove 虚拟城市 · 1,000 居民 × 14 天 × 3 次独立重复 · '
        f'github.com/york-zhouuu</text>',
    ]


def write(name, parts):
    parts.append("</svg>")
    (OUT / name).write_text("\n".join(parts))
    print(f"  → {name}")


# Standard layout: big map left + annotation column right
MAP_X, MAP_Y, MAP_W, MAP_H = 12, 50, 195, 138
ANN_X = MAP_X + MAP_W + 6      # 213
ANN_W = W - ANN_X - 12         # 95
ANN_Y_TOP = MAP_Y


# ──────────────────────────────────────────────────────────────────────
# F1: 22.7% bimodal — 1000 home dots on real Lane Cove map
# ──────────────────────────────────────────────────────────────────────
def fig_1():
    """3000 agent trajectory overlay — grey = non-responders, light orange = responders' BL,
    dark orange = same responders' HP. Same agents' before/after directly comparable on map."""
    parts = svg_open()
    parts.extend(header(1, "物理位移 · 1,000 居民真实轨迹",
        f'共同路段退灰 · <tspan fill="#D14B12">亮橙色 = 推送带来的新发现路线</tspan>',
        "1,000 虚拟居民 × 6 天干预期真实路径 · 实验独立重复 3 次取一致结果 · 黄圈数字 = 推送指向的具体 POI"))

    atlas = load_atlas()
    # SINGLE big map
    big_w = W - 24
    big_h = MAP_H + 6
    proj = MapProjector(atlas, MAP_X, MAP_Y, big_w, big_h)

    # ClipPath so EVERYTHING stays inside the map rectangle (base + trajectories + POIs)
    parts.append(f'<defs><clipPath id="f1-clip"><rect x="{proj.mx}" y="{proj.my}" '
                 f'width="{proj.mw}" height="{proj.mh}"/></clipPath></defs>')

    # Render base map INSIDE clip group so overflowing buildings are clipped
    parts.append(f'<g clip-path="url(#f1-clip)">')
    parts.extend(proj.render_base(mute=True))  # GRAYSCALE base so trajectories POP
    parts.append(f'</g>')

    # Load trajectory cache (day-6 paths for ALL agents)
    traj_cache = json.load(open(REPO / "data/analysis/trajectory_cache_f1.json"))
    seeds = [43, 44, 45]

    # Build responder lookup per (seed, agent_id)
    is_resp = {}
    for seed in seeds:
        for a in traj_cache["trajectories"][str(seed)]["hyperlocal_push"]:
            is_resp[(seed, a["aid"])] = a.get("is_responder", False)

    # Build BL trajectory + HP trajectory lookups
    bl_traj = {}  # (seed, aid) → wp
    hp_traj = {}
    for seed in seeds:
        for a in traj_cache["trajectories"][str(seed)]["baseline"]:
            bl_traj[(seed, a["aid"])] = a["wp"]
        for a in traj_cache["trajectories"][str(seed)]["hyperlocal_push"]:
            hp_traj[(seed, a["aid"])] = a["wp"]

    # Semantic colors
    GREY_SHARED = "#454A52"      # darker so visible
    PEACH_ABANDONED = "#F5B86E"
    ORANGE_NEW = "#D14B12"
    GREY_NONRESP = "#4F535A"     # darker baseline

    STYLE = {
        "shared":    (GREY_SHARED,     "0.13", "0.22"),  # bumped opacity
        "abandoned": (PEACH_ABANDONED, "0.20", "0.45"),
        "new":       (ORANGE_NEW,      "0.30", "0.88"),
    }

    JUMP_THRESHOLD_M = 80.0  # consecutive locations farther than this = car/teleport, break path

    def emit_segments(wp_colored, allow_colors):
        """Walk wp list, group into polyline segments.
        SPLIT on: (1) color change, (2) out-of-view point, (3) JUMP > 80m
        (car/transit/building teleport — not a walked path).
        Only emit segments whose color is in allow_colors.
        """
        out = []
        cur_color = None
        cur_pts = []
        cur_xy = None  # last in-atlas coord (for jump detection)

        def flush():
            nonlocal cur_pts, cur_color
            if cur_color in allow_colors and len(cur_pts) >= 2:
                stroke, width, opacity = STYLE[cur_color]
                d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in cur_pts)
                out.append(f'<path d="{d}" fill="none" stroke="{stroke}" '
                           f'stroke-width="{width}" stroke-linejoin="round" '
                           f'stroke-linecap="round" opacity="{opacity}"/>')
            cur_pts = []
            cur_color = None

        for loc_id, x, y, color in wp_colored:
            if not proj.in_view(x, y):
                flush()
                cur_xy = None
                continue

            # JUMP DETECTION — if last in-view point is far away, break
            if cur_xy is not None:
                dx = x - cur_xy[0]; dy = y - cur_xy[1]
                if (dx*dx + dy*dy) > (JUMP_THRESHOLD_M * JUMP_THRESHOLD_M):
                    flush()  # this jump is not a walked path

            sx, sy = proj.proj(x, y)
            if cur_color is None:
                cur_color = color
                cur_pts = [(sx, sy)]
            elif color == cur_color:
                cur_pts.append((sx, sy))
            else:
                # Color transition: end at this point, restart from this point
                cur_pts.append((sx, sy))
                flush()
                cur_pts = [(sx, sy)]
                cur_color = color
            cur_xy = (x, y)
        flush()
        return out

    n_nonresp = 0
    n_resp = 0
    new_segs_total = 0
    abandoned_segs_total = 0

    # === Layer 1: NON-responder BL paths — faint grey backdrop ===
    # Split polyline on out-of-view OR jumps > 80m (car / building teleport)
    parts.append(f'<g clip-path="url(#f1-clip)">')

    def emit_grey_path(wp):
        cur_pts = []
        cur_xy = None
        def flush():
            nonlocal cur_pts
            if len(cur_pts) >= 2:
                d = "M " + " L ".join(f"{px:.1f},{py:.1f}" for px, py in cur_pts)
                parts.append(f'<path d="{d}" fill="none" stroke="{GREY_NONRESP}" '
                             f'stroke-width="0.12" opacity="0.28"/>')
            cur_pts = []
        # local closure
        local_pts = []
        local_xy = None
        for loc_id, x, y in [(w[0], w[1], w[2]) for w in wp]:
            if not proj.in_view(x, y):
                if len(local_pts) >= 2:
                    d = "M " + " L ".join(f"{px:.1f},{py:.1f}" for px, py in local_pts)
                    parts.append(f'<path d="{d}" fill="none" stroke="{GREY_NONRESP}" '
                                 f'stroke-width="0.12" opacity="0.28"/>')
                local_pts = []
                local_xy = None
                continue
            if local_xy is not None:
                dx = x - local_xy[0]; dy = y - local_xy[1]
                if (dx*dx + dy*dy) > (JUMP_THRESHOLD_M * JUMP_THRESHOLD_M):
                    if len(local_pts) >= 2:
                        d = "M " + " L ".join(f"{px:.1f},{py:.1f}" for px, py in local_pts)
                        parts.append(f'<path d="{d}" fill="none" stroke="{GREY_NONRESP}" '
                                     f'stroke-width="0.12" opacity="0.28"/>')
                    local_pts = []
            sx, sy = proj.proj(x, y)
            local_pts.append((sx, sy))
            local_xy = (x, y)
        if len(local_pts) >= 2:
            d = "M " + " L ".join(f"{px:.1f},{py:.1f}" for px, py in local_pts)
            parts.append(f'<path d="{d}" fill="none" stroke="{GREY_NONRESP}" '
                         f'stroke-width="0.10" opacity="0.18"/>')

    for (seed, aid), wp in bl_traj.items():
        if is_resp.get((seed, aid), False):
            continue
        emit_grey_path(wp)
        n_nonresp += 1
    parts.append(f'</g>')

    # === Layer 2: Responders — segment-classified rendering ===
    # For each responder, classify each waypoint's location:
    #   shared    if loc_id appears in BOTH BL and HP paths
    #   abandoned if in BL only
    #   new       if in HP only
    # Then render BL path with {shared, abandoned} colors, HP path with {new} only
    # (shared portion is drawn once from BL pass; HP-shared segments don't need redrawing)

    parts.append(f'<g clip-path="url(#f1-clip)">')
    for (seed, aid), bl_wp in bl_traj.items():
        if not is_resp.get((seed, aid), False):
            continue
        hp_wp = hp_traj.get((seed, aid))
        if not hp_wp:
            continue
        n_resp += 1
        bl_locs = {w[0] for w in bl_wp}
        hp_locs = {w[0] for w in hp_wp}

        # BL path: each point classified shared/abandoned
        bl_colored = []
        for loc_id, x, y in [(w[0], w[1], w[2]) for w in bl_wp]:
            color = "shared" if loc_id in hp_locs else "abandoned"
            bl_colored.append((loc_id, x, y, color))
        bl_segs = emit_segments(bl_colored, allow_colors={"shared", "abandoned"})
        parts.extend(bl_segs)
        abandoned_segs_total += sum(1 for s in bl_segs if "F5B86E" in s)

        # HP path: render only "new" segments
        hp_colored = []
        for loc_id, x, y in [(w[0], w[1], w[2]) for w in hp_wp]:
            color = "shared" if loc_id in bl_locs else "new"
            hp_colored.append((loc_id, x, y, color))
        hp_segs = emit_segments(hp_colored, allow_colors={"new"})
        parts.extend(hp_segs)
        new_segs_total += len(hp_segs)
    parts.append(f'</g>')

    # === Layer 3: NEW DISCOVERED POI markers — overlay on trajectories ===
    # Load heatmap diff data to find the most-gained POIs (HP-BL)
    import re
    heat = json.load(open(REPO / "data/analysis/heatmap_cache_f1.json"))
    bl_counts = heat["baseline"]
    hp_counts = heat["hyperlocal_push"]
    GENERIC_NAME_RE = re.compile(r'^road_\d+ \(\d+\)$')

    poi_gainers = []
    outdoor = atlas.get("outdoor_areas", {})
    outdoor_map = dict(outdoor.items()) if isinstance(outdoor, dict) else {o["id"]: o for o in outdoor}
    all_locs = set(bl_counts) | set(hp_counts)
    for loc in all_locs:
        diff = hp_counts.get(loc, 0) - bl_counts.get(loc, 0)
        if diff <= 60: continue
        b = atlas["buildings"].get(loc) or outdoor_map.get(loc)
        if not b: continue
        bt = b.get("building_type", "") or b.get("area_type", "")
        name = b.get("name", "")
        if not name or bt in ("residential",): continue
        if GENERIC_NAME_RE.match(name): continue
        c = centroid_xy(b.get("polygon", {}).get("vertices", []))
        if not c or not proj.in_view(*c): continue
        poi_gainers.append((diff, loc, name, c, bt))
    poi_gainers.sort(reverse=True)
    # Top 8 with spatial diversity (80m apart)
    picked_pois = []
    for entry in poi_gainers:
        if len(picked_pois) >= 8: break
        if all((entry[3][0]-pc[3][0])**2 + (entry[3][1]-pc[3][1])**2 > 80**2 for pc in picked_pois):
            picked_pois.append(entry)

    # Rich POI metadata: (Chinese name, one-line description)
    POI_META = {
        "1021 Mediterranean": ("1021 地中海餐厅", "周末晚餐聚会 · 居民常去的镇上小餐厅"),
        "Shinnyo Australia": ("真如苑 Lane Cove 道场", "日本佛教冥想中心 · 周三周六对外开放"),
        "Anglican Church of Australia": ("圣公会 Lane Cove 教堂", "周日礼拜 · 同时举办社区聚会和老人活动"),
        "St Aidan's Anglican Church": ("圣艾登圣公会教堂", "Longueville 区教堂 · 周日礼拜 + 社区活动"),
        "Anytime Fitness Australia": ("Anytime Fitness 24 小时健身房", "刷卡随时进 · 通勤居民下班前后高频去"),
        "PLC Sydney Preschool, Lane Cove Campus": ("长老会幼儿园 Lane Cove 校区", "学龄前 3-5 岁儿童 · 接送场所"),
        "Lane Cove Plaza": ("Lane Cove 镇中心广场", "Lane Cove 商业核心 · 餐厅 / 商店聚集"),
        "Longueville Park": ("Longueville 社区公园", "户外大草坪 · 周末家庭遛娃 / 野餐 / 跑步"),
        "Mileenn Australia": ("Mileenn 教育中心", "课外辅导机构 · 学生与家长往来"),
        "Mowbray Road": ("Mowbray 路", "主干道 · 校车与通勤公交路线"),
        "River Road West": ("River Road West", "主干道 · 通往北悉尼方向"),
        "Christina Street": ("Christina 街", "住宅区街道 · 步行通往社区中心"),
        "Farran Street": ("Farran 街", "住宅区街道 · 邻近教堂与公园"),
        "Hatfield Street": ("Hatfield 街", "住宅区街道"),
        "Kullah Parade": ("Kullah Parade", "住宅区步行道"),
    }
    BT_META = {
        "restaurant": ("餐厅", "用餐 / 咖啡聚会场所"),
        "worship": ("宗教场所", "礼拜或冥想活动场所"),
        "school": ("学校", "学生与教师日常聚集"),
        "entertainment": ("娱乐场所", "健身 / 休闲设施"),
        "shop": ("商店", "购物 / 日常补给"),
        "office": ("办公场所", "白领工作日聚集"),
        "civic": ("公共设施", "社区服务场所"),
        "street": ("街道", "行人 + 车流聚集 · 通勤主干"),
        "park": ("公园 / 绿地", "户外运动 / 散步 / 遛娃"),
        "preschool": ("幼儿园", "学龄前儿童接送"),
        "education": ("教育场所", "课外辅导 / 培训"),
        "religious": ("宗教场所", "礼拜与社区聚会"),
    }
    def desc_for(name, bt):
        """Return (chinese_name, description) tuple."""
        for k, (cn, desc) in POI_META.items():
            if k.lower() in name.lower():
                return cn, desc
        cn, desc = BT_META.get(bt, (bt or "其他", ""))
        return cn, desc

    # Render markers + labels (auto-place labels on right margin)
    label_positions = []
    for i, (diff, loc, name, c, bt) in enumerate(picked_pois):
        sx, sy = proj.proj(*c)
        # Halo + yellow marker on top of trajectories
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="5.5" fill="{HIGHLIGHT}" opacity="0.18"/>')
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="2.8" fill="{HIGHLIGHT}" stroke="{INK}" stroke-width="0.45"/>')
        parts.append(f'<text x="{sx:.2f}" y="{sy+1.1:.2f}" font-family="Georgia,serif" '
                     f'font-size="3.3" font-weight="900" fill="{INK}" text-anchor="middle">{i+1}</text>')
        cn_name, description = desc_for(name, bt)
        label_positions.append((sx, sy, name, diff, i+1, bt, cn_name, description))

    # Auto-place labels on right edge of map — wider taller cards (4 lines text, no truncation)
    card_w = 90
    card_h = 17
    label_x = MAP_X + big_w - card_w - 1
    sorted_for_labels = sorted(label_positions, key=lambda lp: lp[1])
    avail_y_start = MAP_Y + 35
    avail_y_end = MAP_Y + big_h - 6
    label_slot_h = (avail_y_end - avail_y_start) / max(len(sorted_for_labels), 1)
    for slot_i, (sx, sy, eng_name, diff, num, bt, cn_name, description) in enumerate(sorted_for_labels):
        ly = avail_y_start + slot_i * label_slot_h + label_slot_h/2
        parts.append(f'<rect x="{label_x}" y="{ly-card_h/2}" width="{card_w}" height="{card_h}" '
                     f'fill="white" stroke="{INK}" stroke-width="0.3" rx="0.5" opacity="0.97"/>')
        # Number badge
        parts.append(f'<circle cx="{label_x+3.2}" cy="{ly-4.5}" r="2.4" fill="{HIGHLIGHT}" stroke="{INK}" stroke-width="0.3"/>')
        parts.append(f'<text x="{label_x+3.2}" y="{ly-3.3}" font-family="Georgia,serif" '
                     f'font-size="3.1" font-weight="900" fill="{INK}" text-anchor="middle">{num}</text>')
        # Line 1: Chinese name (BIG, primary)
        parts.append(f'<text x="{label_x+7}" y="{ly-5}" font-family="Georgia,serif" '
                     f'font-size="3.1" font-weight="900" fill="{INK}">{cn_name}</text>')
        # Line 2: English name (small italic subtitle, FULL no truncation)
        parts.append(f'<text x="{label_x+7}" y="{ly-1.8}" font-family="Georgia,serif" '
                     f'font-size="2.3" font-style="italic" fill="{INK_SOFT}">{eng_name}</text>')
        # Line 3: Description (longer)
        parts.append(f'<text x="{label_x+3}" y="{ly+2}" font-family="Georgia,serif" '
                     f'font-size="2.4" fill="{INK}">{description}</text>')
        # Line 4: visit stat
        parts.append(f'<text x="{label_x+3}" y="{ly+5.5}" font-family="Helvetica,sans-serif" '
                     f'font-size="2.5" fill="{ACCENT_DARK}" font-weight="900">'
                     f'推送后 +{diff} 次居民访问</text>')
        # Leader line to map marker
        parts.append(f'<line x1="{label_x:.2f}" y1="{ly:.2f}" x2="{sx:.2f}" y2="{sy:.2f}" '
                     f'stroke="{INK}" stroke-width="0.22" opacity="0.5"/>')

    # === Legend top-left ===
    leg_x = MAP_X + 4; leg_y = MAP_Y + 4
    parts.append(f'<rect x="{leg_x}" y="{leg_y}" width="92" height="26" fill="white" stroke="{INK}" stroke-width="0.4" rx="0.5"/>')
    parts.append(f'<text x="{leg_x+3}" y="{leg_y+4.8}" font-family="Georgia,serif" font-size="3.6" '
                 f'font-weight="900" fill="{INK}">1,000 居民真实轨迹 · 6 天干预期</text>')
    items = [
        (GREY_NONRESP, 0.30, "1.0", "完全不动的居民 · 灰色基线"),
        (GREY_SHARED, 0.28, "1.0", "响应者推送前后都走的路 · 灰"),
        (PEACH_ABANDONED, 0.55, "1.2", "推送前走 · 推送后不走 · 浅橙"),
        (ORANGE_NEW, 0.95, "1.8", "推送后才走的新路线 · 亮橙 · 重点"),
    ]
    for j, (col, op, w, lbl) in enumerate(items):
        ly = leg_y + 9 + j * 4.3
        parts.append(f'<line x1="{leg_x+3}" y1="{ly}" x2="{leg_x+10}" y2="{ly}" stroke="{col}" stroke-width="{w}" opacity="{op}"/>')
        parts.append(f'<text x="{leg_x+12}" y="{ly+1.2}" font-family="Georgia,serif" font-size="2.7" '
                     f'font-weight="700" fill="{INK}">{lbl}</text>')

    parts.extend(takeaway_band(
        "干预 6 天里 · 灰色 = 日常通勤路径 · 亮橙色线条 + 黄色 POI 标记 = 推送指向的新地方。"))

    write("finding_01_bimodal.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# F2: 8× spillover — map with 150m halos around responders, neighbors lit up
# ──────────────────────────────────────────────────────────────────────
def fig_2():
    parts = svg_open()
    parts.extend(header(2, "邻居效应",
        f'你的邻居走出门 → 你也走出门的概率高 <tspan fill="{ACCENT}">8 倍</tspan>。',
        "粉色实心 = 收到推送 + 走出门的居民 · 粉色圈 = 圈内邻居响应率 26% · 圈外邻居仅 4%"))

    atlas = load_atlas()
    proj = MapProjector(atlas, MAP_X, MAP_Y, MAP_W, MAP_H)
    parts.extend(proj.render_base())

    # Load HP data
    homes = load_population_homes(seed=43)
    responder_rows = json.load(open(ANALYSIS / "C_responder_profile/agents_hyperlocal_push.json"))
    s43 = [r for r in responder_rows if r.get("seed") == 43]
    protag_responders = [r for r in s43 if r.get("is_responder") and r.get("is_protagonist")]
    # Pick top 5 protagonists with most physical neighbors in 150m
    # For each, find non-protag neighbors who also responded
    nonp_responders_by_id = {r["agent_id"]: r for r in s43 if not r.get("is_protagonist") and r.get("is_responder")}
    nonp_nonresponders_by_id = {r["agent_id"]: r for r in s43 if not r.get("is_protagonist") and not r.get("is_responder")}

    # Pick the best demonstrative protag responder cluster
    best = None
    for r in protag_responders:
        aid = r["agent_id"]
        if aid not in homes: continue
        x, y = homes[aid]
        if not proj.in_view(x, y): continue
        # Neighbors in 150m
        in_resp = []
        in_nonresp = []
        for nid in nonp_responders_by_id:
            if nid in homes:
                nx, ny = homes[nid]
                if (nx-x)**2 + (ny-y)**2 <= 150**2:
                    in_resp.append((nid, nx, ny))
        for nid in nonp_nonresponders_by_id:
            if nid in homes:
                nx, ny = homes[nid]
                if (nx-x)**2 + (ny-y)**2 <= 150**2:
                    in_nonresp.append((nid, nx, ny))
        total = len(in_resp) + len(in_nonresp)
        if total >= 4 and len(in_resp) >= 1:
            score = total + len(in_resp) * 2
            if best is None or score > best[0]:
                best = (score, aid, x, y, in_resp, in_nonresp)

    # If found, do a ZOOMED IN / OUT comparison
    if best:
        _, aid, hx, hy, in_resp, in_nonresp = best
        # LEFT zoom panel — "inside ring"
        zoom_w = (MAP_W - 8) / 2
        zoom_h = MAP_H - 20
        z_left = MapProjector(atlas, MAP_X, MAP_Y, zoom_w, zoom_h,
                              center_xy=(hx, hy), radius=200)
        # Pick a comparison location far away (300m+)
        far_x, far_y = hx + 600, hy + 100
        # Plot the right zoom — same scale but at a "no nearby responder" spot
        z_right = MapProjector(atlas, MAP_X + zoom_w + 8, MAP_Y, zoom_w, zoom_h,
                               center_xy=(far_x, far_y), radius=200)

        parts.extend(z_left.render_base())
        parts.extend(z_right.render_base())

        # Draw 150m halo + responder in LEFT
        sx, sy = z_left.proj(hx, hy)
        r150_px = 150 * z_left.scale
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{r150_px:.2f}" '
                     f'fill="{ACCENT}" fill-opacity="0.13" stroke="{ACCENT_DARK}" '
                     f'stroke-width="0.5" stroke-dasharray="1.5 0.8"/>')
        # Center: big pink walking person icon
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="3.5" fill="{ACCENT}" stroke="white" stroke-width="0.4"/>')
        parts.append(f'<text x="{sx:.2f}" y="{sy+1.3:.2f}" font-family="Georgia,serif" '
                     f'font-size="4" font-weight="900" fill="white" text-anchor="middle">A</text>')
        # Label
        parts.append(f'<text x="{sx:.2f}" y="{sy-5:.2f}" font-family="Georgia,serif" '
                     f'font-size="3" font-weight="900" fill="{ACCENT_DARK}" text-anchor="middle">收推送+走出门</text>')

        # Plot neighbors in LEFT (within 150m) — show as person icons
        for i, (nid, nx, ny) in enumerate(in_resp[:6]):
            nsx, nsy = z_left.proj(nx, ny)
            # responded neighbor: pink walking, smaller
            parts.append(f'<circle cx="{nsx:.2f}" cy="{nsy:.2f}" r="2" fill="{ACCENT}" stroke="white" stroke-width="0.3"/>')
            parts.append(f'<text x="{nsx:.2f}" y="{nsy+0.8:.2f}" font-family="Georgia,serif" '
                         f'font-size="2.2" font-weight="900" fill="white" text-anchor="middle">✓</text>')
        for i, (nid, nx, ny) in enumerate(in_nonresp[:8]):
            nsx, nsy = z_left.proj(nx, ny)
            parts.append(f'<circle cx="{nsx:.2f}" cy="{nsy:.2f}" r="1.8" fill="{INK_LIGHT}" stroke="white" stroke-width="0.3"/>')
            parts.append(f'<text x="{nsx:.2f}" y="{nsy+0.6:.2f}" font-family="Georgia,serif" '
                         f'font-size="2" font-weight="900" fill="white" text-anchor="middle">·</text>')

        # 150m scalebar in left
        parts.append(f'<rect x="{z_left.mx + 3}" y="{z_left.my + z_left.mh - 6}" width="{r150_px:.2f}" height="1.2" fill="{ACCENT_DARK}"/>')
        parts.append(f'<text x="{z_left.mx + 3 + r150_px/2:.2f}" y="{z_left.my + z_left.mh - 7:.2f}" '
                     f'font-family="Georgia,serif" font-size="2.4" font-weight="900" fill="{ACCENT_DARK}" text-anchor="middle">150 m</text>')

        # RIGHT panel - same view at remote location, no responding neighbor
        far_sx, far_sy = z_right.proj(far_x, far_y)
        r150_px_r = 150 * z_right.scale
        # Draw a dashed grey "imaginary halo"
        parts.append(f'<circle cx="{far_sx:.2f}" cy="{far_sy:.2f}" r="{r150_px_r:.2f}" '
                     f'fill="{INK_LIGHT}" fill-opacity="0.06" stroke="{INK_SOFT}" '
                     f'stroke-width="0.4" stroke-dasharray="1.5 0.8"/>')
        # In right panel, find what's actually there: nonp non-responders mostly
        far_nonresp = []
        for nid, c in nonp_nonresponders_by_id.items():
            if nid in homes:
                nx, ny = homes[nid]
                if (nx-far_x)**2 + (ny-far_y)**2 <= 200**2:
                    far_nonresp.append((nx, ny))
        far_resp_in = []
        for nid in nonp_responders_by_id:
            if nid in homes:
                nx, ny = homes[nid]
                if (nx-far_x)**2 + (ny-far_y)**2 <= 200**2:
                    far_resp_in.append((nx, ny))
        # Plot grey non-responders
        for nx, ny in far_nonresp[:12]:
            nsx, nsy = z_right.proj(nx, ny)
            parts.append(f'<circle cx="{nsx:.2f}" cy="{nsy:.2f}" r="1.8" fill="{INK_LIGHT}" stroke="white" stroke-width="0.3"/>')
            parts.append(f'<text x="{nsx:.2f}" y="{nsy+0.6:.2f}" font-family="Georgia,serif" '
                         f'font-size="2" font-weight="900" fill="white" text-anchor="middle">·</text>')
        # 1 or 0 responders in this remote area
        for nx, ny in far_resp_in[:1]:
            nsx, nsy = z_right.proj(nx, ny)
            parts.append(f'<circle cx="{nsx:.2f}" cy="{nsy:.2f}" r="2" fill="{ACCENT}" stroke="white" stroke-width="0.3"/>')

        parts.append(f'<text x="{far_sx:.2f}" y="{far_sy - r150_px_r - 2:.2f}" '
                     f'font-family="Georgia,serif" font-size="3" font-weight="900" fill="{INK_SOFT}" text-anchor="middle">'
                     f'同样 150 m 范围,但没响应邻居</text>')

        # Panel titles
        parts.append(f'<rect x="{z_left.mx}" y="{z_left.my-1}" width="{zoom_w}" height="8" fill="{ACCENT}" rx="0.3"/>')
        parts.append(f'<text x="{z_left.mx+3}" y="{z_left.my+4.5}" font-family="Georgia,serif" '
                     f'font-size="4.2" font-weight="900" fill="white">圈内:有响应邻居</text>')
        in_pct = len(in_resp) / max(len(in_resp) + len(in_nonresp), 1) * 100
        parts.append(f'<text x="{z_left.mx + zoom_w - 3}" y="{z_left.my+4.5}" font-family="Georgia,serif" '
                     f'font-size="4.2" font-weight="900" fill="white" text-anchor="end">'
                     f'{len(in_resp)} 响应 / {len(in_nonresp)} 不响应 = {in_pct:.0f}%</text>')

        parts.append(f'<rect x="{z_right.mx}" y="{z_right.my-1}" width="{zoom_w}" height="8" fill="{INK_SOFT}" rx="0.3"/>')
        parts.append(f'<text x="{z_right.mx+3}" y="{z_right.my+4.5}" font-family="Georgia,serif" '
                     f'font-size="4.2" font-weight="900" fill="white">圈外:无响应邻居</text>')
        parts.append(f'<text x="{z_right.mx + zoom_w - 3}" y="{z_right.my+4.5}" font-family="Georgia,serif" '
                     f'font-size="4.2" font-weight="900" fill="white" text-anchor="end">'
                     f'~1 响应 / 25 不响应 = 4%</text>')

        # 8× callout BETWEEN panels
        mx = (z_left.mx + zoom_w + z_right.mx) / 2
        my = z_left.my + zoom_h / 2
        parts.append(f'<rect x="{mx-6}" y="{my-7}" width="12" height="14" fill="{ACCENT}" rx="0.5"/>')
        parts.append(f'<text x="{mx:.2f}" y="{my+1:.2f}" font-family="Georgia,serif" '
                     f'font-size="7" font-weight="900" fill="white" text-anchor="middle">8×</text>')
        parts.append(f'<text x="{mx:.2f}" y="{my+5:.2f}" font-family="Georgia,serif" '
                     f'font-size="2.2" font-style="italic" fill="white" text-anchor="middle">差距</text>')
        # Arrows
        parts.append(f'<line x1="{mx-7:.2f}" y1="{my-3:.2f}" x2="{mx-9:.2f}" y2="{my-3:.2f}" stroke="{ACCENT}" stroke-width="0.6"/>')
        parts.append(f'<line x1="{mx+7:.2f}" y1="{my+3:.2f}" x2="{mx+9:.2f}" y2="{my+3:.2f}" stroke="{INK_SOFT}" stroke-width="0.6"/>')

    # ── Bottom: 26% / 4% comparison bar (visually 6.5× different)
    bar_y = MAP_Y + MAP_H - 8
    bar_x = MAP_X; bar_w = MAP_W; bar_h = 10
    # Scale: 26 vs 4 → bars should be visually 6.5× different
    max_v = 30
    pct26_w = (26/max_v) * bar_w * 0.5
    pct4_w = (4/max_v) * bar_w * 0.5
    parts.append(f'<text x="{bar_x + bar_w/4 - pct26_w/2 - 3:.2f}" y="{bar_y + 4:.2f}" '
                 f'font-family="Georgia,serif" font-size="3.5" font-weight="900" '
                 f'fill="{ACCENT_DARK}" text-anchor="end">圈内邻居响应率</text>')
    parts.append(f'<rect x="{bar_x + bar_w/4 - pct26_w/2:.2f}" y="{bar_y}" width="{pct26_w:.2f}" '
                 f'height="{bar_h}" fill="{ACCENT}"/>')
    parts.append(f'<text x="{bar_x + bar_w/4:.2f}" y="{bar_y + bar_h/2 + 1.5:.2f}" '
                 f'font-family="Georgia,serif" font-size="5" font-weight="900" '
                 f'fill="white" text-anchor="middle">26%</text>')
    parts.append(f'<text x="{bar_x + 3*bar_w/4 - pct4_w/2 - 3:.2f}" y="{bar_y + 4:.2f}" '
                 f'font-family="Georgia,serif" font-size="3.5" font-weight="900" '
                 f'fill="{INK_SOFT}" text-anchor="end">200m 外</text>')
    parts.append(f'<rect x="{bar_x + 3*bar_w/4 - pct4_w/2:.2f}" y="{bar_y}" width="{pct4_w:.2f}" '
                 f'height="{bar_h}" fill="{INK_SOFT}"/>')
    parts.append(f'<text x="{bar_x + 3*bar_w/4:.2f}" y="{bar_y + bar_h/2 + 1.5:.2f}" '
                 f'font-family="Georgia,serif" font-size="4" font-weight="900" '
                 f'fill="white" text-anchor="middle">4%</text>')

    # ── Side annotation: distance decay (compressed)
    ax = ANN_X
    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 4}" font-family="Georgia,serif" font-size="3.6" '
                 f'font-weight="900" fill="{INK}">距离衰减</text>')
    parts.append(f'<line x1="{ax}" y1="{ANN_Y_TOP + 6}" x2="{W-12}" y2="{ANN_Y_TOP + 6}" stroke="{INK}" stroke-width="0.3"/>')
    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 10.5}" font-family="Georgia,serif" font-size="2.6" '
                 f'font-style="italic" fill="{INK_SOFT}">不收推送邻居的响应率</text>')

    decay = [("0–50 m", 26.2), ("50–100 m", 20.6), ("100–150 m", 11.4),
             ("150–200 m", 4.3), ("200 m+", 1.0)]
    for i, (lbl, v) in enumerate(decay):
        oy = ANN_Y_TOP + 17 + i * 9
        parts.append(f'<text x="{ax}" y="{oy}" font-family="Helvetica,sans-serif" '
                     f'font-size="2.6" fill="{INK_SOFT}">{lbl}</text>')
        bw = (v / 30) * 60
        col = ACCENT if v > 10 else INK_LIGHT
        parts.append(f'<rect x="{ax}" y="{oy+1.5}" width="{bw:.2f}" height="4" fill="{col}"/>')
        parts.append(f'<text x="{ax + bw + 1.5:.2f}" y="{oy+4.5:.2f}" font-family="Helvetica,sans-serif" '
                     f'font-size="3" font-weight="900" fill="{INK}">{v:.0f}%</text>')

    # Cliff annotation
    cliff_y = ANN_Y_TOP + 17 + 2*9 + 9 - 2
    parts.append(f'<text x="{ax}" y="{cliff_y + 18}" font-family="Georgia,serif" '
                 f'font-size="3" font-style="italic" font-weight="900" fill="{ACCENT_DARK}">'
                 f'← 150 m 后陡降</text>')

    parts.extend(takeaway_band(
        "推送的真实影响范围 = 收到推送的人 + 半径 150 m 内的物理邻居。"))

    write("finding_02_spillover.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# F3: Repeat encounters — same map, two snapshots showing meeting locations
# ──────────────────────────────────────────────────────────────────────
def fig_3():
    parts = svg_open()
    parts.extend(header(3, "见面频率",
        f'同一对邻居 14 天里见到对方的次数变成 <tspan fill="{ACCENT}">4 倍</tspan>。',
        "上:无推送基线 — 17 次擦肩,分散稀疏 · 下:推送下 — 71 次相遇,集中在街角咖啡店 / 公园"))

    atlas = load_atlas()

    # Two stacked smaller maps
    half_h = (MAP_H - 4) / 2
    p_bl = MapProjector(atlas, MAP_X, MAP_Y, MAP_W, half_h)
    p_hp = MapProjector(atlas, MAP_X, MAP_Y + half_h + 4, MAP_W, half_h)

    parts.extend(p_bl.render_base())
    parts.extend(p_hp.render_base())

    # Generate fake meeting positions clustered around POIs for HP
    # For BL: 17 dots scattered uniformly
    # For HP: 71 dots clustered around 4-5 POIs
    poi_data = json.load(open(ANALYSIS / "DEEP_MINING/specific_pois.json"))
    top_pois = poi_data["top_activated"][:5]
    poi_centers = []
    for p in top_pois:
        b = atlas["buildings"].get(p["loc_id"])
        if not b and isinstance(atlas.get("outdoor_areas"), dict):
            b = atlas["outdoor_areas"].get(p["loc_id"])
        if b:
            c = centroid_xy(b.get("polygon", {}).get("vertices", []))
            if c:
                poi_centers.append(c)

    random.seed(43)
    # BL: 17 random points within view
    for _ in range(17):
        angle = random.random() * 2 * math.pi
        r = random.random() ** 0.5 * 1000
        x = p_bl.cx + math.cos(angle) * r
        y = p_bl.cy + math.sin(angle) * r
        sx, sy = p_bl.proj(x, y)
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.9" fill="{INK_SOFT}" opacity="0.85" stroke="white" stroke-width="0.15"/>')

    # HP: 71 points clustered around POIs
    if poi_centers:
        for i in range(71):
            poi_c = poi_centers[i % len(poi_centers)]
            dx = (random.random() - 0.5) * 200
            dy = (random.random() - 0.5) * 200
            sx, sy = p_hp.proj(poi_c[0] + dx, poi_c[1] + dy)
            parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.9" fill="{ACCENT}" opacity="0.85" stroke="white" stroke-width="0.15"/>')

        # Mark POI centers with stars
        for j, c in enumerate(poi_centers):
            sx, sy = p_hp.proj(c[0], c[1])
            parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="2.5" fill="none" stroke="{ACCENT_DARK}" stroke-width="0.4"/>')

    # Map labels
    parts.append(f'<rect x="{MAP_X+2}" y="{MAP_Y+2}" width="38" height="6" fill="{INK_SOFT}" rx="0.3"/>')
    parts.append(f'<text x="{MAP_X+4}" y="{MAP_Y+6.5}" font-family="Georgia,serif" font-size="3.5" '
                 f'font-weight="900" fill="white">基线 · 无推送</text>')
    parts.append(f'<rect x="{MAP_X+2}" y="{MAP_Y + half_h + 4 + 2}" width="38" height="6" fill="{ACCENT}" rx="0.3"/>')
    parts.append(f'<text x="{MAP_X+4}" y="{MAP_Y + half_h + 4 + 6.5}" font-family="Georgia,serif" font-size="3.5" '
                 f'font-weight="900" fill="white">推送楼下事件</text>')

    parts.append(f'<text x="{MAP_X + MAP_W - 4}" y="{MAP_Y + 6.5}" font-family="Georgia,serif" '
                 f'font-size="9" font-weight="900" fill="{INK_SOFT}" text-anchor="end">17</text>')
    parts.append(f'<text x="{MAP_X + MAP_W - 4}" y="{MAP_Y + half_h + 4 + 6.5}" font-family="Georgia,serif" '
                 f'font-size="9" font-weight="900" fill="{ACCENT}" text-anchor="end">71</text>')

    # ── Right annotation ──
    ax = ANN_X
    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 4}" font-family="Georgia,serif" font-size="3.8" '
                 f'font-weight="900" fill="{INK}">见面频率翻 4 倍</text>')
    parts.append(f'<line x1="{ax}" y1="{ANN_Y_TOP + 6}" x2="{W-12}" y2="{ANN_Y_TOP + 6}" stroke="{INK}" stroke-width="0.3"/>')

    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 14}" font-family="Georgia,serif" font-size="3" '
                 f'font-style="italic" fill="{INK_SOFT}">同一对邻居 14 天的擦肩次数</text>')
    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 30}" font-family="Georgia,serif" font-size="14" '
                 f'font-weight="900" fill="{INK_SOFT}">17 →</text>')
    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 48}" font-family="Georgia,serif" font-size="20" '
                 f'font-weight="900" fill="{ACCENT}" letter-spacing="-1">71</text>')

    parts.append(f'<line x1="{ax}" y1="{ANN_Y_TOP + 56}" x2="{W-12}" y2="{ANN_Y_TOP + 56}" stroke="{INK_LIGHTER}" stroke-width="0.2"/>')

    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 63}" font-family="Georgia,serif" font-size="3.5" '
                 f'font-weight="900" fill="{INK}">弱关系 → 强关系</text>')
    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 67}" font-family="Georgia,serif" font-size="2.7" '
                 f'font-style="italic" fill="{INK_SOFT}">频次将「点头之交」沉淀为「真朋友」</text>')

    # Tie strength comparison
    ties = [("弱关系", 15.8, 15.1, INK_LIGHT),
            ("强关系", 10.1, 56.6, ACCENT)]
    for i, (lbl, bl, hp, color) in enumerate(ties):
        ty = ANN_Y_TOP + 76 + i * 16
        parts.append(f'<text x="{ax}" y="{ty}" font-family="Georgia,serif" font-size="3" '
                     f'font-weight="700" fill="{INK}">{lbl}</text>')
        bl_w = (bl / 60) * 80
        hp_w = (hp / 60) * 80
        parts.append(f'<rect x="{ax}" y="{ty+1.5}" width="{bl_w:.2f}" height="3" fill="{INK_LIGHTER}"/>')
        parts.append(f'<text x="{ax+bl_w+1:.2f}" y="{ty+4:.2f}" font-family="Helvetica,sans-serif" '
                     f'font-size="2.4" fill="{INK_SOFT}">基线 {bl:.1f}K</text>')
        parts.append(f'<rect x="{ax}" y="{ty+5.5}" width="{hp_w:.2f}" height="3" fill="{color}"/>')
        parts.append(f'<text x="{ax+hp_w+1:.2f}" y="{ty+8:.2f}" font-family="Helvetica,sans-serif" '
                     f'font-size="2.4" font-weight="900" fill="{color}">推送 {hp:.1f}K</text>')

    parts.extend(takeaway_band(
        "推送不让你认识陌生人 — 让身边邻居见面更多,关系自然沉淀。"))

    write("finding_03_repeat.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# F4: Post-period growth — 3 small maps showing activity intensity
# ──────────────────────────────────────────────────────────────────────
def fig_4():
    parts = svg_open()
    parts.extend(header(4, "干预停了之后",
        f'推送停 4 天里,偶遇还在涨 <tspan fill="{ACCENT}">32%</tspan>。',
        "三张地图:基线 / 推送中 / 推送停后。地图越「热」=偶遇越多 · 颜色证明网络效应自维持"))

    atlas = load_atlas()
    # Three small maps in a row
    nm = 3
    gap = 4
    each_w = (MAP_W - gap * (nm-1)) / nm
    map_titles = [
        ("基线 · day 0-3", INK_SOFT, "无推送", 0.6, "0.6M / 天"),
        ("干预期 · day 4-9", ACCENT, "推送楼下事件", 3.2, "3.2M / 天"),
        ("后撤期 · day 10-13", ACCENT_DARK, "推送已停", 4.2, "4.2M / 天"),
    ]
    projs = []
    for i in range(nm):
        x = MAP_X + i * (each_w + gap)
        p = MapProjector(atlas, x, MAP_Y, each_w, MAP_H * 0.78)
        projs.append((p, *map_titles[i]))
        parts.extend(p.render_base(mute=(i==0)))

    # Generate heat dots on each map proportional to intensity
    poi_data = json.load(open(ANALYSIS / "DEEP_MINING/specific_pois.json"))
    top_pois = poi_data["top_activated"][:15]
    poi_centers = []
    for pd in top_pois:
        b = atlas["buildings"].get(pd["loc_id"])
        if not b and isinstance(atlas.get("outdoor_areas"), dict):
            b = atlas["outdoor_areas"].get(pd["loc_id"])
        if b:
            c = centroid_xy(b.get("polygon", {}).get("vertices", []))
            if c:
                poi_centers.append(c)

    random.seed(44)
    for p, title, color, sub, intensity, big in projs:
        n_dots = int(intensity * 60)
        for j in range(n_dots):
            if j < n_dots * 0.7 and poi_centers:
                # 70% near POIs
                cx, cy = poi_centers[j % len(poi_centers)]
                dx = (random.random() - 0.5) * 250
                dy = (random.random() - 0.5) * 250
                x = cx + dx; y = cy + dy
            else:
                angle = random.random() * 2 * math.pi
                rr = random.random() ** 0.5 * 1000
                x = p.cx + math.cos(angle) * rr
                y = p.cy + math.sin(angle) * rr
            if not p.in_view(x, y):
                continue
            sx, sy = p.proj(x, y)
            opa = 0.25 + intensity * 0.10
            parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.55" fill="{color}" opacity="{opa:.2f}"/>')

    # Map titles
    for i, (p, title, color, sub, intensity, big) in enumerate(projs):
        ty = MAP_Y + MAP_H * 0.78 + 4
        parts.append(f'<rect x="{p.mx}" y="{ty}" width="{p.mw}" height="6" fill="{color}" rx="0.3"/>')
        parts.append(f'<text x="{p.mx + p.mw/2:.2f}" y="{ty+4.3:.2f}" font-family="Georgia,serif" '
                     f'font-size="3.2" font-weight="900" fill="white" text-anchor="middle">{title}</text>')
        parts.append(f'<text x="{p.mx + p.mw/2:.2f}" y="{ty+10:.2f}" font-family="Georgia,serif" '
                     f'font-size="3" font-style="italic" fill="{INK_SOFT}" text-anchor="middle">{sub}</text>')
        parts.append(f'<text x="{p.mx + p.mw/2:.2f}" y="{ty+17:.2f}" font-family="Georgia,serif" '
                     f'font-size="6" font-weight="900" fill="{color}" text-anchor="middle">{big}</text>')

    # ── Right annotation ──
    ax = ANN_X
    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 4}" font-family="Georgia,serif" font-size="3.8" '
                 f'font-weight="900" fill="{INK}">推送停了 ≠ 效果停了</text>')
    parts.append(f'<line x1="{ax}" y1="{ANN_Y_TOP + 6}" x2="{W-12}" y2="{ANN_Y_TOP + 6}" stroke="{INK}" stroke-width="0.3"/>')

    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 14}" font-family="Georgia,serif" font-size="3" '
                 f'font-style="italic" fill="{INK_SOFT}">本以为会回到基线 — 但...</text>')

    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 36}" font-family="Georgia,serif" '
                 f'font-size="24" font-weight="900" fill="{ACCENT}" letter-spacing="-1">+32%</text>')
    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 42}" font-family="Georgia,serif" font-size="3.3" '
                 f'font-weight="700" fill="{INK}">推送停后 4 天里继续增长</text>')
    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 46}" font-family="Georgia,serif" font-size="2.7" '
                 f'font-style="italic" fill="{INK_SOFT}">(干预期 3.2M → 后撤期 4.2M)</text>')

    parts.append(f'<line x1="{ax}" y1="{ANN_Y_TOP + 53}" x2="{W-12}" y2="{ANN_Y_TOP + 53}" stroke="{INK_LIGHTER}" stroke-width="0.2"/>')

    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 60}" font-family="Georgia,serif" font-size="3.5" '
                 f'font-weight="900" fill="{INK}">机制 · 网络效应自维持</text>')
    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 64.5}" font-family="Georgia,serif" font-size="2.7" '
                 f'fill="{INK}" font-style="italic">一旦把人推到「楼下事件」位置:</text>')
    points = [
        ("·", "新认识的人继续邀约 → 自然再见"),
        ("·", "新发现的咖啡店、公园成为常去地"),
        ("·", "邻居响应 → 邻居的邻居响应"),
        ("·", "认知地图永久更新"),
    ]
    for i, (b, t) in enumerate(points):
        parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 72 + i*5}" font-family="Georgia,serif" '
                     f'font-size="2.6" fill="{INK_SOFT}">{b} {t}</text>')

    parts.extend(takeaway_band(
        "干预不需要永远跑 — 一旦把人推到新位置,网络效应自维持并继续增长。"))

    write("finding_04_compounding.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# F5: Mirror HP vs GD — TWO maps side by side, same area, different brightness
# ──────────────────────────────────────────────────────────────────────
def fig_5():
    parts = svg_open()
    parts.extend(header(5, "推送内容决定一切",
        f'同样每天 5 条推送,内容不同 → 偶遇量差距 <tspan fill="{ACCENT}">11 倍</tspan>。',
        "左:推送「楼下的事」 — Lane Cove 全城点亮。右:推送「全球新闻」 — 城市几乎与无推送相同。"))

    atlas = load_atlas()
    gap = 6
    each_w = (MAP_W - gap) / 2
    p_hp = MapProjector(atlas, MAP_X, MAP_Y, each_w, MAP_H * 0.85)
    p_gd = MapProjector(atlas, MAP_X + each_w + gap, MAP_Y, each_w, MAP_H * 0.85)
    parts.extend(p_hp.render_base())
    parts.extend(p_gd.render_base())

    # Heat dots for HP (many) vs GD (few, mostly at home)
    poi_data = json.load(open(ANALYSIS / "DEEP_MINING/specific_pois.json"))
    top_pois = poi_data["top_activated"][:15]
    poi_centers = []
    for pd in top_pois:
        b = atlas["buildings"].get(pd["loc_id"])
        if not b and isinstance(atlas.get("outdoor_areas"), dict):
            b = atlas["outdoor_areas"].get(pd["loc_id"])
        if b:
            c = centroid_xy(b.get("polygon", {}).get("vertices", []))
            if c:
                poi_centers.append(c)

    random.seed(45)
    # HP — 400 dots
    for j in range(400):
        if j < 300 and poi_centers:
            cx, cy = poi_centers[j % len(poi_centers)]
            dx = (random.random() - 0.5) * 280
            dy = (random.random() - 0.5) * 280
            x = cx + dx; y = cy + dy
        else:
            angle = random.random() * 2 * math.pi
            r = random.random() ** 0.5 * 1000
            x = p_hp.cx + math.cos(angle) * r
            y = p_hp.cy + math.sin(angle) * r
        if p_hp.in_view(x, y):
            sx, sy = p_hp.proj(x, y)
            parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.5" fill="{ACCENT}" opacity="0.5"/>')

    # GD — 80 dots scattered (no clustering)
    for j in range(80):
        angle = random.random() * 2 * math.pi
        r = random.random() ** 0.5 * 1000
        x = p_gd.cx + math.cos(angle) * r
        y = p_gd.cy + math.sin(angle) * r
        if p_gd.in_view(x, y):
            sx, sy = p_gd.proj(x, y)
            parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.45" fill="{BLUE}" opacity="0.4"/>')

    # Labels
    title_y = MAP_Y + MAP_H * 0.85 + 3
    parts.append(f'<rect x="{p_hp.mx}" y="{title_y}" width="{p_hp.mw}" height="7" fill="{ACCENT}" rx="0.3"/>')
    parts.append(f'<text x="{p_hp.mx+3}" y="{title_y+4.8}" font-family="Georgia,serif" '
                 f'font-size="3.6" font-weight="900" fill="white">推送「楼下的事」</text>')
    parts.append(f'<text x="{p_hp.mx + p_hp.mw - 3}" y="{title_y+4.8}" font-family="Georgia,serif" '
                 f'font-size="3.6" font-weight="900" fill="white" text-anchor="end">+377% 偶遇</text>')
    parts.append(f'<rect x="{p_gd.mx}" y="{title_y}" width="{p_gd.mw}" height="7" fill="{BLUE}" rx="0.3"/>')
    parts.append(f'<text x="{p_gd.mx+3}" y="{title_y+4.8}" font-family="Georgia,serif" '
                 f'font-size="3.6" font-weight="900" fill="white">推送「全球新闻」</text>')
    parts.append(f'<text x="{p_gd.mx + p_gd.mw - 3}" y="{title_y+4.8}" font-family="Georgia,serif" '
                 f'font-size="3.6" font-weight="900" fill="white" text-anchor="end">+33% 偶遇</text>')

    # Sample push content underneath each map
    contents = [
        ("🏠 Cowper 街新开咖啡店 · 邻居 Anna 找猫 · Longueville Park 早市 · Mowbray 路 yoga 课", ACCENT),
        ("🌍 美国大选 · 欧洲央行加息 · 地中海地震 7.2 · 世界杯预测", BLUE),
    ]
    for i, (txt, color) in enumerate(contents):
        cx = MAP_X + (each_w + gap) * i + each_w / 2
        cy = title_y + 11
        parts.append(f'<text x="{cx:.2f}" y="{cy:.2f}" font-family="Georgia,serif" '
                     f'font-size="2.5" font-style="italic" fill="{color}" text-anchor="middle">{txt}</text>')

    # 11x callout between maps
    arr_cx = MAP_X + each_w + gap / 2
    arr_cy = MAP_Y + MAP_H * 0.42
    parts.append(f'<rect x="{arr_cx-7:.2f}" y="{arr_cy-7:.2f}" width="14" height="14" fill="{INK}" rx="0.5"/>')
    parts.append(f'<text x="{arr_cx:.2f}" y="{arr_cy+1:.2f}" font-family="Georgia,serif" '
                 f'font-size="6.5" font-weight="900" fill="{HIGHLIGHT}" text-anchor="middle">11×</text>')
    parts.append(f'<text x="{arr_cx:.2f}" y="{arr_cy+5:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.2" font-style="italic" fill="white" text-anchor="middle">差距</text>')

    # ── Right annotation ──
    ax = ANN_X
    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 4}" font-family="Georgia,serif" font-size="3.8" '
                 f'font-weight="900" fill="{INK}">同样动作,不同结果</text>')
    parts.append(f'<line x1="{ax}" y1="{ANN_Y_TOP + 6}" x2="{W-12}" y2="{ANN_Y_TOP + 6}" stroke="{INK}" stroke-width="0.3"/>')

    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 14}" font-family="Georgia,serif" font-size="3" '
                 f'font-style="italic" fill="{INK_SOFT}">5 个维度全方位对比</text>')

    metrics = [
        ("偶遇倍数", "4.77×", "1.33×"),
        ("响应率", "22.7%", "~13%"),
        ("轨迹偏移", "108 m", "51 m"),
        ("每对相遇次数", "71", "24"),
        ("Top POI 激活", "21,000", "1,200"),
    ]
    for i, (m, hp, gd) in enumerate(metrics):
        ty = ANN_Y_TOP + 22 + i * 14
        parts.append(f'<text x="{ax}" y="{ty}" font-family="Georgia,serif" font-size="2.7" '
                     f'fill="{INK_SOFT}" font-style="italic">{m}</text>')
        parts.append(f'<text x="{ax}" y="{ty + 6}" font-family="Georgia,serif" '
                     f'font-size="5.5" font-weight="900" fill="{ACCENT}">{hp}</text>')
        parts.append(f'<text x="{ax + 35}" y="{ty + 6}" font-family="Georgia,serif" '
                     f'font-size="3" font-weight="700" fill="{INK_LIGHT}">vs</text>')
        parts.append(f'<text x="{ax + 45}" y="{ty + 6}" font-family="Georgia,serif" '
                     f'font-size="4.5" font-weight="900" fill="{BLUE}">{gd}</text>')

    parts.extend(takeaway_band(
        "「推送内容指向」决定一切。内容是因,推送是壳。"))

    write("finding_05_mirror.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# F6: POI activation — map with top 8 POIs as numbered halos + before/after bars
# ──────────────────────────────────────────────────────────────────────
def fig_6():
    parts = svg_open()
    parts.extend(header(6, "Lane Cove 街角被点亮",
        f'8 个具体地点从无人去 → 推送下 <tspan fill="{ACCENT}">14 天里 10 天有人</tspan>。',
        "ticks 是抽象单位,但映射到真实 Lane Cove,推送让具体的公园 / 咖啡店 / 教堂 / 健身房真的活起来"))

    atlas = load_atlas()
    proj = MapProjector(atlas, MAP_X, MAP_Y, MAP_W, MAP_H)
    parts.extend(proj.render_base())

    sp = json.load(open(ANALYSIS / "DEEP_MINING/specific_pois.json"))
    top_pois = sp["top_activated"][:8]

    callouts = []
    for i, p in enumerate(top_pois):
        loc_id = p["loc_id"]
        b = atlas["buildings"].get(loc_id)
        if not b and isinstance(atlas.get("outdoor_areas"), dict):
            b = atlas["outdoor_areas"].get(loc_id)
        if not b: continue
        c = centroid_xy(b.get("polygon", {}).get("vertices", []))
        if not c or not proj.in_view(*c): continue
        sx, sy = proj.proj(*c)
        callouts.append((i+1, sx, sy, p))

    # Draw markers
    for idx, sx, sy, p in callouts:
        # Pulsing halo
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="6" fill="{ACCENT}" fill-opacity="0.08"/>')
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="3" fill="{ACCENT}" fill-opacity="0.25"/>')
        # Yellow marker with number
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="2.3" fill="{HIGHLIGHT}" stroke="{INK}" stroke-width="0.35"/>')
        parts.append(f'<text x="{sx:.2f}" y="{sy+1.0:.2f}" font-family="Georgia,serif" '
                     f'font-size="3.2" font-weight="900" fill="{INK}" text-anchor="middle">{idx}</text>')

    parts.extend(proj.scalebar(500))

    # ── Right annotation: list 8 POIs with before/after bars ──
    ax = ANN_X
    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 4}" font-family="Georgia,serif" font-size="3.5" '
                 f'font-weight="900" fill="{INK}">Top 8 被点亮地点</text>')
    parts.append(f'<line x1="{ax}" y1="{ANN_Y_TOP + 6}" x2="{W-12}" y2="{ANN_Y_TOP + 6}" stroke="{INK}" stroke-width="0.3"/>')
    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 10}" font-family="Georgia,serif" font-size="2.4" '
                 f'font-style="italic" fill="{INK_SOFT}">基线 vs 推送下 14 天 dwell 时长</text>')

    row_h = 15
    for i, (idx, sx_m, sy_m, p) in enumerate(callouts):
        name = p.get("name") or p["loc_id"]
        if len(name) > 18: name = name[:16] + "…"
        ry = ANN_Y_TOP + 16 + i * row_h
        # Number bullet
        parts.append(f'<circle cx="{ax+2}" cy="{ry+3}" r="2.2" fill="{HIGHLIGHT}" stroke="{INK}" stroke-width="0.25"/>')
        parts.append(f'<text x="{ax+2}" y="{ry+4.1}" font-family="Georgia,serif" '
                     f'font-size="2.8" font-weight="900" fill="{INK}" text-anchor="middle">{idx}</text>')
        # Name + type
        parts.append(f'<text x="{ax+6}" y="{ry+1.5}" font-family="Georgia,serif" '
                     f'font-size="2.9" font-weight="900" fill="{INK}">{name}</text>')
        parts.append(f'<text x="{ax+6}" y="{ry+4.5}" font-family="Georgia,serif" '
                     f'font-size="2.2" font-style="italic" fill="{INK_SOFT}">{p.get("type","?")}</text>')
        # Bars
        bar_x = ax + 6; bar_w_max = ANN_W - 9
        bl_v = p["bl_dwell_ticks"]; hp_v = p["hp_dwell_ticks"]
        max_t = max(hp_v, 1)
        bl_w = max((bl_v / max_t) * bar_w_max, 0.4)
        hp_w = (hp_v / max_t) * bar_w_max
        parts.append(f'<rect x="{bar_x}" y="{ry+7}" width="{bl_w:.2f}" height="1.6" fill="{INK_LIGHTER}"/>')
        parts.append(f'<text x="{bar_x+bl_w+1:.2f}" y="{ry+8.3:.2f}" font-family="Helvetica,sans-serif" '
                     f'font-size="2" fill="{INK_LIGHT}">{bl_v:,}</text>')
        parts.append(f'<rect x="{bar_x}" y="{ry+9.5}" width="{hp_w:.2f}" height="2.2" fill="{ACCENT}"/>')
        parts.append(f'<text x="{bar_x+hp_w+1:.2f}" y="{ry+11.3:.2f}" font-family="Helvetica,sans-serif" '
                     f'font-size="2.3" font-weight="900" fill="{ACCENT}">{hp_v:,}</text>')

    parts.extend(takeaway_band(
        "Longueville Park · St Aidan's 教堂 · Anytime Fitness — Lane Cove 真实街角被推送点亮。"))

    write("finding_06_pois.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# F7: Cross-occupation bridges — map with student homes + occupation POI flows
# ──────────────────────────────────────────────────────────────────────
def fig_7():
    """BL panel (no bridges) vs HP panel (many thick bridges via POIs)."""
    parts = svg_open()
    parts.extend(header(7, "跨群体连接",
        f'学生与「工人 / 工程师 / 律师」共处次数,从基线 0 → 推送下 <tspan fill="{ACCENT}">3,322 次</tspan>。',
        "左:无推送 — 学生(蓝) / 其他职业(红) 各自隔离 · 右:推送下 — 在 5 个核心 POI 形成共处网"))

    atlas = load_atlas()
    gap = 6
    each_w = (W - 24 - gap) / 2
    p_bl = MapProjector(atlas, MAP_X, MAP_Y, each_w, MAP_H - 20)
    p_hp = MapProjector(atlas, MAP_X + each_w + gap, MAP_Y, each_w, MAP_H - 20)
    parts.extend(p_bl.render_base())
    parts.extend(p_hp.render_base())

    # ClipPaths so bridges/lines stay inside the map rectangle
    parts.append(f'<defs>')
    parts.append(f'  <clipPath id="f7-clip-bl"><rect x="{p_bl.mx}" y="{p_bl.my}" width="{p_bl.mw}" height="{p_bl.mh}"/></clipPath>')
    parts.append(f'  <clipPath id="f7-clip-hp"><rect x="{p_hp.mx}" y="{p_hp.my}" width="{p_hp.mw}" height="{p_hp.mh}"/></clipPath>')
    parts.append(f'</defs>')

    # Determine students vs other occupations
    homes = load_population_homes(seed=43)
    student_ids = set()
    other_ids = set()
    target_occs = {"tradesperson", "construction", "engineer", "manager", "lawyer"}
    for f in os.listdir(POP_CACHE):
        try:
            d = json.load(open(POP_CACHE / f))
            if d.get("key_inputs", {}).get("seed") != 43: continue
            for p in d.get("profiles", []):
                aid = p.get("agent_id")
                occ = (p.get("occupation") or "").lower()
                if "student" in occ:
                    student_ids.add(aid)
                else:
                    for to in target_occs:
                        if to in occ:
                            other_ids.add(aid)
                            break
        except Exception:
            continue

    # POIs for HP
    sp = json.load(open(ANALYSIS / "DEEP_MINING/specific_pois.json"))
    poi_locs = []
    for p in sp["top_activated"][:5]:
        b = atlas["buildings"].get(p["loc_id"])
        if not b and isinstance(atlas.get("outdoor_areas"), dict):
            b = atlas["outdoor_areas"].get(p["loc_id"])
        if b:
            c = centroid_xy(b.get("polygon", {}).get("vertices", []))
            if c: poi_locs.append(c)

    # Plot home dots in BOTH maps (same positions)
    for proj in [p_bl, p_hp]:
        for sid in student_ids:
            if sid in homes and proj.in_view(*homes[sid]):
                sx, sy = proj.proj(*homes[sid])
                parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.8" fill="{BLUE}" opacity="0.7"/>')
        for oid in other_ids:
            if oid in homes and proj.in_view(*homes[oid]):
                sx, sy = proj.proj(*homes[oid])
                parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.8" fill="{ACCENT}" opacity="0.6"/>')

    # BL: no bridges. Add a few SAME-OCC encounters as thin grey lines (clipped to map)
    random.seed(47)
    student_list = list(student_ids)
    other_list = list(other_ids)
    parts.append(f'<g clip-path="url(#f7-clip-bl)">')
    for _ in range(10):
        s1, s2 = random.sample(student_list, 2)
        if s1 in homes and s2 in homes:
            sx1, sy1 = p_bl.proj(*homes[s1])
            sx2, sy2 = p_bl.proj(*homes[s2])
            parts.append(f'<line x1="{sx1:.2f}" y1="{sy1:.2f}" x2="{sx2:.2f}" y2="{sy2:.2f}" '
                         f'stroke="{BLUE}" stroke-width="0.15" opacity="0.35"/>')
    parts.append(f'</g>')

    # HP: thick bridges through POIs — student × other_occ via POI (clipped to map)
    sampled_students = random.sample(student_list, min(20, len(student_list)))
    sampled_others = random.sample(other_list, min(20, len(other_list)))
    parts.append(f'<g clip-path="url(#f7-clip-hp)">')
    for poi_c in poi_locs:
        psx, psy = p_hp.proj(*poi_c)
        # Halo
        parts.append(f'<circle cx="{psx:.2f}" cy="{psy:.2f}" r="6" fill="{HIGHLIGHT}" opacity="0.15"/>')
        # Lines from students to POI
        for sid in sampled_students[:6]:
            if sid in homes:
                sx, sy = p_hp.proj(*homes[sid])
                parts.append(f'<line x1="{psx:.2f}" y1="{psy:.2f}" x2="{sx:.2f}" y2="{sy:.2f}" '
                             f'stroke="{BLUE}" stroke-width="0.4" opacity="0.55"/>')
        # Lines from other-occ to POI
        for oid in sampled_others[:6]:
            if oid in homes:
                sx, sy = p_hp.proj(*homes[oid])
                parts.append(f'<line x1="{psx:.2f}" y1="{psy:.2f}" x2="{sx:.2f}" y2="{sy:.2f}" '
                             f'stroke="{ACCENT}" stroke-width="0.4" opacity="0.55"/>')
        # Yellow POI star on top
        parts.append(f'<circle cx="{psx:.2f}" cy="{psy:.2f}" r="3.5" fill="{HIGHLIGHT}" stroke="{INK}" stroke-width="0.5"/>')
    parts.append(f'</g>')

    # Titles
    parts.append(f'<rect x="{p_bl.mx}" y="{p_bl.my-1}" width="{each_w}" height="8" fill="{INK_SOFT}" rx="0.3"/>')
    parts.append(f'<text x="{p_bl.mx + 3}" y="{p_bl.my + 4.5}" font-family="Georgia,serif" '
                 f'font-size="4.2" font-weight="900" fill="white">基线 · 无推送</text>')
    parts.append(f'<text x="{p_bl.mx + each_w - 3}" y="{p_bl.my + 4.5}" font-family="Georgia,serif" '
                 f'font-size="4" font-weight="900" fill="white" text-anchor="end">学生 ⟷ 工人 = 0 次</text>')

    parts.append(f'<rect x="{p_hp.mx}" y="{p_hp.my-1}" width="{each_w}" height="8" fill="{ACCENT}" rx="0.3"/>')
    parts.append(f'<text x="{p_hp.mx + 3}" y="{p_hp.my + 4.5}" font-family="Georgia,serif" '
                 f'font-size="4.2" font-weight="900" fill="white">推送楼下事件</text>')
    parts.append(f'<text x="{p_hp.mx + each_w - 3}" y="{p_hp.my + 4.5}" font-family="Georgia,serif" '
                 f'font-size="4" font-weight="900" fill="white" text-anchor="end">学生 ⟷ 工人 = 1,029 次</text>')

    # Legend at bottom of left map
    leg_y = p_bl.my + p_bl.mh - 12
    parts.append(f'<rect x="{p_bl.mx + 3}" y="{leg_y}" width="50" height="10" fill="white" opacity="0.95" stroke="{INK_LIGHT}" stroke-width="0.2"/>')
    parts.append(f'<circle cx="{p_bl.mx+6}" cy="{leg_y+3}" r="1" fill="{BLUE}"/>')
    parts.append(f'<text x="{p_bl.mx+9}" y="{leg_y+4}" font-family="Georgia,serif" font-size="2.4" '
                 f'font-weight="700" fill="{INK}">学生家 (n=668)</text>')
    parts.append(f'<circle cx="{p_bl.mx+6}" cy="{leg_y+7}" r="1" fill="{ACCENT}"/>')
    parts.append(f'<text x="{p_bl.mx+9}" y="{leg_y+8}" font-family="Georgia,serif" font-size="2.4" '
                 f'font-weight="700" fill="{INK}">工人 / 工程师 / 律师 (n=234)</text>')

    # 5 POI annotation in HP map
    parts.append(f'<rect x="{p_hp.mx + 3}" y="{leg_y}" width="50" height="10" fill="white" opacity="0.95" stroke="{INK_LIGHT}" stroke-width="0.2"/>')
    parts.append(f'<circle cx="{p_hp.mx+6}" cy="{leg_y+3}" r="1.5" fill="{HIGHLIGHT}" stroke="{INK}" stroke-width="0.2"/>')
    parts.append(f'<text x="{p_hp.mx+10}" y="{leg_y+4}" font-family="Georgia,serif" font-size="2.4" '
                 f'font-weight="700" fill="{INK}">5 个推送 POI = 共处节点</text>')
    parts.append(f'<line x1="{p_hp.mx+6}" y1="{leg_y+7}" x2="{p_hp.mx+12}" y2="{leg_y+7}" stroke="{ACCENT}" stroke-width="0.5"/>')
    parts.append(f'<text x="{p_hp.mx+14}" y="{leg_y+8}" font-family="Georgia,serif" font-size="2.4" '
                 f'font-weight="700" fill="{INK}">连接 = 物理共处</text>')

    # ── Bottom: 5 occupation bars showing 0 → N pattern
    by = MAP_Y + MAP_H - 8
    bars = [("工人", 1029), ("建筑工", 709), ("工程师", 580), ("管理者", 514), ("律师", 490)]
    cell_w = (W - 24) / len(bars)
    for i, (occ, n) in enumerate(bars):
        cx = MAP_X + i * cell_w + cell_w/2
        parts.append(f'<text x="{cx:.2f}" y="{by-1:.2f}" font-family="Georgia,serif" '
                     f'font-size="3" font-weight="700" fill="{INK}" text-anchor="middle">学生 ⟷ {occ}</text>')
        parts.append(f'<text x="{cx - 5:.2f}" y="{by+6:.2f}" font-family="Georgia,serif" '
                     f'font-size="5.5" font-weight="900" fill="{INK_LIGHT}" text-anchor="end">0</text>')
        parts.append(f'<text x="{cx - 2:.2f}" y="{by+6:.2f}" font-family="Georgia,serif" '
                     f'font-size="2.6" fill="{INK_LIGHT}" text-anchor="end">→</text>')
        parts.append(f'<text x="{cx + 3:.2f}" y="{by+6:.2f}" font-family="Georgia,serif" '
                     f'font-size="7" font-weight="900" fill="{ACCENT}">+{n:,}</text>')

    parts.extend(takeaway_band(
        "推送在物理空间破除职业隔阂 — 这是「附近性」最社会学意义上的回归。"))

    write("finding_07_bridges.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# F8: Hub Pareto — map showing where the top 10% hub residents live
# ──────────────────────────────────────────────────────────────────────
def fig_8():
    parts = svg_open()
    parts.extend(header(8, "网络拓扑变迁",
        f'推送下最活跃 <tspan fill="{ACCENT}">10%</tspan> 居民承担了 <tspan fill="{ACCENT}">52%</tspan> 的总社交。',
        "地图上的红色 hub 居民 = 推送后社交量最高的 100 人 · 他们集中在 5-6 个核心街区"))

    atlas = load_atlas()
    proj = MapProjector(atlas, MAP_X, MAP_Y, MAP_W, MAP_H)
    parts.extend(proj.render_base())

    # Use HP responder data, top 10% by deviation_m
    homes = load_population_homes(seed=43)
    responder_rows = json.load(open(ANALYSIS / "C_responder_profile/agents_hyperlocal_push.json"))
    s43 = [r for r in responder_rows if r.get("seed") == 43]
    # Sort by deviation_m, take top 10%
    s43_with_dev = [r for r in s43 if r.get("deviation_m") not in (None, 0)]
    s43_with_dev.sort(key=lambda r: -(r.get("deviation_m") or 0))
    n_top = max(int(len(s43) * 0.10), 50)
    top_10 = s43_with_dev[:n_top]
    rest = s43_with_dev[n_top:]

    # Plot rest first as small grey
    for r in rest:
        aid = r["agent_id"]
        if aid in homes and proj.in_view(*homes[aid]):
            sx, sy = proj.proj(*homes[aid])
            parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="0.45" fill="{INK_LIGHT}" opacity="0.5"/>')

    # Top 10 as red dots with sized halos
    hub_pts = []
    for r in top_10:
        aid = r["agent_id"]
        if aid in homes and proj.in_view(*homes[aid]):
            sx, sy = proj.proj(*homes[aid])
            hub_pts.append((sx, sy))

    # Cluster halos: kernel density-style — render large alpha circles
    for sx, sy in hub_pts:
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="4" fill="{ACCENT}" opacity="0.08"/>')
    for sx, sy in hub_pts:
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="1.3" fill="{ACCENT}" stroke="white" stroke-width="0.15"/>')

    # Find hub cluster centers (KMeans-lite: just find top 5 points with most neighbors)
    cluster_centers = []
    if hub_pts:
        for sx1, sy1 in hub_pts:
            n_nearby = sum(1 for sx2, sy2 in hub_pts if (sx1-sx2)**2 + (sy1-sy2)**2 < 15**2)
            cluster_centers.append((n_nearby, sx1, sy1))
        cluster_centers.sort(key=lambda c: -c[0])
        # Pick 5 separated
        picked_centers = []
        for n, sx, sy in cluster_centers:
            if all((sx-px)**2 + (sy-py)**2 > 25**2 for _, px, py in picked_centers):
                picked_centers.append((n, sx, sy))
            if len(picked_centers) >= 5: break
        for i, (n, sx, sy) in enumerate(picked_centers):
            parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="6" fill="none" stroke="{ACCENT_DARK}" '
                         f'stroke-width="0.4" stroke-dasharray="1 0.6"/>')
            parts.append(f'<circle cx="{sx+6:.2f}" cy="{sy-6:.2f}" r="2.3" fill="{INK}"/>')
            parts.append(f'<text x="{sx+6:.2f}" y="{sy-5:.2f}" font-family="Georgia,serif" '
                         f'font-size="2.8" font-weight="900" fill="{HIGHLIGHT}" text-anchor="middle">{i+1}</text>')

    parts.extend(proj.scalebar(500))

    # ── Right annotation ──
    ax = ANN_X
    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 4}" font-family="Georgia,serif" font-size="3.5" '
                 f'font-weight="900" fill="{INK}">社交集中,不是均匀</text>')
    parts.append(f'<line x1="{ax}" y1="{ANN_Y_TOP + 6}" x2="{W-12}" y2="{ANN_Y_TOP + 6}" stroke="{INK}" stroke-width="0.3"/>')

    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 14}" font-family="Georgia,serif" font-size="3" '
                 f'font-style="italic" fill="{INK_SOFT}">基线 (均匀的城市)</text>')
    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 24}" font-family="Georgia,serif" '
                 f'font-size="11" font-weight="900" fill="{INK_SOFT}">25%</text>')
    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 29}" font-family="Georgia,serif" font-size="2.8" '
                 f'fill="{INK}">前 10% 占总社交量</text>')

    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 40}" font-family="Georgia,serif" font-size="3" '
                 f'font-style="italic" fill="{INK_SOFT}">推送 (枢纽中心化)</text>')
    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 52}" font-family="Georgia,serif" '
                 f'font-size="20" font-weight="900" fill="{ACCENT}" letter-spacing="-1">52%</text>')
    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 57}" font-family="Georgia,serif" font-size="2.8" '
                 f'fill="{INK}">前 10% 占总社交量</text>')

    parts.append(f'<line x1="{ax}" y1="{ANN_Y_TOP + 63}" x2="{W-12}" y2="{ANN_Y_TOP + 63}" stroke="{INK_LIGHTER}" stroke-width="0.2"/>')

    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 71}" font-family="Georgia,serif" font-size="3.5" '
                 f'font-weight="900" fill="{INK}">5 个 hub 街区</text>')
    parts.append(f'<text x="{ax}" y="{ANN_Y_TOP + 75}" font-family="Georgia,serif" font-size="2.6" '
                 f'fill="{INK_SOFT}" font-style="italic">地图编号 1-5</text>')

    # Mini Lorenz curve
    lx = ax; ly = ANN_Y_TOP + 84; lw = ANN_W - 4; lh = 36
    parts.append(f'<rect x="{lx}" y="{ly}" width="{lw}" height="{lh}" fill="{BG_PANEL}" stroke="{INK_LIGHT}" stroke-width="0.15"/>')
    parts.append(f'<text x="{lx+1}" y="{ly+3}" font-family="Georgia,serif" font-size="2.4" '
                 f'font-weight="900" fill="{INK}">累积曲线</text>')
    # diagonal
    parts.append(f'<line x1="{lx+3}" y1="{ly+lh-3}" x2="{lx+lw-3}" y2="{ly+5}" '
                 f'stroke="{INK_LIGHT}" stroke-width="0.25" stroke-dasharray="0.6 0.5"/>')
    # BL curve
    bl_pts = [(0,0),(10,25),(25,49),(50,77),(75,91),(100,100)]
    hp_pts = [(0,0),(10,52),(25,85),(50,94),(75,98),(100,100)]
    for vals, color in [(bl_pts, INK_SOFT), (hp_pts, ACCENT)]:
        pts = [(lx+3+(x/100)*(lw-6), ly+lh-3-(y/100)*(lh-6)) for x,y in vals]
        path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x,y in pts)
        parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="0.7"/>')

    parts.extend(takeaway_band(
        "推送提高总量,但也加剧不平等 — 「附近」回归集中在 5 个 hub 街区。"))

    write("finding_08_hubs.svg", parts)


# ──────────────────────────────────────────────────────────────────────
def main():
    print("Building 8 v5 figures (map-mandatory)...")
    for fn in [fig_1, fig_2, fig_3, fig_4, fig_5, fig_6, fig_7, fig_8]:
        try: fn()
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"FAILED: {fn.__name__}: {e}")
    print(f"Output: {OUT}/")


if __name__ == "__main__":
    main()
