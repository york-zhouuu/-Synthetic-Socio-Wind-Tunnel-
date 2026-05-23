"""Build long-form SVG posters for case study agents.

Each poster: 320 mm wide × ~1200 mm tall. Suitable for printing as A0 vertical or
displaying as scroll. Contains:
  - Cover band with profile + key stats
  - Intro paragraph
  - 14-day strip (one row per day, narrative + map)
  - Discovery + takeaway bands

Output: docs/case_studies/{mary,mike}_diary_poster.svg
"""
import json
import os
from pathlib import Path

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
ATLAS_PATH = REPO / "data/lanecove_atlas.json"
DIARY_DIR = REPO / "data/analysis/case_studies"
OUT_DIR = REPO / "docs/case_studies"

# Import narrative from the HTML script
import sys; sys.path.insert(0, str(REPO / "tools/case_studies"))
from build_diary_html import NARRATIVE  # reuse

W = 320  # mm wide
DAY_H = 65  # mm per day row
COVER_H = 110
INTRO_H = 50
DISCOVERY_H = 60
TAKEAWAY_H = 50

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
ORANGE_NEW = "#D14B12"


def centroid_xy(verts):
    if not verts: return None
    xs = [v["x"] for v in verts] if isinstance(verts[0], dict) else [v[0] for v in verts]
    ys = [v["y"] for v in verts] if isinstance(verts[0], dict) else [v[1] for v in verts]
    return sum(xs)/len(xs), sum(ys)/len(ys)


print("Loading atlas...")
atlas = json.load(open(ATLAS_PATH))
LOC2META = {}
for bid, b in atlas["buildings"].items():
    verts = b.get("polygon", {}).get("vertices", [])
    if verts:
        c = centroid_xy(verts)
        if c:
            LOC2META[bid] = {"name": b.get("name") or "", "type": b.get("building_type") or "",
                             "x": c[0], "y": c[1], "polygon": verts}
outdoor = atlas.get("outdoor_areas", {})
outdoor_iter = outdoor.items() if isinstance(outdoor, dict) else [(o["id"], o) for o in outdoor]
for oid, o in outdoor_iter:
    verts = o.get("polygon", {}).get("vertices", [])
    if verts:
        c = centroid_xy(verts)
        if c:
            LOC2META[oid] = {"name": o.get("name") or "", "type": o.get("area_type") or "",
                             "x": c[0], "y": c[1], "polygon": verts}


