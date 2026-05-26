"""Finding 2 redesign — drop the map (it adds nothing here).

The finding is about a CAUSAL/MECHANISTIC claim:
  "If a neighbor within 150m responded to the push,
   you (who didn't receive any push) are 8× more likely to also respond."

This is NOT a geographic claim. It's a SOCIAL CAUSATION claim.
A map of Lane Cove doesn't help prove or visualize this.

What DOES help:
  - Two side-by-side scenes contrasting WITH-vs-WITHOUT a responding neighbor
  - Person icons showing who responds (pink walking) vs who doesn't (grey home)
  - Plain Chinese — no HP/GD/PF/protag jargon
  - Big "8倍" comparison number
  - Distance decay mini-chart at bottom showing why 150m is the cutoff
"""
from __future__ import annotations
from pathlib import Path
import math

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
OUT = REPO / "docs/mockups"
OUT.mkdir(parents=True, exist_ok=True)

# Palette
INK = "#1B1F2A"
INK_SOFT = "#5A5E6A"
INK_LIGHT = "#A8ACB5"
BG_PAPER = "#FFFFFF"
BG_SCENE = "#F8F5EE"
ACCENT = "#E03A4A"
ACCENT_SOFT = "#FBD8DC"
ACCENT_DARK = "#A0252F"
HIGHLIGHT = "#F0C419"
GREY = "#D8D9DC"
W, H = 320, 220


def person_walking(x, y, color, scale=1.0, halo=False):
    """A simple walking person silhouette."""
    s = scale
    parts = []
    if halo:
        parts.append(f'<circle cx="{x:.2f}" cy="{y-2*s:.2f}" r="{4.5*s:.2f}" '
                     f'fill="{HIGHLIGHT}" fill-opacity="0.45"/>')
    # Head
    parts.append(f'<circle cx="{x:.2f}" cy="{y - 3.5*s:.2f}" r="{0.9*s:.2f}" fill="{color}"/>')
    # Body (slight forward lean)
    parts.append(f'<line x1="{x:.2f}" y1="{y-2.6*s:.2f}" x2="{x+0.3*s:.2f}" y2="{y+0.2*s:.2f}" '
                 f'stroke="{color}" stroke-width="{0.65*s:.2f}" stroke-linecap="round"/>')
    # Arms — one swung back, one swung forward
    parts.append(f'<line x1="{x-1.2*s:.2f}" y1="{y-1.2*s:.2f}" x2="{x+0.2*s:.2f}" y2="{y-2.2*s:.2f}" '
                 f'stroke="{color}" stroke-width="{0.4*s:.2f}" stroke-linecap="round"/>')
    parts.append(f'<line x1="{x+0.2*s:.2f}" y1="{y-2.2*s:.2f}" x2="{x+1.4*s:.2f}" y2="{y-1.0*s:.2f}" '
                 f'stroke="{color}" stroke-width="{0.4*s:.2f}" stroke-linecap="round"/>')
    # Legs — striding
    parts.append(f'<line x1="{x+0.3*s:.2f}" y1="{y+0.2*s:.2f}" x2="{x-1.2*s:.2f}" y2="{y+2.4*s:.2f}" '
                 f'stroke="{color}" stroke-width="{0.55*s:.2f}" stroke-linecap="round"/>')
    parts.append(f'<line x1="{x+0.3*s:.2f}" y1="{y+0.2*s:.2f}" x2="{x+1.7*s:.2f}" y2="{y+2.4*s:.2f}" '
                 f'stroke="{color}" stroke-width="{0.55*s:.2f}" stroke-linecap="round"/>')
    return parts


def person_home(x, y, color, scale=1.0):
    """A small house glyph — represents 'stayed home'."""
    s = scale
    parts = []
    # roof (triangle)
    parts.append(f'<path d="M {x-2*s:.2f} {y-0.5*s:.2f} L {x:.2f} {y-2.5*s:.2f} L {x+2*s:.2f} {y-0.5*s:.2f} Z" '
                 f'fill="{color}" stroke="{INK}" stroke-width="0.1"/>')
    # body (rect)
    parts.append(f'<rect x="{x-1.7*s:.2f}" y="{y-0.5*s:.2f}" width="{3.4*s:.2f}" height="{2.5*s:.2f}" '
                 f'fill="{color}" stroke="{INK}" stroke-width="0.1"/>')
    # door
    parts.append(f'<rect x="{x-0.4*s:.2f}" y="{y+0.7*s:.2f}" width="{0.8*s:.2f}" height="{1.3*s:.2f}" '
                 f'fill="{INK}" opacity="0.55"/>')
    return parts