def render_mini_map(stays_bl, stays_hp, mx, my, mw, mh):
    """Render mini map for a single day row. Returns list of SVG strings."""
    parts = []
    pts = [(s["x"], s["y"]) for s in stays_bl + stays_hp if s.get("x") is not None]
    if not pts:
        parts.append(f'<rect x="{mx}" y="{my}" width="{mw}" height="{mh}" fill="{MAP_LAND}" stroke="{INK_LIGHT}" stroke-width="0.2"/>')
        parts.append(f'<text x="{mx + mw/2}" y="{my + mh/2}" text-anchor="middle" '
                     f'font-family="Georgia,serif" font-size="3" font-style="italic" fill="{INK_LIGHT}">'
                     f'静默 · 没有移动</text>')
        return parts

    min_x = min(p[0] for p in pts) - 80; max_x = max(p[0] for p in pts) + 80
    min_y = min(p[1] for p in pts) - 80; max_y = max(p[1] for p in pts) + 80
    span_x = max_x - min_x; span_y = max_y - min_y
    target_aspect = mw / mh
    actual_aspect = span_x / span_y if span_y > 0 else 1
    if actual_aspect > target_aspect:
        new_y = span_x / target_aspect
        pad = (new_y - span_y) / 2
        min_y -= pad; max_y += pad
    else:
        new_x = span_y * target_aspect
        pad = (new_x - span_x) / 2
        min_x -= pad; max_x += pad
    span_x = max_x - min_x
    scale = mw / span_x

    def proj(x, y):
        return mx + (x - min_x) * scale, my + (max_y - y) * scale

    def in_view(x, y):
        return min_x <= x <= max_x and min_y <= y <= max_y

    # Background
    parts.append(f'<rect x="{mx}" y="{my}" width="{mw}" height="{mh}" fill="{MAP_LAND}" stroke="{INK}" stroke-width="0.3"/>')
    clip_id = f'clip-{mx}-{my}'
    parts.append(f'<defs><clipPath id="{clip_id}"><rect x="{mx}" y="{my}" width="{mw}" height="{mh}"/></clipPath></defs>')
    parts.append(f'<g clip-path="url(#{clip_id})">')

    # Streets + parks + buildings
    for loc_id, m in LOC2META.items():
        if not in_view(m["x"], m["y"]): continue
        verts = m["polygon"]
        if len(verts) < 3: continue
        pts2 = [proj(v["x"], v["y"]) for v in verts]
        path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in pts2) + " Z"
        t = m.get("type", "")
        if t in ("park", "playground", "garden"):
            parts.append(f'<path d="{path}" fill="{MAP_PARK}" stroke="#9DBC8A" stroke-width="0.15"/>')
        elif t == "street":
            parts.append(f'<path d="{path}" fill="{MAP_STREET}" stroke="none"/>')
        else:
            parts.append(f'<path d="{path}" fill="{MAP_BLDG}" stroke="{MAP_BLDG_STROKE}" stroke-width="0.1"/>')

    # BL stays (grey)
    for s in stays_bl:
        sx, sy = proj(s["x"], s["y"])
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="1.3" fill="{INK_SOFT}" opacity="0.6" stroke="white" stroke-width="0.3"/>')

    # HP stays (orange star with name)
    for s in stays_hp:
        sx, sy = proj(s["x"], s["y"])
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="2.8" fill="{ORANGE_NEW}" stroke="white" stroke-width="0.4"/>')
        nm = s.get("name") or s["loc"]
        if nm and not nm.startswith("road_"):
            parts.append(f'<text x="{sx + 4:.2f}" y="{sy+1:.2f}" font-family="Georgia,serif" '
                         f'font-size="2.5" font-weight="900" fill="{ACCENT_DARK}">{nm[:20]}</text>')

    parts.append("</g>")
    return parts