def build():
    out = []
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" '
               f'viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">')
    out.append(f'<rect width="100%" height="100%" fill="{BG_PAPER}"/>')

    # ==== Header (plain language, no jargon) ====
    out.append(f'<text x="12" y="14" font-family="Georgia,serif" font-size="3.3" '
               f'font-style="italic" fill="{ACCENT_DARK}" letter-spacing="0.3">'
               f'FINDING 02  ·  邻居效应  ·  Lane Cove 虚拟实验</text>')
    out.append(f'<line x1="12" y1="17" x2="{W-12}" y2="17" stroke="{ACCENT_DARK}" stroke-width="0.3"/>')

    # Big plain headline
    out.append(f'<text x="12" y="32" font-family="Georgia,serif" font-size="13" '
               f'font-weight="900" fill="{INK}" letter-spacing="-0.5">'
               f'你的邻居响应了推送 → 你自己响应概率高 <tspan fill="{ACCENT}">8 倍</tspan></text>')
    # Plain language sub
    out.append(f'<text x="12" y="42" font-family="Georgia,serif" font-size="4.5" '
               f'font-style="italic" fill="{INK_SOFT}">'
               f'实验里有 500 人能收到「楼下的事」推送,另外 500 人永远不收。第二组里谁会响应?只有家附近 150 米内有「响应邻居」的人。</text>')

    # ==== Two scene panels ====
    panel_y = 55
    panel_h = 105
    panel_w = (W - 24 - 14) / 2  # 7mm gap between panels
    panel_lx = 12
    panel_rx = panel_lx + panel_w + 14

    # --- Scene A: WITH responding neighbor ---
    out.append(f'<rect x="{panel_lx}" y="{panel_y}" width="{panel_w}" height="{panel_h}" '
               f'fill="{BG_SCENE}" stroke="{INK_LIGHT}" stroke-width="0.25"/>')
    # Header bar
    out.append(f'<rect x="{panel_lx}" y="{panel_y}" width="{panel_w}" height="9" fill="{ACCENT}"/>')
    out.append(f'<text x="{panel_lx+4}" y="{panel_y+6}" font-family="Georgia,serif" '
               f'font-size="4" font-weight="900" fill="white">场景 A</text>')
    out.append(f'<text x="{panel_lx+panel_w-4}" y="{panel_y+6}" font-family="Georgia,serif" '
               f'font-size="3.5" font-weight="700" fill="white" text-anchor="end" font-style="italic">'
               f'你身边 150m 内,有响应邻居</text>')

    # Scene center coords
    sa_cx = panel_lx + panel_w / 2
    sa_cy = panel_y + 9 + (panel_h - 9) / 2 - 2

    # 150m circle (just visual indicator)
    out.append(f'<circle cx="{sa_cx:.2f}" cy="{sa_cy:.2f}" r="{32:.2f}" '
               f'fill="{ACCENT}" fill-opacity="0.04" stroke="{ACCENT}" stroke-width="0.35" '
               f'stroke-dasharray="1.2 0.8"/>')
    out.append(f'<text x="{sa_cx+33:.2f}" y="{sa_cy-32:.2f}" font-family="Georgia,serif" '
               f'font-size="2.6" font-style="italic" font-weight="700" fill="{ACCENT_DARK}">150 米半径</text>')

    # The "you" figure in center — non-protag who responded (pink walking)
    out.extend(person_walking(sa_cx, sa_cy + 8, ACCENT, scale=1.4, halo=False))
    out.append(f'<text x="{sa_cx:.2f}" y="{sa_cy+15:.2f}" font-family="Georgia,serif" '
               f'font-size="3" font-weight="900" fill="{INK}" text-anchor="middle">你</text>')
    out.append(f'<text x="{sa_cx:.2f}" y="{sa_cy+18.5:.2f}" font-family="Georgia,serif" '
               f'font-size="2.5" fill="{INK_SOFT}" text-anchor="middle" font-style="italic">(不收推送,但走出门了)</text>')

    # Responding neighbor — with phone halo
    n_x, n_y = sa_cx - 22, sa_cy - 12
    out.extend(person_walking(n_x, n_y, ACCENT, scale=1.2, halo=True))
    # Phone icon next to them
    out.append(f'<rect x="{n_x+3:.2f}" y="{n_y-6:.2f}" width="3" height="5" fill="white" stroke="{INK}" stroke-width="0.2" rx="0.3"/>')
    out.append(f'<rect x="{n_x+3.5:.2f}" y="{n_y-5.5:.2f}" width="2" height="3.5" fill="{ACCENT}"/>')
    out.append(f'<text x="{n_x:.2f}" y="{n_y-8:.2f}" font-family="Georgia,serif" '
               f'font-size="2.5" font-weight="700" fill="{ACCENT_DARK}" text-anchor="middle">邻居 ·</text>')
    out.append(f'<text x="{n_x:.2f}" y="{n_y-5:.2f}" font-family="Georgia,serif" '
               f'font-size="2.5" font-weight="700" fill="{ACCENT_DARK}" text-anchor="middle">收到推送 → 走出门</text>')

    # Other neighbors inside the circle — mix of pink walking and grey home
    inner_neighbors_A = [
        (sa_cx + 14, sa_cy - 16, "walk"),
        (sa_cx + 22, sa_cy + 6, "home"),
        (sa_cx - 14, sa_cy + 14, "walk"),
        (sa_cx + 4, sa_cy - 22, "home"),
        (sa_cx + 17, sa_cy + 17, "walk"),
        (sa_cx - 8, sa_cy - 5, "home"),
        (sa_cx - 22, sa_cy + 10, "home"),
        (sa_cx + 10, sa_cy + 16, "home"),
    ]
    walk_count_A = sum(1 for _, _, t in inner_neighbors_A if t == "walk")
    total_A = len(inner_neighbors_A)  # 8 (excluding center "you" and the responder)
    for px, py, kind in inner_neighbors_A:
        if kind == "walk":
            out.extend(person_walking(px, py, ACCENT, scale=0.85))
        else:
            out.extend(person_home(px, py, INK_LIGHT, scale=0.85))

    # Big stat for scene A — at bottom of panel
    stat_y = panel_y + panel_h - 22
    out.append(f'<text x="{sa_cx:.2f}" y="{stat_y:.2f}" font-family="Georgia,serif" '
               f'font-size="20" font-weight="900" fill="{ACCENT}" text-anchor="middle" letter-spacing="-1">26%</text>')
    out.append(f'<text x="{sa_cx:.2f}" y="{stat_y+6:.2f}" font-family="Georgia,serif" '
               f'font-size="3.2" font-weight="700" fill="{INK}" text-anchor="middle">'
               f'圈内「不收推送」的居民,响应率</text>')
    out.append(f'<text x="{sa_cx:.2f}" y="{stat_y+10:.2f}" font-family="Georgia,serif" '
               f'font-size="2.5" fill="{INK_SOFT}" font-style="italic" text-anchor="middle">'
               f'(实测 n=1,170 across 3 seeds)</text>')

    # --- Scene B: WITHOUT responding neighbor ---
    out.append(f'<rect x="{panel_rx}" y="{panel_y}" width="{panel_w}" height="{panel_h}" '
               f'fill="{BG_SCENE}" stroke="{INK_LIGHT}" stroke-width="0.25"/>')
    out.append(f'<rect x="{panel_rx}" y="{panel_y}" width="{panel_w}" height="9" fill="{INK_SOFT}"/>')
    out.append(f'<text x="{panel_rx+4}" y="{panel_y+6}" font-family="Georgia,serif" '
               f'font-size="4" font-weight="900" fill="white">场景 B</text>')
    out.append(f'<text x="{panel_rx+panel_w-4}" y="{panel_y+6}" font-family="Georgia,serif" '
               f'font-size="3.5" font-weight="700" fill="white" text-anchor="end" font-style="italic">'
               f'同样情况,但邻居没响应</text>')

    sb_cx = panel_rx + panel_w / 2
    sb_cy = panel_y + 9 + (panel_h - 9) / 2 - 2

    out.append(f'<circle cx="{sb_cx:.2f}" cy="{sb_cy:.2f}" r="{32:.2f}" '
               f'fill="{INK_LIGHT}" fill-opacity="0.06" stroke="{INK_SOFT}" stroke-width="0.35" '
               f'stroke-dasharray="1.2 0.8"/>')
    out.append(f'<text x="{sb_cx+33:.2f}" y="{sb_cy-32:.2f}" font-family="Georgia,serif" '
               f'font-size="2.6" font-style="italic" font-weight="700" fill="{INK_SOFT}">150 米半径</text>')

    # "You" in scene B — stays home (grey home icon)
    out.extend(person_home(sb_cx, sb_cy + 7, INK_LIGHT, scale=1.5))
    out.append(f'<text x="{sb_cx:.2f}" y="{sb_cy+15:.2f}" font-family="Georgia,serif" '
               f'font-size="3" font-weight="900" fill="{INK}" text-anchor="middle">你</text>')
    out.append(f'<text x="{sb_cx:.2f}" y="{sb_cy+18.5:.2f}" font-family="Georgia,serif" '
               f'font-size="2.5" fill="{INK_SOFT}" text-anchor="middle" font-style="italic">(不收推送 + 没走出门)</text>')

    # Neighbor with phone (got push) but didn't walk out
    n_x, n_y = sb_cx - 22, sb_cy - 12
    out.extend(person_home(n_x, n_y, INK_LIGHT, scale=1.2))
    out.append(f'<rect x="{n_x+3:.2f}" y="{n_y-3:.2f}" width="3" height="5" fill="white" stroke="{INK}" stroke-width="0.2" rx="0.3"/>')
    out.append(f'<rect x="{n_x+3.5:.2f}" y="{n_y-2.5:.2f}" width="2" height="3.5" fill="{INK_LIGHT}"/>')
    out.append(f'<text x="{n_x:.2f}" y="{n_y-5:.2f}" font-family="Georgia,serif" '
               f'font-size="2.5" font-weight="700" fill="{INK_SOFT}" text-anchor="middle">邻居 ·</text>')
    out.append(f'<text x="{n_x:.2f}" y="{n_y-2:.2f}" font-family="Georgia,serif" '
               f'font-size="2.5" font-weight="700" fill="{INK_SOFT}" text-anchor="middle">收到推送但没响应</text>')

    # Inner neighbors B — almost all grey home icons
    inner_neighbors_B = [
        (sb_cx + 14, sb_cy - 16),
        (sb_cx + 22, sb_cy + 6),
        (sb_cx - 14, sb_cy + 14),
        (sb_cx + 4, sb_cy - 22),
        (sb_cx + 17, sb_cy + 17),
        (sb_cx - 8, sb_cy - 5),
        (sb_cx - 22, sb_cy + 10),
        (sb_cx + 10, sb_cy + 16),
    ]
    for px, py in inner_neighbors_B:
        out.extend(person_home(px, py, INK_LIGHT, scale=0.85))

    # Big stat for scene B
    out.append(f'<text x="{sb_cx:.2f}" y="{stat_y:.2f}" font-family="Georgia,serif" '
               f'font-size="20" font-weight="900" fill="{INK_SOFT}" text-anchor="middle" letter-spacing="-1">4%</text>')
    out.append(f'<text x="{sb_cx:.2f}" y="{stat_y+6:.2f}" font-family="Georgia,serif" '
               f'font-size="3.2" font-weight="700" fill="{INK}" text-anchor="middle">'
               f'同样的人,响应率</text>')
    out.append(f'<text x="{sb_cx:.2f}" y="{stat_y+10:.2f}" font-family="Georgia,serif" '
               f'font-size="2.5" fill="{INK_SOFT}" font-style="italic" text-anchor="middle">'
               f'(实测 n=207 across 3 seeds)</text>')

    # ==== Center: "8 倍" arrow between scenes ====
    arr_cx = (panel_lx + panel_w + panel_rx) / 2
    arr_cy = panel_y + 60
    out.append(f'<line x1="{arr_cx-5:.2f}" y1="{arr_cy:.2f}" x2="{arr_cx+5:.2f}" y2="{arr_cy:.2f}" '
               f'stroke="{INK}" stroke-width="0.6"/>')
    out.append(f'<polygon points="{arr_cx+5:.2f},{arr_cy:.2f} {arr_cx+3:.2f},{arr_cy-1.5:.2f} '
               f'{arr_cx+3:.2f},{arr_cy+1.5:.2f}" fill="{INK}"/>')
    out.append(f'<polygon points="{arr_cx-5:.2f},{arr_cy:.2f} {arr_cx-3:.2f},{arr_cy-1.5:.2f} '
               f'{arr_cx-3:.2f},{arr_cy+1.5:.2f}" fill="{INK}"/>')
    out.append(f'<rect x="{arr_cx-7:.2f}" y="{arr_cy+3:.2f}" width="14" height="9" fill="{ACCENT}" rx="0.5"/>')
    out.append(f'<text x="{arr_cx:.2f}" y="{arr_cy+9:.2f}" font-family="Georgia,serif" '
               f'font-size="7" font-weight="900" fill="white" text-anchor="middle">8×</text>')
    out.append(f'<text x="{arr_cx:.2f}" y="{arr_cy+15:.2f}" font-family="Georgia,serif" '
               f'font-size="2.6" font-style="italic" fill="{INK_SOFT}" text-anchor="middle">差距</text>')

    # ==== Bottom: distance decay row + caption ====
    by = 175
    out.append(f'<line x1="12" y1="{by-3}" x2="{W-12}" y2="{by-3}" stroke="{INK_LIGHT}" stroke-width="0.2"/>')
    out.append(f'<text x="12" y="{by+2}" font-family="Georgia,serif" font-size="4" '
               f'font-weight="900" fill="{INK}">为什么是 150 米?</text>')
    out.append(f'<text x="12" y="{by+6.5}" font-family="Georgia,serif" font-size="3" '
               f'font-style="italic" fill="{INK_SOFT}">效应随邻居距离呈陡降衰减,150-200 米之间是临界点</text>')

    # Mini bar chart on the right
    bar_x = 130; bar_y = by; bar_w = 175; bar_h = 25
    bars = [("0–50 米", 26.2, ACCENT), ("50–100 米", 20.6, ACCENT),
            ("100–150 米", 11.4, ACCENT_DARK), ("150–200 米", 4.3, INK_SOFT),
            ("200–300 米", 4.4, INK_SOFT), ("300+ 米", 1.0, INK_LIGHT)]
    each_w = bar_w / len(bars) - 1
    max_v = 30
    for j, (lbl, v, color) in enumerate(bars):
        h = (v / max_v) * bar_h
        x0 = bar_x + j * (bar_w / len(bars))
        y0 = bar_y + bar_h - h + 4
        out.append(f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{each_w:.2f}" height="{h:.2f}" fill="{color}"/>')
        out.append(f'<text x="{x0 + each_w/2:.2f}" y="{y0-0.4:.2f}" font-family="Helvetica,sans-serif" '
                   f'font-size="2.4" font-weight="900" fill="{INK}" text-anchor="middle">{v:.0f}%</text>')
        out.append(f'<text x="{x0 + each_w/2:.2f}" y="{bar_y + bar_h + 7.5:.2f}" font-family="Helvetica,sans-serif" '
                   f'font-size="2.2" fill="{INK_SOFT}" text-anchor="middle">{lbl}</text>')

    # Arrow + "陡降" label at the 150m cliff
    cliff_x = bar_x + 3.5 * (bar_w / len(bars))
    out.append(f'<line x1="{cliff_x-3:.2f}" y1="{bar_y + bar_h-13:.2f}" x2="{cliff_x:.2f}" y2="{bar_y + bar_h-3:.2f}" '
               f'stroke="{ACCENT_DARK}" stroke-width="0.4"/>')
    out.append(f'<text x="{cliff_x-5:.2f}" y="{bar_y + bar_h-15:.2f}" font-family="Georgia,serif" '
               f'font-size="2.6" font-style="italic" font-weight="900" fill="{ACCENT_DARK}" text-anchor="end">陡降 cliff</text>')

    # ==== Bottom takeaway band ====
    ty = H - 18
    out.append(f'<rect x="12" y="{ty}" width="{W-24}" height="11" fill="{INK}"/>')
    out.append(f'<text x="{W/2:.2f}" y="{ty+7:.2f}" font-family="Georgia,serif" '
               f'font-size="5" font-weight="900" fill="{HIGHLIGHT}" text-anchor="middle" '
               f'font-style="italic">▶  推送的真实影响范围 = 收到推送的居民 + 半径 150 米内的物理邻居。 </text>')

    # Source line below
    out.append(f'<text x="{W/2:.2f}" y="{H-3:.2f}" font-family="Georgia,serif" font-size="2.3" '
               f'font-style="italic" fill="{INK_LIGHT}" text-anchor="middle">'
               f'实验: 1,000 个虚拟居民 × 14 天 × 3 次独立重复 · Synthetic Socio Wind Tunnel · '
               f'github.com/york-zhouuu</text>')

    # Plain explanation tucked at top right (small)
    expl_x = panel_lx + panel_w - 4; expl_y = panel_y + 16
    # Just info box on the right edge of scene A
    out.append(f'<text x="{W-12}" y="49" font-family="Georgia,serif" font-size="2.5" '
               f'font-style="italic" fill="{INK_LIGHT}" text-anchor="end">'
               f'解释 ↘  原理是:邻居走出门 → 你在咖啡店/街角/公园看到 → 自己也走出门</text>')

    out.append("</svg>")
    (OUT / "finding2_v2_no_map.svg").write_text("\n".join(out))
    print(f"  → {OUT}/finding2_v2_no_map.svg")


if __name__ == "__main__":
    build()