def build_poster(label, diary):
    narr = NARRATIVE[label]
    profile = diary.get("profile", {})

    # Filter days to ones with narrative (4-13)
    valid_days = [d for d in diary["days"] if d["day"] in narr["days"]]

    H_total = COVER_H + INTRO_H + len(valid_days) * DAY_H + DISCOVERY_H + TAKEAWAY_H + 20

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H_total}mm" '
        f'viewBox="0 0 {W} {H_total}" preserveAspectRatio="xMidYMid meet">',
        f'<rect width="100%" height="100%" fill="{BG_PAPER}"/>',
    ]

    y = 0

    # ─── COVER ─────────────────────────────────
    parts.append(f'<rect x="0" y="{y}" width="{W}" height="{COVER_H}" fill="{INK}"/>')
    parts.append(f'<text x="20" y="{y+12}" font-family="Georgia,serif" font-size="3.5" '
                 f'font-style="italic" fill="{ACCENT_DARK}" letter-spacing="0.5">'
                 f'CASE STUDY · 1,000 居民中的一位 · 真实 positions.json 14 天完整路径</text>')
    parts.append(f'<text x="20" y="{y+38}" font-family="Georgia,serif" font-size="22" '
                 f'font-weight="900" fill="white">{narr["cover_title"]}</text>')
    parts.append(f'<text x="20" y="{y+52}" font-family="Georgia,serif" font-size="6" '
                 f'font-style="italic" fill="{INK_LIGHTER}">{narr["cover_subtitle"]}</text>')
    # 4 stat boxes
    total_dist_hp = sum(d["hp_distance_m"] for d in diary["days"])
    total_dist_bl = sum(d["bl_distance_m"] for d in diary["days"])
    discovery_count = len(set(n["name"] for d in diary["days"] for n in d.get("new_locations_today", []) if n.get("name")))
    stats = [
        (str(profile.get("age", "?")), "岁"),
        (f"{int(total_dist_hp/1000)} km", "14 天总距离"),
        (f"+{discovery_count}", "新发现地点"),
        (f"+{int((total_dist_hp - total_dist_bl)/1000)} km", "比无推送多走"),
    ]
    for i, (num, lbl) in enumerate(stats):
        sx = 20 + i * 72
        parts.append(f'<line x1="{sx}" y1="{y+70}" x2="{sx}" y2="{y+98}" stroke="{HIGHLIGHT}" stroke-width="1"/>')
        parts.append(f'<text x="{sx+4}" y="{y+82}" font-family="Georgia,serif" font-size="11" '
                     f'font-weight="900" fill="{HIGHLIGHT}">{num}</text>')
        parts.append(f'<text x="{sx+4}" y="{y+90}" font-family="Georgia,serif" font-size="3.2" '
                     f'font-style="italic" fill="{INK_LIGHTER}">{lbl}</text>')
    y += COVER_H

    # ─── INTRO ─────────────────────────────────
    parts.append(f'<rect x="0" y="{y}" width="{W}" height="{INTRO_H}" fill="{BG_PANEL}"/>')
    parts.append(f'<text x="20" y="{y+12}" font-family="Georgia,serif" font-size="7" '
                 f'font-weight="900" fill="{INK}">她是谁?</text>')
    # Wrap intro (strip HTML tags)
    intro_text = narr["intro"].replace("<br><br>", " ").replace("<br>", " ")
    intro_text = "".join(c if c.isprintable() else "" for c in intro_text)
    # Word wrap
    lines = []
    line = ""
    MAX_CHARS = 78
    for ch in intro_text:
        line += ch
        if len(line) >= MAX_CHARS and ch in "。,、 ":
            lines.append(line.strip())
            line = ""
    if line.strip(): lines.append(line.strip())
    for i, ln in enumerate(lines[:5]):
        parts.append(f'<text x="20" y="{y+20+i*5.5}" font-family="Georgia,serif" font-size="3.6" '
                     f'fill="{INK}">{ln}</text>')
    y += INTRO_H

    # ─── 14-DAY STRIP ─────────────────────────────────
    for day_data in valid_days:
        day = day_data["day"]
        day_title, day_text = narr["days"][day]
        # Phase color
        if day <= 3: phase_col = INK_SOFT
        elif day == 4: phase_col = HIGHLIGHT
        elif 5 <= day <= 9: phase_col = ORANGE_NEW
        else: phase_col = ACCENT

        # Background panel
        parts.append(f'<rect x="0" y="{y}" width="{W}" height="{DAY_H}" fill="white"/>')
        parts.append(f'<rect x="0" y="{y}" width="6" height="{DAY_H}" fill="{phase_col}"/>')

        # Day label + title
        parts.append(f'<text x="12" y="{y+9}" font-family="Georgia,serif" font-size="3" '
                     f'font-style="italic" fill="{INK_SOFT}" letter-spacing="1">DAY {day}</text>')
        parts.append(f'<text x="12" y="{y+18}" font-family="Georgia,serif" font-size="7" '
                     f'font-weight="900" fill="{INK}">{day_title}</text>')

        # Distance stat (top-right)
        parts.append(f'<text x="{W-12}" y="{y+10}" font-family="Helvetica,sans-serif" font-size="2.8" '
                     f'fill="{INK_SOFT}" text-anchor="end">推送下 <tspan font-weight="900" fill="{ACCENT_DARK}">'
                     f'{day_data["hp_distance_m"]:.0f} m</tspan></text>')
        parts.append(f'<text x="{W-12}" y="{y+14}" font-family="Helvetica,sans-serif" font-size="2.8" '
                     f'fill="{INK_SOFT}" text-anchor="end">vs 无推送 {day_data["bl_distance_m"]:.0f} m</text>')

        # Narrative text (wrap)
        text_x = 12
        text_max_chars = 50
        ll = []
        line = ""
        for ch in day_text:
            line += ch
            if len(line) >= text_max_chars and ch in "。,、 ":
                ll.append(line.strip()); line = ""
        if line.strip(): ll.append(line.strip())
        for i, ln in enumerate(ll[:5]):
            parts.append(f'<text x="{text_x}" y="{y+25+i*4.5}" font-family="Georgia,serif" '
                         f'font-size="3.2" fill="{INK}">{ln}</text>')

        # Stays list (compact)
        stays_y = y + 47
        # Filter to named POI stays only (skip road segments + raw building IDs)
        named_stays = [s for s in day_data["hp_stays"]
                       if s.get("name") and not s["name"].startswith("road_")
                       and not s.get("loc", "").startswith("building_")]
        if named_stays:
            parts.append(f'<text x="{text_x}" y="{stays_y}" font-family="Georgia,serif" '
                         f'font-size="2.5" font-weight="900" fill="{ACCENT_DARK}">推送下停留:</text>')
            for j, s in enumerate(named_stays[:3]):
                nm = s["name"][:18]
                txt = f'{nm} · 停留约 {s["duration_min"]} 分钟'
                parts.append(f'<text x="{text_x+22}" y="{stays_y + j*3.5}" font-family="Helvetica,sans-serif" '
                             f'font-size="2.4" fill="{INK_SOFT}">{txt}</text>')

        # Mini map (right side)
        mx = W - 95; my = y + 5; mw = 83; mh = DAY_H - 10
        parts.extend(render_mini_map(day_data["bl_stays"], day_data["hp_stays"], mx, my, mw, mh))

        # Day divider
        parts.append(f'<line x1="0" y1="{y+DAY_H}" x2="{W}" y2="{y+DAY_H}" '
                     f'stroke="{INK_LIGHTER}" stroke-width="0.2"/>')

        y += DAY_H

    # ─── DISCOVERY ─────────────────────────────────
    parts.append(f'<rect x="0" y="{y}" width="{W}" height="{DISCOVERY_H}" fill="#FBD8DC"/>')
    parts.append(f'<rect x="0" y="{y}" width="6" height="{DISCOVERY_H}" fill="{ACCENT_DARK}"/>')
    parts.append(f'<text x="14" y="{y+12}" font-family="Georgia,serif" font-size="3.5" '
                 f'font-style="italic" fill="{ACCENT_DARK}" letter-spacing="0.5">她发现的地方</text>')
    parts.append(f'<text x="14" y="{y+22}" font-family="Georgia,serif" font-size="8" '
                 f'font-weight="900" fill="{INK}">{narr["discovery_title"]}</text>')
    desc_text = narr["discovery_desc"]
    lines = []
    line = ""
    for ch in desc_text:
        line += ch
        if len(line) >= 75 and ch in "。,、 ":
            lines.append(line.strip()); line = ""
    if line.strip(): lines.append(line.strip())
    for i, ln in enumerate(lines[:4]):
        parts.append(f'<text x="14" y="{y+33+i*5}" font-family="Georgia,serif" font-size="3.2" '
                     f'fill="{INK}">{ln}</text>')
    y += DISCOVERY_H

    # ─── TAKEAWAY ─────────────────────────────────
    parts.append(f'<rect x="0" y="{y}" width="{W}" height="{TAKEAWAY_H}" fill="{INK}"/>')
    parts.append(f'<text x="14" y="{y+12}" font-family="Georgia,serif" font-size="3.5" '
                 f'font-style="italic" fill="{HIGHLIGHT}" letter-spacing="0.5">这意味着什么?</text>')
    tk_text = narr["takeaway"].replace("<br><br>", " ").replace("<br>", " ").replace("<strong>", "").replace("</strong>", "")
    lines = []
    line = ""
    for ch in tk_text:
        line += ch
        if len(line) >= 75 and ch in "。,、 ":
            lines.append(line.strip()); line = ""
    if line.strip(): lines.append(line.strip())
    for i, ln in enumerate(lines[:5]):
        parts.append(f'<text x="14" y="{y+22+i*5}" font-family="Georgia,serif" font-size="3.4" '
                     f'font-style="italic" fill="white">{ln}</text>')
    y += TAKEAWAY_H

    # Footer
    parts.append(f'<text x="{W/2}" y="{y+12}" font-family="Georgia,serif" font-size="2.5" '
                 f'font-style="italic" fill="{INK_LIGHT}" text-anchor="middle">'
                 f'Synthetic Socio Wind Tunnel · 悉尼 Lane Cove 虚拟城市 · github.com/york-zhouuu</text>')

    parts.append("</svg>")
    return "".join(parts)


for label in ["mary", "mike"]:
    diary = json.load(open(DIARY_DIR / f"{label}_diary.json"))
    svg = build_poster(label, diary)
    out_path = OUT_DIR / f"{label}_diary_poster.svg"
    out_path.write_text(svg)
    print(f"Wrote {out_path} · {out_path.stat().st_size / 1e3:.0f} KB")
