"""v4 — concept-diagram-first findings.

Each figure focuses on ONE conclusion and uses the visual that MOST DIRECTLY
makes it visible. Map is dropped unless map IS the point.

Plain Chinese throughout — no HP/GD/PF/protag jargon.
"""
from __future__ import annotations
import json
import math
from collections import defaultdict
from pathlib import Path

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
ATLAS = REPO / "data/lanecove_atlas.json"
ANALYSIS = REPO / "data/analysis/2026-05-23_paper_exploration"
OUT = REPO / "docs/figures_v4"
OUT.mkdir(parents=True, exist_ok=True)

# Palette (NYT)
INK = "#1B1F2A"
INK_SOFT = "#5A5E6A"
INK_LIGHT = "#A8ACB5"
BG_PAPER = "#FFFFFF"
BG_SCENE = "#F8F5EE"
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

W, H = 320, 220


# ──────────────────────────────────────────────────────────────────────
# Reusable primitives
# ──────────────────────────────────────────────────────────────────────
def person_walking(x, y, color, scale=1.0, halo=False):
    s = scale
    parts = []
    if halo:
        parts.append(f'<circle cx="{x:.2f}" cy="{y-2*s:.2f}" r="{4.5*s:.2f}" '
                     f'fill="{HIGHLIGHT}" fill-opacity="0.45"/>')
    parts.append(f'<circle cx="{x:.2f}" cy="{y - 3.5*s:.2f}" r="{0.9*s:.2f}" fill="{color}"/>')
    parts.append(f'<line x1="{x:.2f}" y1="{y-2.6*s:.2f}" x2="{x+0.3*s:.2f}" y2="{y+0.2*s:.2f}" '
                 f'stroke="{color}" stroke-width="{0.65*s:.2f}" stroke-linecap="round"/>')
    parts.append(f'<line x1="{x-1.2*s:.2f}" y1="{y-1.2*s:.2f}" x2="{x+0.2*s:.2f}" y2="{y-2.2*s:.2f}" '
                 f'stroke="{color}" stroke-width="{0.4*s:.2f}" stroke-linecap="round"/>')
    parts.append(f'<line x1="{x+0.2*s:.2f}" y1="{y-2.2*s:.2f}" x2="{x+1.4*s:.2f}" y2="{y-1.0*s:.2f}" '
                 f'stroke="{color}" stroke-width="{0.4*s:.2f}" stroke-linecap="round"/>')
    parts.append(f'<line x1="{x+0.3*s:.2f}" y1="{y+0.2*s:.2f}" x2="{x-1.2*s:.2f}" y2="{y+2.4*s:.2f}" '
                 f'stroke="{color}" stroke-width="{0.55*s:.2f}" stroke-linecap="round"/>')
    parts.append(f'<line x1="{x+0.3*s:.2f}" y1="{y+0.2*s:.2f}" x2="{x+1.7*s:.2f}" y2="{y+2.4*s:.2f}" '
                 f'stroke="{color}" stroke-width="{0.55*s:.2f}" stroke-linecap="round"/>')
    return parts


def person_home(x, y, color, scale=1.0):
    s = scale
    return [
        f'<path d="M {x-2*s:.2f} {y-0.5*s:.2f} L {x:.2f} {y-2.5*s:.2f} L {x+2*s:.2f} {y-0.5*s:.2f} Z" '
        f'fill="{color}" stroke="{INK}" stroke-width="0.1"/>',
        f'<rect x="{x-1.7*s:.2f}" y="{y-0.5*s:.2f}" width="{3.4*s:.2f}" height="{2.5*s:.2f}" '
        f'fill="{color}" stroke="{INK}" stroke-width="0.1"/>',
        f'<rect x="{x-0.4*s:.2f}" y="{y+0.7*s:.2f}" width="{0.8*s:.2f}" height="{1.3*s:.2f}" '
        f'fill="{INK}" opacity="0.55"/>',
    ]


def phone(x, y, w=14, h=24, screen_color=BG_PAPER, content_lines=None,
          content_color=INK, halo_color=None):
    """A simple phone mockup with notification lines on the screen."""
    parts = []
    if halo_color:
        parts.append(f'<rect x="{x-2:.2f}" y="{y-2:.2f}" width="{w+4:.2f}" height="{h+4:.2f}" '
                     f'rx="3" fill="{halo_color}" fill-opacity="0.35"/>')
    # body
    parts.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{w}" height="{h}" rx="1.5" '
                 f'fill="{INK}" stroke="{INK}" stroke-width="0.3"/>')
    # screen
    sm = 1.2
    parts.append(f'<rect x="{x+sm:.2f}" y="{y+sm:.2f}" width="{w-2*sm:.2f}" height="{h-2*sm-1.5:.2f}" '
                 f'fill="{screen_color}"/>')
    # speaker dot
    parts.append(f'<circle cx="{x+w/2:.2f}" cy="{y+0.9:.2f}" r="0.25" fill="{INK_LIGHT}"/>')
    # home button line
    parts.append(f'<line x1="{x+w/2-1.5:.2f}" y1="{y+h-0.8:.2f}" x2="{x+w/2+1.5:.2f}" y2="{y+h-0.8:.2f}" '
                 f'stroke="{INK_LIGHT}" stroke-width="0.25"/>')
    # content notifications
    if content_lines:
        ly = y + 3
        for line, color in content_lines:
            parts.append(f'<rect x="{x+2:.2f}" y="{ly:.2f}" width="{w-4:.2f}" height="3" '
                         f'fill="white" stroke="{color}" stroke-width="0.2" rx="0.4"/>')
            parts.append(f'<text x="{x+2.5:.2f}" y="{ly+2.1:.2f}" font-family="Helvetica,sans-serif" '
                         f'font-size="1.6" font-weight="700" fill="{color}">{line}</text>')
            ly += 3.6
    return parts


def header_band(idx, kicker, accent_word, headline_left, headline_right, subhead):
    return [
        f'<text x="12" y="14" font-family="Georgia,serif" font-size="3.3" '
        f'font-style="italic" fill="{ACCENT_DARK}" letter-spacing="0.3">'
        f'FINDING {idx:02d}  ·  {kicker}  ·  Lane Cove 虚拟实验</text>',
        f'<line x1="12" y1="17" x2="{W-12}" y2="17" stroke="{ACCENT_DARK}" stroke-width="0.3"/>',
        f'<text x="12" y="32" font-family="Georgia,serif" font-size="13" '
        f'font-weight="900" fill="{INK}" letter-spacing="-0.5">'
        f'{headline_left} <tspan fill="{ACCENT}">{accent_word}</tspan> {headline_right}</text>',
        f'<text x="12" y="42" font-family="Georgia,serif" font-size="4.5" '
        f'font-style="italic" fill="{INK_SOFT}">{subhead}</text>',
    ]


def takeaway_band(text, color_text=HIGHLIGHT):
    ty = H - 18
    return [
        f'<rect x="12" y="{ty}" width="{W-24}" height="11" fill="{INK}"/>',
        f'<text x="{W/2:.2f}" y="{ty+7:.2f}" font-family="Georgia,serif" '
        f'font-size="5" font-weight="900" fill="{color_text}" text-anchor="middle" '
        f'font-style="italic">▶  {text}</text>',
        f'<text x="{W/2:.2f}" y="{H-3:.2f}" font-family="Georgia,serif" font-size="2.3" '
        f'font-style="italic" fill="{INK_LIGHT}" text-anchor="middle">'
        f'实验: 1,000 个虚拟居民 × 14 天 × 3 次独立重复 · Synthetic Socio Wind Tunnel · '
        f'github.com/york-zhouuu</text>',
    ]


def svg_open():
    return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" '
            f'viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">',
            f'<rect width="100%" height="100%" fill="{BG_PAPER}"/>']


def write(name, parts):
    parts.append("</svg>")
    path = OUT / name
    path.write_text("\n".join(parts))
    print(f"  → {path.name}")


# ──────────────────────────────────────────────────────────────────────
# F1: Bimodal 22.7% / 77.3% — grid of 100 people
# ──────────────────────────────────────────────────────────────────────
def fig_1():
    parts = svg_open()
    parts.extend(header_band(1, "物理位移", "22.7%",
        "推送来到楼下,只有",
        "的居民真的走出门。",
        "剩下 77.3% 完全不为所动 — 不是「走一点点」,是要么大动 5+ 街区,要么完全没变化。"))

    # === Main visual: 10×10 grid of 100 person icons ===
    grid_x, grid_y = 50, 60
    cell = 8  # mm per cell
    # 23 walking pink (responders), 77 grey home (non-responders)
    # Distribute: rows 0-2 mostly pink, rest grey
    for i in range(100):
        col = i % 10
        row = i // 10
        cx = grid_x + col * cell + cell/2
        cy = grid_y + row * cell + cell/2
        # First 23: pink walking
        if i < 23:
            parts.extend(person_walking(cx, cy, ACCENT, scale=0.8))
        else:
            parts.extend(person_home(cx, cy, INK_LIGHT, scale=0.75))
    # Label below grid
    parts.append(f'<text x="{grid_x + 5*cell:.2f}" y="{grid_y + 10*cell + 6:.2f}" '
                 f'font-family="Georgia,serif" font-size="3" font-style="italic" '
                 f'fill="{INK_SOFT}" text-anchor="middle">100 名虚拟居民,按 22.7% 响应率比例显示</text>')

    # === Right side: numbers + key facts ===
    rx = grid_x + 10 * cell + 18
    # Responder stat
    parts.append(f'<text x="{rx}" y="68" font-family="Georgia,serif" font-size="26" '
                 f'font-weight="900" fill="{ACCENT}" letter-spacing="-1">22.7%</text>')
    parts.append(f'<text x="{rx}" y="75" font-family="Georgia,serif" font-size="4" '
                 f'font-weight="700" fill="{INK}">走出门去新地方</text>')
    parts.append(f'<text x="{rx}" y="79.5" font-family="Georgia,serif" font-size="3" '
                 f'font-style="italic" fill="{INK_SOFT}">中位位移 850 米 · 最远 3,121 米</text>')
    parts.append(f'<text x="{rx}" y="83.5" font-family="Georgia,serif" font-size="3" '
                 f'font-style="italic" fill="{INK_SOFT}">(走 5 个街区距离)</text>')

    # Non-responder
    parts.append(f'<text x="{rx}" y="105" font-family="Georgia,serif" font-size="20" '
                 f'font-weight="900" fill="{INK_LIGHT}" letter-spacing="-1">77.3%</text>')
    parts.append(f'<text x="{rx}" y="111" font-family="Georgia,serif" font-size="4" '
                 f'font-weight="700" fill="{INK}">完全不为所动</text>')
    parts.append(f'<text x="{rx}" y="115" font-family="Georgia,serif" font-size="3" '
                 f'font-style="italic" fill="{INK_SOFT}">轨迹与「未干预对照」完全重合</text>')

    parts.append(f'<line x1="{rx}" y1="125" x2="{W-12}" y2="125" stroke="{INK_LIGHT}" stroke-width="0.2"/>')

    # Key insight: bimodal
    parts.append(f'<text x="{rx}" y="135" font-family="Georgia,serif" font-size="3.6" '
                 f'font-weight="900" fill="{INK}">关键 · 没有「走一点点」</text>')
    # Bar showing: 0 days, 0 people; 1-5 days, 0 people; 6 days, 682 people
    bb_x = rx; bb_y = 140; bb_w = W - rx - 12
    parts.append(f'<rect x="{bb_x}" y="{bb_y}" width="{bb_w}" height="20" fill="{BG_SCENE}"/>')
    # 6 bars for "响应天数 0, 1, 2, 3, 4, 5, 6 (出 7 bar)"
    barw = bb_w / 7 - 1
    days = [(0, 2318), (1, 0), (2, 0), (3, 0), (4, 0), (5, 0), (6, 682)]
    max_v = 2500
    for i, (d, n) in enumerate(days):
        h = (n / max_v) * 13
        x0 = bb_x + i * (bb_w / 7) + 1
        y0 = bb_y + 16 - h
        color = INK_LIGHT if d == 0 else ACCENT if d == 6 else INK_LIGHT
        parts.append(f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{barw:.2f}" height="{h:.2f}" fill="{color}"/>')
        parts.append(f'<text x="{x0 + barw/2:.2f}" y="{bb_y + 18.5:.2f}" font-family="Helvetica,sans-serif" '
                     f'font-size="1.8" fill="{INK_SOFT}" text-anchor="middle">{d}</text>')
    parts.append(f'<text x="{bb_x + bb_w/2:.2f}" y="{bb_y - 1:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.3" font-style="italic" fill="{INK_SOFT}" text-anchor="middle">'
                 f'在 6 天干预期里,响应了几天的居民数</text>')

    # === Who are the responders? mini bars ===
    occs = [("退休的人 (n=403)", 37.2, ACCENT),
            ("失业的人 (n=97)", 39.2, ACCENT),
            ("学生 (n=668)", 18.3, INK_LIGHT),
            ("固定工时工程师 (n=88)", 8.0, INK_LIGHT)]
    oy = 175
    parts.append(f'<text x="50" y="{oy}" font-family="Georgia,serif" font-size="3.6" '
                 f'font-weight="900" fill="{INK}">谁是那 22.7%?  时间灵活的人响应最多</text>')
    parts.append(f'<text x="50" y="{oy + 4}" font-family="Georgia,serif" font-size="2.8" '
                 f'font-style="italic" fill="{INK_SOFT}">'
                 f'其中没有性别 / 收入 / 性格的差异 — 决定因素是「有没有时间」</text>')
    for i, (lbl, rate, color) in enumerate(occs):
        bx = 50 + (i % 4) * 65
        by = oy + 10 + (i // 4) * 8
        parts.append(f'<text x="{bx}" y="{by}" font-family="Helvetica,sans-serif" font-size="2.5" '
                     f'fill="{INK}">{lbl}</text>')
        bar_w = (rate / 45) * 45
        parts.append(f'<rect x="{bx}" y="{by+0.5}" width="{bar_w:.2f}" height="2.2" fill="{color}"/>')
        parts.append(f'<text x="{bx + bar_w + 1:.2f}" y="{by+2.3:.2f}" font-family="Helvetica,sans-serif" '
                     f'font-size="2.5" font-weight="900" fill="{INK}">{rate:.1f}%</text>')

    parts.extend(takeaway_band(
        "干预效果不是「人人走一点点」,是 1/5 居民走 5 个街区。"))

    write("finding_01_bimodal.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# F2: Already designed in mockup_finding2_v2 — copy logic here for self-contained
# ──────────────────────────────────────────────────────────────────────
def fig_2():
    parts = svg_open()
    parts.extend(header_band(2, "邻居效应", "8 倍",
        "你的邻居响应了推送 → 你自己响应概率高",
        "。",
        "实验里有 500 人能收到「楼下的事」推送,另外 500 人永远不收。第二组里谁会响应?只有家附近 150 米内有「响应邻居」的人。"))

    panel_y = 55; panel_h = 105
    panel_w = (W - 24 - 14) / 2
    panel_lx = 12
    panel_rx = panel_lx + panel_w + 14

    # Scene A — WITH responding neighbor
    parts.append(f'<rect x="{panel_lx}" y="{panel_y}" width="{panel_w}" height="{panel_h}" '
                 f'fill="{BG_SCENE}" stroke="{INK_LIGHT}" stroke-width="0.25"/>')
    parts.append(f'<rect x="{panel_lx}" y="{panel_y}" width="{panel_w}" height="9" fill="{ACCENT}"/>')
    parts.append(f'<text x="{panel_lx+4}" y="{panel_y+6}" font-family="Georgia,serif" '
                 f'font-size="4" font-weight="900" fill="white">场景 A</text>')
    parts.append(f'<text x="{panel_lx+panel_w-4}" y="{panel_y+6}" font-family="Georgia,serif" '
                 f'font-size="3.5" font-weight="700" fill="white" text-anchor="end" font-style="italic">'
                 f'你身边 150m 内,有响应邻居</text>')

    sa_cx = panel_lx + panel_w / 2
    sa_cy = panel_y + 9 + (panel_h - 9) / 2 - 2

    parts.append(f'<circle cx="{sa_cx:.2f}" cy="{sa_cy:.2f}" r="32" '
                 f'fill="{ACCENT}" fill-opacity="0.04" stroke="{ACCENT}" stroke-width="0.35" '
                 f'stroke-dasharray="1.2 0.8"/>')
    parts.append(f'<text x="{sa_cx+33:.2f}" y="{sa_cy-32:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.6" font-style="italic" font-weight="700" fill="{ACCENT_DARK}">150 米半径</text>')

    parts.extend(person_walking(sa_cx, sa_cy + 8, ACCENT, scale=1.4))
    parts.append(f'<text x="{sa_cx:.2f}" y="{sa_cy+15:.2f}" font-family="Georgia,serif" '
                 f'font-size="3" font-weight="900" fill="{INK}" text-anchor="middle">你</text>')
    parts.append(f'<text x="{sa_cx:.2f}" y="{sa_cy+18.5:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.5" fill="{INK_SOFT}" text-anchor="middle" font-style="italic">(不收推送,但走出门了)</text>')

    n_x, n_y = sa_cx - 22, sa_cy - 12
    parts.extend(person_walking(n_x, n_y, ACCENT, scale=1.2, halo=True))
    parts.append(f'<rect x="{n_x+3:.2f}" y="{n_y-6:.2f}" width="3" height="5" fill="white" stroke="{INK}" stroke-width="0.2" rx="0.3"/>')
    parts.append(f'<rect x="{n_x+3.5:.2f}" y="{n_y-5.5:.2f}" width="2" height="3.5" fill="{ACCENT}"/>')
    parts.append(f'<text x="{n_x:.2f}" y="{n_y-8:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.5" font-weight="700" fill="{ACCENT_DARK}" text-anchor="middle">邻居 ·</text>')
    parts.append(f'<text x="{n_x:.2f}" y="{n_y-5:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.5" font-weight="700" fill="{ACCENT_DARK}" text-anchor="middle">收到推送 → 走出门</text>')

    inner_A = [(sa_cx + 14, sa_cy - 16, "w"), (sa_cx + 22, sa_cy + 6, "h"),
               (sa_cx - 14, sa_cy + 14, "w"), (sa_cx + 4, sa_cy - 22, "h"),
               (sa_cx + 17, sa_cy + 17, "w"), (sa_cx - 8, sa_cy - 5, "h"),
               (sa_cx - 22, sa_cy + 10, "h"), (sa_cx + 10, sa_cy + 16, "h")]
    for px, py, kind in inner_A:
        if kind == "w": parts.extend(person_walking(px, py, ACCENT, scale=0.85))
        else: parts.extend(person_home(px, py, INK_LIGHT, scale=0.85))

    stat_y = panel_y + panel_h - 22
    parts.append(f'<text x="{sa_cx:.2f}" y="{stat_y:.2f}" font-family="Georgia,serif" '
                 f'font-size="20" font-weight="900" fill="{ACCENT}" text-anchor="middle" letter-spacing="-1">26%</text>')
    parts.append(f'<text x="{sa_cx:.2f}" y="{stat_y+6:.2f}" font-family="Georgia,serif" '
                 f'font-size="3.2" font-weight="700" fill="{INK}" text-anchor="middle">'
                 f'圈内「不收推送」的居民,响应率</text>')
    parts.append(f'<text x="{sa_cx:.2f}" y="{stat_y+10:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.5" fill="{INK_SOFT}" font-style="italic" text-anchor="middle">'
                 f'(n=1,170 居民, 3 seeds pooled)</text>')

    # Scene B
    parts.append(f'<rect x="{panel_rx}" y="{panel_y}" width="{panel_w}" height="{panel_h}" '
                 f'fill="{BG_SCENE}" stroke="{INK_LIGHT}" stroke-width="0.25"/>')
    parts.append(f'<rect x="{panel_rx}" y="{panel_y}" width="{panel_w}" height="9" fill="{INK_SOFT}"/>')
    parts.append(f'<text x="{panel_rx+4}" y="{panel_y+6}" font-family="Georgia,serif" '
                 f'font-size="4" font-weight="900" fill="white">场景 B</text>')
    parts.append(f'<text x="{panel_rx+panel_w-4}" y="{panel_y+6}" font-family="Georgia,serif" '
                 f'font-size="3.5" font-weight="700" fill="white" text-anchor="end" font-style="italic">'
                 f'同样情况,但邻居没响应</text>')

    sb_cx = panel_rx + panel_w / 2
    sb_cy = panel_y + 9 + (panel_h - 9) / 2 - 2

    parts.append(f'<circle cx="{sb_cx:.2f}" cy="{sb_cy:.2f}" r="32" '
                 f'fill="{INK_LIGHT}" fill-opacity="0.06" stroke="{INK_SOFT}" stroke-width="0.35" '
                 f'stroke-dasharray="1.2 0.8"/>')
    parts.append(f'<text x="{sb_cx+33:.2f}" y="{sb_cy-32:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.6" font-style="italic" font-weight="700" fill="{INK_SOFT}">150 米半径</text>')

    parts.extend(person_home(sb_cx, sb_cy + 7, INK_LIGHT, scale=1.5))
    parts.append(f'<text x="{sb_cx:.2f}" y="{sb_cy+15:.2f}" font-family="Georgia,serif" '
                 f'font-size="3" font-weight="900" fill="{INK}" text-anchor="middle">你</text>')
    parts.append(f'<text x="{sb_cx:.2f}" y="{sb_cy+18.5:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.5" fill="{INK_SOFT}" text-anchor="middle" font-style="italic">(不收推送 + 没走出门)</text>')

    n_x, n_y = sb_cx - 22, sb_cy - 12
    parts.extend(person_home(n_x, n_y, INK_LIGHT, scale=1.2))
    parts.append(f'<rect x="{n_x+3:.2f}" y="{n_y-3:.2f}" width="3" height="5" fill="white" stroke="{INK}" stroke-width="0.2" rx="0.3"/>')
    parts.append(f'<rect x="{n_x+3.5:.2f}" y="{n_y-2.5:.2f}" width="2" height="3.5" fill="{INK_LIGHT}"/>')
    parts.append(f'<text x="{n_x:.2f}" y="{n_y-5:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.5" font-weight="700" fill="{INK_SOFT}" text-anchor="middle">邻居 ·</text>')
    parts.append(f'<text x="{n_x:.2f}" y="{n_y-2:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.5" font-weight="700" fill="{INK_SOFT}" text-anchor="middle">收到推送但没响应</text>')

    inner_B = [(sb_cx + 14, sb_cy - 16), (sb_cx + 22, sb_cy + 6),
               (sb_cx - 14, sb_cy + 14), (sb_cx + 4, sb_cy - 22),
               (sb_cx + 17, sb_cy + 17), (sb_cx - 8, sb_cy - 5),
               (sb_cx - 22, sb_cy + 10), (sb_cx + 10, sb_cy + 16)]
    for px, py in inner_B:
        parts.extend(person_home(px, py, INK_LIGHT, scale=0.85))

    parts.append(f'<text x="{sb_cx:.2f}" y="{stat_y:.2f}" font-family="Georgia,serif" '
                 f'font-size="20" font-weight="900" fill="{INK_SOFT}" text-anchor="middle" letter-spacing="-1">4%</text>')
    parts.append(f'<text x="{sb_cx:.2f}" y="{stat_y+6:.2f}" font-family="Georgia,serif" '
                 f'font-size="3.2" font-weight="700" fill="{INK}" text-anchor="middle">'
                 f'同样的人,响应率</text>')
    parts.append(f'<text x="{sb_cx:.2f}" y="{stat_y+10:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.5" fill="{INK_SOFT}" font-style="italic" text-anchor="middle">'
                 f'(n=207 居民)</text>')

    # Center arrow + 8×
    arr_cx = (panel_lx + panel_w + panel_rx) / 2
    arr_cy = panel_y + 60
    parts.append(f'<line x1="{arr_cx-5:.2f}" y1="{arr_cy:.2f}" x2="{arr_cx+5:.2f}" y2="{arr_cy:.2f}" '
                 f'stroke="{INK}" stroke-width="0.6"/>')
    parts.append(f'<polygon points="{arr_cx+5:.2f},{arr_cy:.2f} {arr_cx+3:.2f},{arr_cy-1.5:.2f} '
                 f'{arr_cx+3:.2f},{arr_cy+1.5:.2f}" fill="{INK}"/>')
    parts.append(f'<polygon points="{arr_cx-5:.2f},{arr_cy:.2f} {arr_cx-3:.2f},{arr_cy-1.5:.2f} '
                 f'{arr_cx-3:.2f},{arr_cy+1.5:.2f}" fill="{INK}"/>')
    parts.append(f'<rect x="{arr_cx-7:.2f}" y="{arr_cy+3:.2f}" width="14" height="9" fill="{ACCENT}" rx="0.5"/>')
    parts.append(f'<text x="{arr_cx:.2f}" y="{arr_cy+9:.2f}" font-family="Georgia,serif" '
                 f'font-size="7" font-weight="900" fill="white" text-anchor="middle">8×</text>')
    parts.append(f'<text x="{arr_cx:.2f}" y="{arr_cy+15:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.6" font-style="italic" fill="{INK_SOFT}" text-anchor="middle">差距</text>')

    # Distance decay
    by = 175
    parts.append(f'<line x1="12" y1="{by-3}" x2="{W-12}" y2="{by-3}" stroke="{INK_LIGHT}" stroke-width="0.2"/>')
    parts.append(f'<text x="12" y="{by+2}" font-family="Georgia,serif" font-size="4" '
                 f'font-weight="900" fill="{INK}">为什么是 150 米?</text>')
    parts.append(f'<text x="12" y="{by+6.5}" font-family="Georgia,serif" font-size="3" '
                 f'font-style="italic" fill="{INK_SOFT}">效应随邻居距离呈陡降衰减,150-200 米之间是临界点</text>')

    bar_x = 130; bar_y = by; bar_w = 175; bar_h = 25
    bars = [("0-50 米", 26.2, ACCENT), ("50-100 米", 20.6, ACCENT),
            ("100-150 米", 11.4, ACCENT_DARK), ("150-200 米", 4.3, INK_SOFT),
            ("200-300 米", 4.4, INK_SOFT), ("300+ 米", 1.0, INK_LIGHT)]
    each_w = bar_w / len(bars) - 1
    max_v = 30
    for j, (lbl, v, color) in enumerate(bars):
        h = (v / max_v) * bar_h
        x0 = bar_x + j * (bar_w / len(bars))
        y0 = bar_y + bar_h - h + 4
        parts.append(f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{each_w:.2f}" height="{h:.2f}" fill="{color}"/>')
        parts.append(f'<text x="{x0 + each_w/2:.2f}" y="{y0-0.4:.2f}" font-family="Helvetica,sans-serif" '
                     f'font-size="2.4" font-weight="900" fill="{INK}" text-anchor="middle">{v:.0f}%</text>')
        parts.append(f'<text x="{x0 + each_w/2:.2f}" y="{bar_y + bar_h + 7.5:.2f}" font-family="Helvetica,sans-serif" '
                     f'font-size="2.2" fill="{INK_SOFT}" text-anchor="middle">{lbl}</text>')

    cliff_x = bar_x + 3.5 * (bar_w / len(bars))
    parts.append(f'<line x1="{cliff_x-3:.2f}" y1="{bar_y + bar_h-13:.2f}" x2="{cliff_x:.2f}" y2="{bar_y + bar_h-3:.2f}" '
                 f'stroke="{ACCENT_DARK}" stroke-width="0.4"/>')
    parts.append(f'<text x="{cliff_x-5:.2f}" y="{bar_y + bar_h-15:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.6" font-style="italic" font-weight="900" fill="{ACCENT_DARK}" text-anchor="end">陡降</text>')

    parts.extend(takeaway_band(
        "推送的真实影响范围 = 收到推送的居民 + 半径 150 米内的物理邻居。"))

    write("finding_02_spillover.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# F3: Repeat encounters 17 vs 71 — two timelines + strong tie growth
# ──────────────────────────────────────────────────────────────────────
def fig_3():
    parts = svg_open()
    parts.extend(header_band(3, "见面频率", "4 倍",
        "同一对邻居在 14 天里见到对方的次数变成",
        "。",
        "推送不让你认识新陌生人。它让你和已经在身边的人,见面更频繁 — 弱关系沉淀为强关系。"))

    # ── Two timelines: 14 days, dots = meetings between same pair
    tl_x = 35; tl_w = W - tl_x - 90
    # Timeline BL (top)
    tl_y_bl = 70
    parts.append(f'<text x="{tl_x - 4}" y="{tl_y_bl}" font-family="Georgia,serif" font-size="5" '
                 f'font-weight="900" fill="{INK_SOFT}" text-anchor="end">基线</text>')
    parts.append(f'<text x="{tl_x - 4}" y="{tl_y_bl+4}" font-family="Georgia,serif" font-size="2.6" '
                 f'fill="{INK_SOFT}" text-anchor="end" font-style="italic">无推送</text>')
    parts.append(f'<rect x="{tl_x}" y="{tl_y_bl-3}" width="{tl_w}" height="8" fill="{BG_SCENE}" stroke="{INK_LIGHT}" stroke-width="0.2"/>')
    # 17 dots scattered uniformly
    import random
    random.seed(42)
    for i in range(17):
        dx = tl_x + 2 + random.random() * (tl_w - 4)
        dy = tl_y_bl + 1 + random.random() * 2
        parts.append(f'<circle cx="{dx:.2f}" cy="{dy:.2f}" r="0.85" fill="{INK_SOFT}"/>')
    parts.append(f'<text x="{tl_x + tl_w + 4}" y="{tl_y_bl - 1}" font-family="Georgia,serif" '
                 f'font-size="11" font-weight="900" fill="{INK_SOFT}">17</text>')
    parts.append(f'<text x="{tl_x + tl_w + 4}" y="{tl_y_bl + 4}" font-family="Georgia,serif" '
                 f'font-size="3" fill="{INK_SOFT}" font-style="italic">次相遇</text>')

    # Timeline HP (bottom)
    tl_y_hp = 95
    parts.append(f'<text x="{tl_x - 4}" y="{tl_y_hp}" font-family="Georgia,serif" font-size="5" '
                 f'font-weight="900" fill="{ACCENT}" text-anchor="end">推送</text>')
    parts.append(f'<text x="{tl_x - 4}" y="{tl_y_hp+4}" font-family="Georgia,serif" font-size="2.6" '
                 f'fill="{ACCENT_DARK}" text-anchor="end" font-style="italic">楼下事件</text>')
    parts.append(f'<rect x="{tl_x}" y="{tl_y_hp-3}" width="{tl_w}" height="8" fill="{ACCENT_SOFT}" stroke="{ACCENT}" stroke-width="0.2"/>')
    # 71 dots
    random.seed(43)
    for i in range(71):
        dx = tl_x + 2 + random.random() * (tl_w - 4)
        dy = tl_y_hp + 1 + random.random() * 2
        parts.append(f'<circle cx="{dx:.2f}" cy="{dy:.2f}" r="0.9" fill="{ACCENT}"/>')
    parts.append(f'<text x="{tl_x + tl_w + 4}" y="{tl_y_hp - 1}" font-family="Georgia,serif" '
                 f'font-size="11" font-weight="900" fill="{ACCENT}">71</text>')
    parts.append(f'<text x="{tl_x + tl_w + 4}" y="{tl_y_hp + 4}" font-family="Georgia,serif" '
                 f'font-size="3" fill="{ACCENT_DARK}" font-style="italic">次相遇</text>')

    # X axis (day labels)
    for d in [1, 4, 7, 11, 14]:
        x = tl_x + ((d-1) / 13) * tl_w
        parts.append(f'<text x="{x:.2f}" y="{tl_y_hp + 11:.2f}" font-family="Helvetica,sans-serif" '
                     f'font-size="2.3" fill="{INK_SOFT}" text-anchor="middle">day {d}</text>')
        parts.append(f'<line x1="{x:.2f}" y1="{tl_y_bl - 6}" x2="{x:.2f}" y2="{tl_y_hp + 8}" '
                     f'stroke="{INK_LIGHT}" stroke-width="0.1" stroke-dasharray="0.4 0.6"/>')

    # Label: "同一对邻居 A & B"
    parts.append(f'<text x="{tl_x + tl_w/2}" y="60" font-family="Georgia,serif" font-size="3.6" '
                 f'font-weight="900" fill="{INK}" text-anchor="middle">同一对邻居 (A &amp; B),14 天里见到对方的每一次</text>')
    parts.append(f'<text x="{tl_x + tl_w/2}" y="64" font-family="Georgia,serif" font-size="2.7" '
                 f'font-style="italic" fill="{INK_SOFT}" text-anchor="middle">每一个圆点 = 一次擦肩 / 短暂共处</text>')

    # === Strong tie growth right side ===
    parts.append(f'<text x="55" y="120" font-family="Georgia,serif" font-size="3.6" '
                 f'font-weight="900" fill="{INK}">见面频率翻 4 倍 → 关系强度翻 5.6 倍</text>')
    parts.append(f'<text x="55" y="124" font-family="Georgia,serif" font-size="2.8" '
                 f'font-style="italic" fill="{INK_SOFT}">弱关系不变 (15K),但强关系数量翻 5.6 倍 — 频次将「点头之交」变成「真朋友」</text>')

    # Two bar groups: weak ties + strong ties, BL vs HP
    bar_y = 130
    groups = [("弱关系\n(认识但不熟)", 15.8, 15.1, INK_SOFT),
              ("强关系\n(真朋友)", 10.1, 56.6, ACCENT)]
    for i, (lbl, bl, hp, color) in enumerate(groups):
        gx = 55 + i * 120
        # Label
        for j, ln in enumerate(lbl.split("\n")):
            parts.append(f'<text x="{gx}" y="{bar_y + j*3.5:.2f}" font-family="Georgia,serif" '
                         f'font-size="2.8" font-weight="700" fill="{INK}">{ln}</text>')
        # BL bar
        bl_w = (bl / 60) * 80
        parts.append(f'<rect x="{gx}" y="{bar_y + 9}" width="{bl_w:.2f}" height="4" fill="{INK_LIGHT}"/>')
        parts.append(f'<text x="{gx + bl_w + 1.5:.2f}" y="{bar_y + 12.5:.2f}" font-family="Helvetica,sans-serif" '
                     f'font-size="3" font-weight="900" fill="{INK_SOFT}">{bl:.1f}K · 基线</text>')
        # HP bar
        hp_w = (hp / 60) * 80
        parts.append(f'<rect x="{gx}" y="{bar_y + 15}" width="{hp_w:.2f}" height="4" fill="{color}"/>')
        parts.append(f'<text x="{gx + hp_w + 1.5:.2f}" y="{bar_y + 18.5:.2f}" font-family="Helvetica,sans-serif" '
                     f'font-size="3" font-weight="900" fill="{color}">{hp:.1f}K · 推送</text>')

    # Big right-side "5.6×" callout
    parts.append(f'<rect x="265" y="155" width="42" height="22" fill="{ACCENT}" rx="0.5"/>')
    parts.append(f'<text x="286" y="167" font-family="Georgia,serif" font-size="9" '
                 f'font-weight="900" fill="white" text-anchor="middle">5.6×</text>')
    parts.append(f'<text x="286" y="173" font-family="Georgia,serif" font-size="3" '
                 f'fill="white" text-anchor="middle" font-style="italic">强关系翻倍</text>')

    parts.extend(takeaway_band(
        "推送不是让你认识新陌生人 — 是让身边邻居见到的次数翻倍,关系自然沉淀。"))

    write("finding_03_repeat.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# F4: Post-period growth 1.32× — clean line chart, no map
# ──────────────────────────────────────────────────────────────────────
def fig_4():
    parts = svg_open()
    parts.extend(header_band(4, "推送停了之后", "1.32×",
        "干预后撤 4 天里,偶遇量还在继续增长",
        "。",
        "推送 6 天,然后停止。本以为会回到基线 — 但偶遇量在接下来 4 天里继续上涨 32%。网络效应自维持。"))

    # Load data
    with open(ANALYSIS / "B_temporal_curves/per_day_series.json") as f:
        tc = json.load(f)

    # Big line chart
    cx = 30; cy = 55; cw = W - 60; ch = 110
    parts.append(f'<rect x="{cx}" y="{cy}" width="{cw}" height="{ch}" fill="{BG_PAPER}" stroke="{INK_LIGHT}" stroke-width="0.2"/>')

    plot_x = cx + 16; plot_y = cy + 12
    plot_w = cw - 26; plot_h = ch - 24

    # Phase shading
    parts.append(f'<rect x="{plot_x}" y="{plot_y}" width="{plot_w * 4/14:.2f}" height="{plot_h}" '
                 f'fill="{INK_LIGHT}" fill-opacity="0.15"/>')
    parts.append(f'<rect x="{plot_x + plot_w*4/14:.2f}" y="{plot_y}" width="{plot_w * 6/14:.2f}" height="{plot_h}" '
                 f'fill="{ACCENT}" fill-opacity="0.10"/>')
    parts.append(f'<rect x="{plot_x + plot_w*10/14:.2f}" y="{plot_y}" width="{plot_w * 4/14:.2f}" height="{plot_h}" '
                 f'fill="{HIGHLIGHT}" fill-opacity="0.20"/>')

    # Phase labels (above chart)
    parts.append(f'<text x="{plot_x + plot_w*2/14:.2f}" y="{plot_y - 3:.2f}" font-family="Georgia,serif" '
                 f'font-size="3.5" font-weight="900" fill="{INK_SOFT}" text-anchor="middle">基线 (前 4 天)</text>')
    parts.append(f'<text x="{plot_x + plot_w*2/14:.2f}" y="{plot_y + 1.5:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.5" fill="{INK_SOFT}" text-anchor="middle" font-style="italic">无推送</text>')

    parts.append(f'<text x="{plot_x + plot_w*7/14:.2f}" y="{plot_y - 3:.2f}" font-family="Georgia,serif" '
                 f'font-size="3.5" font-weight="900" fill="{ACCENT}" text-anchor="middle">干预期 (6 天)</text>')
    parts.append(f'<text x="{plot_x + plot_w*7/14:.2f}" y="{plot_y + 1.5:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.5" fill="{ACCENT}" text-anchor="middle" font-style="italic">每天推送 5 条「楼下的事」</text>')

    parts.append(f'<text x="{plot_x + plot_w*12/14:.2f}" y="{plot_y - 3:.2f}" font-family="Georgia,serif" '
                 f'font-size="3.5" font-weight="900" fill="{ACCENT_DARK}" text-anchor="middle">后撤期 (4 天)</text>')
    parts.append(f'<text x="{plot_x + plot_w*12/14:.2f}" y="{plot_y + 1.5:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.5" fill="{ACCENT_DARK}" text-anchor="middle" font-style="italic">推送停止</text>')

    # Line chart
    max_v = 5.0
    variants = [
        ("hyperlocal_push", ACCENT, "推送楼下"),
        ("phone_friction", GREEN, "减少手机"),
        ("global_distraction", BLUE, "全球新闻"),
        ("baseline", INK_LIGHT, "无干预"),
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
        parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.1"/>')
        for x, y in pts:
            parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="1" fill="{color}"/>')
        last_x, last_y = pts[-1]
        parts.append(f'<text x="{last_x+2:.2f}" y="{last_y+1.5:.2f}" font-family="Georgia,serif" '
                     f'font-size="3.5" font-weight="900" fill="{color}">{lbl}</text>')

    # Y axis labels
    for v in [0, 1, 2, 3, 4, 5]:
        py = plot_y + plot_h - (v/max_v) * plot_h
        parts.append(f'<text x="{plot_x-2:.2f}" y="{py+0.9:.2f}" font-family="Helvetica,sans-serif" '
                     f'font-size="2.4" fill="{INK_SOFT}" text-anchor="end">{v}M</text>')
    parts.append(f'<text x="{plot_x-12:.2f}" y="{plot_y + plot_h/2:.2f}" font-family="Georgia,serif" '
                 f'font-size="3" font-style="italic" fill="{INK_SOFT}" text-anchor="middle" '
                 f'transform="rotate(-90, {plot_x-12:.2f}, {plot_y + plot_h/2:.2f})">每日偶遇 (百万)</text>')
    # X labels
    for d in [0, 4, 9, 13]:
        px = plot_x + (d / 13) * plot_w
        parts.append(f'<text x="{px:.2f}" y="{plot_y + plot_h + 3.5:.2f}" font-family="Helvetica,sans-serif" '
                     f'font-size="2.6" font-weight="700" fill="{INK}" text-anchor="middle">day {d}</text>')

    # KEY annotation
    end_x = plot_x + plot_w
    parts.append(f'<rect x="{end_x-50:.2f}" y="{plot_y+3}" width="48" height="13" fill="{ACCENT_DARK}" rx="0.5"/>')
    parts.append(f'<text x="{end_x-26:.2f}" y="{plot_y+8:.2f}" font-family="Georgia,serif" '
                 f'font-size="3.5" font-weight="900" fill="white" text-anchor="middle">推送停了之后还在涨</text>')
    parts.append(f'<text x="{end_x-26:.2f}" y="{plot_y+12.5:.2f}" font-family="Georgia,serif" '
                 f'font-size="3.2" font-weight="900" fill="{HIGHLIGHT}" text-anchor="middle">+ 32%</text>')

    # Bottom: 4 quick stat boxes
    by = cy + ch + 8
    stats = [
        ("基线 (day 0-3)", "0.6M / 天", "对照", INK_LIGHT),
        ("干预期 (day 4-9)", "3.2M / 天", "5.5× 基线", ACCENT),
        ("后撤期 (day 10-13)", "4.2M / 天", "7.2× 基线", ACCENT_DARK),
        ("后撤/干预 比", "1.32×", "推送停了反而更多", HIGHLIGHT),
    ]
    cell_w = (W - 24) / len(stats)
    for i, (top_lbl, big, sub, color) in enumerate(stats):
        x = 12 + i * cell_w
        parts.append(f'<rect x="{x}" y="{by}" width="{cell_w-1.5:.2f}" height="22" fill="{BG_SCENE}" stroke="{INK_LIGHT}" stroke-width="0.15"/>')
        parts.append(f'<text x="{x + cell_w/2:.2f}" y="{by+4.5:.2f}" font-family="Georgia,serif" '
                     f'font-size="2.5" font-weight="700" fill="{INK_SOFT}" text-anchor="middle" letter-spacing="0.3">{top_lbl}</text>')
        parts.append(f'<text x="{x + cell_w/2:.2f}" y="{by+13:.2f}" font-family="Georgia,serif" '
                     f'font-size="7" font-weight="900" fill="{color}" text-anchor="middle">{big}</text>')
        parts.append(f'<text x="{x + cell_w/2:.2f}" y="{by+18:.2f}" font-family="Georgia,serif" '
                     f'font-size="2.5" fill="{INK_SOFT}" font-style="italic" text-anchor="middle">{sub}</text>')

    parts.extend(takeaway_band(
        "干预不需要永远跑 — 一旦把人推到新位置,网络效应自维持并继续增长。"))

    write("finding_04_compounding.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# F5: Mirror — two phone mockups, no map
# ──────────────────────────────────────────────────────────────────────
def fig_5():
    parts = svg_open()
    parts.extend(header_band(5, "推送内容决定一切", "11 倍",
        "同样每天 5 条推送,但内容不同 → 偶遇量差距",
        "。",
        "推送「楼下的事」: 偶遇 +377%。 推送「全球新闻」: 偶遇仅 +33%。 是「内容指向」决定效应,不是「推送动作」本身。"))

    # Two side-by-side scenes
    panel_y = 55; panel_h = 110
    panel_w = (W - 24 - 14) / 2
    panel_lx = 12; panel_rx = panel_lx + panel_w + 14

    # === LEFT: 推送楼下 ===
    parts.append(f'<rect x="{panel_lx}" y="{panel_y}" width="{panel_w}" height="{panel_h}" '
                 f'fill="{BG_SCENE}" stroke="{INK_LIGHT}" stroke-width="0.25"/>')
    parts.append(f'<rect x="{panel_lx}" y="{panel_y}" width="{panel_w}" height="10" fill="{ACCENT}"/>')
    parts.append(f'<text x="{panel_lx+4}" y="{panel_y+7}" font-family="Georgia,serif" '
                 f'font-size="4.5" font-weight="900" fill="white">推送「楼下的事」</text>')

    # Phone mockup
    ph_x = panel_lx + 12; ph_y = panel_y + 17
    parts.extend(phone(ph_x, ph_y, w=22, h=38, halo_color=ACCENT, content_lines=[
        ("🏠 楼下咖啡店今天有", ACCENT_DARK),
        ("Cowper 街社区聚会", ACCENT_DARK),
        ("邻居 Anna 在找猫", ACCENT_DARK),
        ("Longueville Park 早市", ACCENT_DARK),
        ("Mowbray 街角免费课", ACCENT_DARK),
    ]))
    parts.append(f'<text x="{ph_x+11:.2f}" y="{ph_y-2:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.6" font-style="italic" fill="{INK_SOFT}" text-anchor="middle">5 条推送/天</text>')

    # Arrow
    parts.append(f'<line x1="{ph_x+24:.2f}" y1="{ph_y+19:.2f}" x2="{ph_x+34:.2f}" y2="{ph_y+19:.2f}" '
                 f'stroke="{ACCENT}" stroke-width="0.8"/>')
    parts.append(f'<polygon points="{ph_x+34:.2f},{ph_y+19:.2f} {ph_x+32:.2f},{ph_y+17.5:.2f} '
                 f'{ph_x+32:.2f},{ph_y+20.5:.2f}" fill="{ACCENT}"/>')

    # Walking person (out of home)
    parts.extend(person_walking(ph_x + 50, ph_y + 25, ACCENT, scale=2.0))
    parts.append(f'<text x="{ph_x + 50:.2f}" y="{ph_y + 41:.2f}" font-family="Georgia,serif" '
                 f'font-size="3" font-weight="900" fill="{ACCENT}" text-anchor="middle">走出门</text>')
    # +377% big number
    parts.append(f'<text x="{panel_lx + panel_w - 6:.2f}" y="{panel_y + panel_h - 14:.2f}" '
                 f'font-family="Georgia,serif" font-size="22" font-weight="900" fill="{ACCENT}" '
                 f'text-anchor="end" letter-spacing="-1">+377%</text>')
    parts.append(f'<text x="{panel_lx + panel_w - 6:.2f}" y="{panel_y + panel_h - 8:.2f}" '
                 f'font-family="Georgia,serif" font-size="3" font-weight="700" fill="{INK}" '
                 f'text-anchor="end">偶遇增加</text>')
    parts.append(f'<text x="{panel_lx + panel_w - 6:.2f}" y="{panel_y + panel_h - 4:.2f}" '
                 f'font-family="Georgia,serif" font-size="2.5" font-style="italic" fill="{INK_SOFT}" '
                 f'text-anchor="end">vs 无推送</text>')

    # === RIGHT: 推送全球新闻 ===
    parts.append(f'<rect x="{panel_rx}" y="{panel_y}" width="{panel_w}" height="{panel_h}" '
                 f'fill="{BG_SCENE}" stroke="{INK_LIGHT}" stroke-width="0.25"/>')
    parts.append(f'<rect x="{panel_rx}" y="{panel_y}" width="{panel_w}" height="10" fill="{BLUE}"/>')
    parts.append(f'<text x="{panel_rx+4}" y="{panel_y+7}" font-family="Georgia,serif" '
                 f'font-size="4.5" font-weight="900" fill="white">推送「全球新闻」</text>')

    ph_x = panel_rx + 12; ph_y = panel_y + 17
    parts.extend(phone(ph_x, ph_y, w=22, h=38, halo_color=BLUE, content_lines=[
        ("🌍 美国大选最新动态", BLUE),
        ("地中海地区地震 7.2", BLUE),
        ("好莱坞明星离婚", BLUE),
        ("欧洲央行加息", BLUE),
        ("世界杯决赛预测", BLUE),
    ]))
    parts.append(f'<text x="{ph_x+11:.2f}" y="{ph_y-2:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.6" font-style="italic" fill="{INK_SOFT}" text-anchor="middle">5 条推送/天</text>')

    # Arrow (dimmer)
    parts.append(f'<line x1="{ph_x+24:.2f}" y1="{ph_y+19:.2f}" x2="{ph_x+34:.2f}" y2="{ph_y+19:.2f}" '
                 f'stroke="{INK_LIGHT}" stroke-width="0.8"/>')
    parts.append(f'<polygon points="{ph_x+34:.2f},{ph_y+19:.2f} {ph_x+32:.2f},{ph_y+17.5:.2f} '
                 f'{ph_x+32:.2f},{ph_y+20.5:.2f}" fill="{INK_LIGHT}"/>')

    # Home (didn't go out)
    parts.extend(person_home(ph_x + 50, ph_y + 25, INK_LIGHT, scale=2.4))
    parts.append(f'<text x="{ph_x + 50:.2f}" y="{ph_y + 41:.2f}" font-family="Georgia,serif" '
                 f'font-size="3" font-weight="900" fill="{INK_SOFT}" text-anchor="middle">留在家</text>')

    # +33% number
    parts.append(f'<text x="{panel_rx + panel_w - 6:.2f}" y="{panel_y + panel_h - 14:.2f}" '
                 f'font-family="Georgia,serif" font-size="22" font-weight="900" fill="{BLUE}" '
                 f'text-anchor="end" letter-spacing="-1">+33%</text>')
    parts.append(f'<text x="{panel_rx + panel_w - 6:.2f}" y="{panel_y + panel_h - 8:.2f}" '
                 f'font-family="Georgia,serif" font-size="3" font-weight="700" fill="{INK}" '
                 f'text-anchor="end">偶遇微增</text>')
    parts.append(f'<text x="{panel_rx + panel_w - 6:.2f}" y="{panel_y + panel_h - 4:.2f}" '
                 f'font-family="Georgia,serif" font-size="2.5" font-style="italic" fill="{INK_SOFT}" '
                 f'text-anchor="end">vs 无推送</text>')

    # Center: 11x callout
    arr_cx = (panel_lx + panel_w + panel_rx) / 2
    arr_cy = panel_y + 65
    parts.append(f'<rect x="{arr_cx-7:.2f}" y="{arr_cy-5:.2f}" width="14" height="11" fill="{INK}" rx="0.5"/>')
    parts.append(f'<text x="{arr_cx:.2f}" y="{arr_cy+1:.2f}" font-family="Georgia,serif" '
                 f'font-size="6" font-weight="900" fill="{HIGHLIGHT}" text-anchor="middle">11×</text>')
    parts.append(f'<text x="{arr_cx:.2f}" y="{arr_cy+4:.2f}" font-family="Georgia,serif" '
                 f'font-size="2.2" font-style="italic" fill="white" text-anchor="middle">差距</text>')

    # Bottom: 5-metric comparison row
    by = 175
    parts.append(f'<text x="12" y="{by}" font-family="Georgia,serif" font-size="3.6" '
                 f'font-weight="900" fill="{INK}">5 个维度全方位对比</text>')
    metrics = [
        ("偶遇增加", "4.77×", "1.33×"),
        ("响应率", "22.7%", "~13%"),
        ("轨迹偏移", "108 m", "51 m"),
        ("每对相遇", "71 次", "24 次"),
        ("重规划数", "1,990", "447"),
    ]
    cell_w = (W - 24) / len(metrics)
    by2 = by + 4
    for i, (m, hp, gd) in enumerate(metrics):
        x = 12 + i * cell_w
        parts.append(f'<rect x="{x}" y="{by2}" width="{cell_w-1.5:.2f}" height="13" fill="{BG_SCENE}" stroke="{INK_LIGHT}" stroke-width="0.1"/>')
        parts.append(f'<text x="{x + cell_w/2:.2f}" y="{by2+3.5:.2f}" font-family="Helvetica,sans-serif" '
                     f'font-size="2.3" fill="{INK_SOFT}" text-anchor="middle" letter-spacing="0.3">{m}</text>')
        parts.append(f'<text x="{x + cell_w/2 - 9:.2f}" y="{by2+9.5:.2f}" font-family="Georgia,serif" '
                     f'font-size="4" font-weight="900" fill="{ACCENT}" text-anchor="middle">{hp}</text>')
        parts.append(f'<text x="{x + cell_w/2 - 1:.2f}" y="{by2+9.5:.2f}" font-family="Georgia,serif" '
                     f'font-size="2" fill="{INK_LIGHT}" text-anchor="middle">vs</text>')
        parts.append(f'<text x="{x + cell_w/2 + 8:.2f}" y="{by2+9.5:.2f}" font-family="Georgia,serif" '
                     f'font-size="3.5" font-weight="900" fill="{BLUE}" text-anchor="middle">{gd}</text>')

    parts.extend(takeaway_band(
        "「推送内容指向」决定一切。推送 ≠ 推送 — 内容是因,推送是壳。"))

    write("finding_05_mirror.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# F6: POI activation — MAP IS USEFUL HERE
# ──────────────────────────────────────────────────────────────────────
def fig_6():
    parts = svg_open()
    parts.extend(header_band(6, "Lane Cove 街角被点亮", "0 → 21,000",
        "Longueville Park 从无人去,变成 14 天里 10 天有人来 ·",
        "ticks 跨越。",
        "ticks 是抽象单位,但映射到真实 Lane Cove 街区,推送让具体的咖啡店 / 公园 / 教堂 / 健身房真的活过来。"))

    # Load atlas + POI data
    with open(ATLAS) as f:
        atlas = json.load(f)
    with open(ANALYSIS / "DEEP_MINING/specific_pois.json") as f:
        sp = json.load(f)
    top_pois = sp["top_activated"][:8]

    # Simple map
    def centroid(verts):
        if not verts: return None
        xs = [v["x"] for v in verts] if isinstance(verts[0], dict) else [v[0] for v in verts]
        ys = [v["y"] for v in verts] if isinstance(verts[0], dict) else [v[1] for v in verts]
        return sum(xs)/len(xs), sum(ys)/len(ys)

    hub = atlas["buildings"].get("lane_cove_community_hub")
    center = centroid(hub.get("polygon", {}).get("vertices", [])) if hub else (0, 0)
    cx_a, cy_a = center

    # Left: map
    map_x = 12; map_y = 50; map_w = 170; map_h = 130
    radius = 1100
    scale = min(map_w / (2 * radius), map_h / (2 * radius))
    def proj(x, y):
        return map_x + map_w/2 + (x - cx_a) * scale, map_y + map_h/2 - (y - cy_a) * scale
    parts.append(f'<rect x="{map_x}" y="{map_y}" width="{map_w}" height="{map_h}" fill="{BG_MAP}" stroke="{INK_LIGHT}" stroke-width="0.2"/>')

    # Streets (light)
    outdoor = atlas.get("outdoor_areas", {})
    if isinstance(outdoor, dict): outdoor = list(outdoor.values())
    for o in outdoor:
        if (o.get("area_type") or "") not in ("street", "park", "playground"): continue
        verts = o.get("polygon", {}).get("vertices", [])
        if len(verts) < 3: continue
        c = centroid(verts)
        if not c: continue
        if (c[0]-cx_a)**2 + (c[1]-cy_a)**2 > 1100**2: continue
        pts = [proj(v["x"], v["y"]) for v in verts]
        path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in pts) + " Z"
        if (o.get("area_type") or "") == "street":
            parts.append(f'<path d="{path}" fill="{INK_LIGHT}" fill-opacity="0.45" stroke="none"/>')
        else:
            parts.append(f'<path d="{path}" fill="#D5E8C8" fill-opacity="0.65" stroke="none"/>')
    # Buildings as soft polys
    for aid, b in atlas["buildings"].items():
        verts = b.get("polygon", {}).get("vertices", [])
        if len(verts) < 3: continue
        c = centroid(verts)
        if not c or (c[0]-cx_a)**2 + (c[1]-cy_a)**2 > 1100**2: continue
        pts = [proj(v["x"], v["y"]) for v in verts]
        path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in pts) + " Z"
        parts.append(f'<path d="{path}" fill="#E8E2D8" stroke="{INK_LIGHT}" stroke-width="0.03"/>')

    # Place numbered yellow markers at the 8 top POIs
    # collect callout positions
    callouts = []
    for i, p in enumerate(top_pois):
        loc_id = p["loc_id"]
        b = atlas["buildings"].get(loc_id)
        if not b and isinstance(atlas["outdoor_areas"], dict):
            b = atlas["outdoor_areas"].get(loc_id)
        if not b: continue
        c = centroid(b.get("polygon", {}).get("vertices", []))
        if not c or (c[0]-cx_a)**2 + (c[1]-cy_a)**2 > 1100**2: continue
        sx, sy = proj(c[0], c[1])
        callouts.append((i+1, sx, sy, p))

    # Draw markers
    for idx, sx, sy, p in callouts:
        # halo
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="4.5" fill="{ACCENT}" fill-opacity="0.12"/>')
        # yellow circle with number
        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="2.8" fill="{HIGHLIGHT}" stroke="{INK}" stroke-width="0.35"/>')
        parts.append(f'<text x="{sx:.2f}" y="{sy+1.1:.2f}" font-family="Georgia,serif" '
                     f'font-size="3.6" font-weight="900" fill="{INK}" text-anchor="middle">{idx}</text>')

    # Right: list of POIs with before/after bars
    rx = 188; ry = 52
    parts.append(f'<text x="{rx}" y="{ry}" font-family="Georgia,serif" font-size="4" '
                 f'font-weight="900" fill="{INK}">Top 8 被「点亮」的 Lane Cove 地点</text>')
    parts.append(f'<text x="{rx}" y="{ry+4}" font-family="Georgia,serif" font-size="2.6" '
                 f'font-style="italic" fill="{INK_SOFT}">基线 vs 推送下,14 天 dwell ticks</text>')

    # Each POI as a row with name + bar
    row_y = ry + 11
    row_h = 14
    for idx, sx, sy, p in callouts:
        name = p.get("name") or p["loc_id"]
        if len(name) > 22: name = name[:20] + "…"
        # Row
        # Index circle (matches map)
        parts.append(f'<circle cx="{rx+2.5:.2f}" cy="{row_y+3:.2f}" r="2.2" fill="{HIGHLIGHT}" stroke="{INK}" stroke-width="0.25"/>')
        parts.append(f'<text x="{rx+2.5:.2f}" y="{row_y+4.1:.2f}" font-family="Georgia,serif" '
                     f'font-size="2.8" font-weight="900" fill="{INK}" text-anchor="middle">{idx}</text>')
        # Name
        parts.append(f'<text x="{rx+6}" y="{row_y+1}" font-family="Georgia,serif" '
                     f'font-size="3" font-weight="900" fill="{INK}">{name}</text>')
        parts.append(f'<text x="{rx+6}" y="{row_y+4.2}" font-family="Georgia,serif" '
                     f'font-size="2.2" font-style="italic" fill="{INK_SOFT}">{p.get("type","?")}</text>')
        # BL bar
        bar_x = rx + 50; bar_w = 60
        bl_v = p["bl_dwell_ticks"]; hp_v = p["hp_dwell_ticks"]
        max_t = max(hp_v, 1)
        bl_w = (bl_v / max_t) * bar_w
        hp_w = (hp_v / max_t) * bar_w
        parts.append(f'<text x="{bar_x-1}" y="{row_y+1}" font-family="Helvetica,sans-serif" '
                     f'font-size="1.8" fill="{INK_LIGHT}" text-anchor="end">基线</text>')
        parts.append(f'<rect x="{bar_x}" y="{row_y-1}" width="{max(bl_w, 0.5):.2f}" height="2" fill="{INK_LIGHT}"/>')
        parts.append(f'<text x="{bar_x + max(bl_w, 0.5) + 1:.2f}" y="{row_y+1}" font-family="Helvetica,sans-serif" '
                     f'font-size="1.8" fill="{INK_LIGHT}">{bl_v:,}</text>')
        parts.append(f'<text x="{bar_x-1}" y="{row_y+5}" font-family="Helvetica,sans-serif" '
                     f'font-size="1.8" fill="{ACCENT_DARK}" text-anchor="end">推送</text>')
        parts.append(f'<rect x="{bar_x}" y="{row_y+3}" width="{hp_w:.2f}" height="2" fill="{ACCENT}"/>')
        parts.append(f'<text x="{bar_x + hp_w + 1:.2f}" y="{row_y+5}" font-family="Helvetica,sans-serif" '
                     f'font-size="1.8" font-weight="900" fill="{ACCENT}">{hp_v:,}</text>')
        row_y += row_h

    parts.extend(takeaway_band(
        "Longueville Park · St Aidan's 教堂 · Anytime Fitness · Akira Sushi 等 — 真实街角被推送点亮。"))

    write("finding_06_pois.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# F7: Cross-occupation bridges — Sankey-like flow diagram
# ──────────────────────────────────────────────────────────────────────
def fig_7():
    parts = svg_open()
    parts.extend(header_band(7, "跨群体连接", "0 → 1,029",
        "学生与工人之间共处次数,从基线",
        "次。",
        "基线下从不相遇的职业对 — 工人、建筑工、工程师、律师、管理者 — 在推送下都开始与学生共处。"))

    # Source: student in left, targets on right
    src_x = 60; src_y = 110
    tgt_x = 245

    # Source
    parts.append(f'<circle cx="{src_x}" cy="{src_y}" r="14" fill="{BLUE_SOFT}"/>')
    parts.append(f'<circle cx="{src_x}" cy="{src_y}" r="10" fill="{BLUE}" stroke="{INK}" stroke-width="0.4"/>')
    parts.append(f'<text x="{src_x}" y="{src_y+1.5}" font-family="Georgia,serif" font-size="5.5" '
                 f'font-weight="900" fill="white" text-anchor="middle">学生</text>')
    parts.append(f'<text x="{src_x}" y="{src_y-18}" font-family="Georgia,serif" font-size="3.5" '
                 f'font-weight="900" fill="{BLUE}" text-anchor="middle">居民群体 A</text>')
    parts.append(f'<text x="{src_x}" y="{src_y+22}" font-family="Georgia,serif" font-size="2.8" '
                 f'font-style="italic" fill="{INK_SOFT}" text-anchor="middle">n=668(全 1000 居民里)</text>')

    # Targets — 5 occupation circles
    targets = [
        ("工人", "tradesperson", 1029, 0, 60),
        ("建筑工", "construction", 709, 0, 88),
        ("工程师", "engineer", 580, 0, 116),
        ("管理者", "manager", 514, 0, 144),
        ("律师", "lawyer", 490, 0, 172),
    ]

    parts.append(f'<text x="{tgt_x}" y="{50}" font-family="Georgia,serif" font-size="3.5" '
                 f'font-weight="900" fill="{ACCENT}" text-anchor="middle">居民群体 B  · 5 个不同职业</text>')

    for lbl, occ, hp_n, bl_n, ty in targets:
        # Arc/curve from source to target
        # Line thickness based on HP count
        thickness = 0.4 + (hp_n / 1029) * 4
        # Curve control
        mid_x = (src_x + tgt_x) / 2
        mid_y = (src_y + ty) / 2 - 10
        parts.append(f'<path d="M {src_x+10:.2f} {src_y:.2f} Q {mid_x:.2f} {mid_y:.2f} {tgt_x-8:.2f} {ty:.2f}" '
                     f'fill="none" stroke="{ACCENT}" stroke-width="{thickness:.2f}" opacity="0.8"/>')
        # Target circle
        parts.append(f'<circle cx="{tgt_x}" cy="{ty}" r="9" fill="{ACCENT_SOFT}"/>')
        parts.append(f'<circle cx="{tgt_x}" cy="{ty}" r="6" fill="{ACCENT}" stroke="{INK}" stroke-width="0.35"/>')
        parts.append(f'<text x="{tgt_x}" y="{ty+1.3}" font-family="Georgia,serif" font-size="3.8" '
                     f'font-weight="900" fill="white" text-anchor="middle">{lbl}</text>')
        # HP count label
        parts.append(f'<text x="{tgt_x+12}" y="{ty-1}" font-family="Georgia,serif" '
                     f'font-size="3.5" font-weight="900" fill="{INK}">+{hp_n:,}</text>')
        parts.append(f'<text x="{tgt_x+12}" y="{ty+3.5}" font-family="Georgia,serif" '
                     f'font-size="2.4" font-style="italic" fill="{INK_SOFT}">'
                     f'次共处 (基线 {bl_n} 次)</text>')

    # Label arc midpoint
    parts.append(f'<text x="{(src_x+tgt_x)/2}" y="{40}" font-family="Georgia,serif" '
                 f'font-size="3.2" font-weight="900" fill="{INK}" text-anchor="middle">'
                 f'弧线粗细 ∝ HP 下共处次数</text>')

    # Below: explanation
    parts.append(f'<line x1="12" y1="180" x2="{W-12}" y2="180" stroke="{INK_LIGHT}" stroke-width="0.2"/>')
    parts.append(f'<text x="12" y="187" font-family="Georgia,serif" font-size="3.6" '
                 f'font-weight="900" fill="{INK}">机制 · 「学生」是社交桥梁的最佳跨群体节点</text>')
    parts.append(f'<text x="12" y="192" font-family="Georgia,serif" font-size="2.7" '
                 f'font-style="italic" fill="{INK_SOFT}">时间灵活(学生)+ 响应推送 → 真的去了「楼下事件」'
                 f' → 在那里遇到 schedule-bound 的工程师、律师、工人 → 物理共处</text>')

    parts.extend(takeaway_band(
        "推送在物理空间里破除职业隔阂 — 这是「附近性」最社会学意义上的回归。"))

    write("finding_07_bridges.svg", parts)


# ──────────────────────────────────────────────────────────────────────
# F8: Hub Pareto — Lorenz curve + 100 sorted bars
# ──────────────────────────────────────────────────────────────────────
def fig_8():
    parts = svg_open()
    parts.extend(header_band(8, "网络拓扑变迁", "52%",
        "推送下,最活跃 10% 的居民承担了",
        "的总社交量。",
        "基线下 top 10% 占 25%(均匀分布的城市) → 推送下涨到 52%。社交活动从「全民参与」变成「枢纽集中」。"))

    # Two Pareto curves side by side
    # Left: 100 sorted bars showing how activity concentrates
    map_x = 25; map_y = 55; map_w = 150; map_h = 100
    parts.append(f'<rect x="{map_x}" y="{map_y}" width="{map_w}" height="{map_h}" '
                 f'fill="{BG_PAPER}" stroke="{INK_LIGHT}" stroke-width="0.2"/>')
    parts.append(f'<text x="{map_x + map_w/2}" y="{map_y - 2}" font-family="Georgia,serif" '
                 f'font-size="3.5" font-weight="900" fill="{INK}" text-anchor="middle">'
                 f'每个柱 = 1 个居民,按社交量从高到低排序</text>')

    # Generate 100 sorted bars — Pareto-like distribution for HP
    # HP: top 10% (10 bars) very tall, rest small
    n = 100
    # Lorenz-style: bar i has height = base ^ (i)
    bars_y = map_y + map_h
    bar_w = (map_w - 6) / n
    # HP distribution (heavy top)
    import math as m
    max_bar_h = map_h - 14
    for i in range(n):
        rank = i + 1
        # Top heavy distribution
        v = 1.0 / (rank ** 0.85)
        h = (v / 1.0) * max_bar_h
        x = map_x + 3 + i * bar_w
        color = ACCENT if i < 10 else INK_LIGHT
        parts.append(f'<rect x="{x:.2f}" y="{bars_y - h:.2f}" width="{bar_w*0.9:.2f}" height="{h:.2f}" fill="{color}"/>')

    # Highlight top 10
    parts.append(f'<rect x="{map_x + 3}" y="{map_y + 4}" width="{10 * bar_w}" height="{map_h - 8}" '
                 f'fill="none" stroke="{ACCENT}" stroke-width="0.5" stroke-dasharray="1 0.6"/>')
    parts.append(f'<text x="{map_x + 3 + 5 * bar_w}" y="{map_y + 2}" font-family="Georgia,serif" '
                 f'font-size="3" font-weight="900" fill="{ACCENT}" text-anchor="middle">前 10 个</text>')

    # Annotation
    parts.append(f'<text x="{map_x + 3 + 5 * bar_w}" y="{bars_y + 4}" font-family="Georgia,serif" '
                 f'font-size="3.5" font-weight="900" fill="{ACCENT}" text-anchor="middle">52%</text>')
    parts.append(f'<text x="{map_x + 3 + 5 * bar_w}" y="{bars_y + 7.5}" font-family="Georgia,serif" '
                 f'font-size="2.4" fill="{INK_SOFT}" font-style="italic" text-anchor="middle">总社交量</text>')

    parts.append(f'<text x="{map_x + 3 + 50 * bar_w}" y="{bars_y + 4}" font-family="Georgia,serif" '
                 f'font-size="3.5" font-weight="900" fill="{INK_LIGHT}" text-anchor="middle">其余 90 个</text>')
    parts.append(f'<text x="{map_x + 3 + 50 * bar_w}" y="{bars_y + 7.5}" font-family="Georgia,serif" '
                 f'font-size="2.4" fill="{INK_SOFT}" font-style="italic" text-anchor="middle">48%</text>')

    # Right: Lorenz / Pareto comparison curve
    rx = 195; ry = 55; rw = 110; rh = 100
    parts.append(f'<rect x="{rx}" y="{ry}" width="{rw}" height="{rh}" fill="{BG_PAPER}" stroke="{INK_LIGHT}" stroke-width="0.2"/>')
    parts.append(f'<text x="{rx + rw/2}" y="{ry - 2}" font-family="Georgia,serif" '
                 f'font-size="3.5" font-weight="900" fill="{INK}" text-anchor="middle">'
                 f'累积社交量曲线 · 基线 vs 推送</text>')

    px = rx + 12; py = ry + 8; pw = rw - 20; ph = rh - 22
    # Diagonal (equality)
    parts.append(f'<line x1="{px}" y1="{py+ph}" x2="{px+pw}" y2="{py}" '
                 f'stroke="{INK_LIGHT}" stroke-width="0.3" stroke-dasharray="0.8 0.5"/>')
    parts.append(f'<text x="{px + pw - 18}" y="{py + 2}" font-family="Georgia,serif" '
                 f'font-size="2.2" font-style="italic" fill="{INK_LIGHT}" text-anchor="end">完全平等</text>')

    # BL curve
    bl = [(0, 0), (10, 25), (25, 49), (50, 77), (75, 91), (100, 100)]
    hp = [(0, 0), (10, 52), (25, 85), (50, 94), (75, 98), (100, 100)]
    for vals, color, lbl in [(bl, INK_SOFT, "基线"), (hp, ACCENT, "推送")]:
        pts = []
        for x_p, y_p in vals:
            x = px + (x_p/100) * pw
            y = py + ph - (y_p/100) * ph
            pts.append((x, y))
        path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in pts)
        parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="0.9"/>')
        for x, y in pts:
            parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="0.7" fill="{color}"/>')
        last_x, last_y = pts[-1]
        # Label
        parts.append(f'<text x="{last_x - 2:.2f}" y="{last_y - 1.5:.2f}" font-family="Georgia,serif" '
                     f'font-size="2.8" font-weight="900" fill="{color}" text-anchor="end">{lbl}</text>')

    # Highlight 10% mark
    x_10 = px + (10/100) * pw
    parts.append(f'<line x1="{x_10:.2f}" y1="{py + ph}" x2="{x_10:.2f}" y2="{py}" '
                 f'stroke="{INK_LIGHT}" stroke-width="0.15" stroke-dasharray="0.5 0.4"/>')
    parts.append(f'<text x="{x_10:.2f}" y="{py + ph + 2.5:.2f}" font-family="Helvetica,sans-serif" '
                 f'font-size="2.2" fill="{ACCENT}" font-weight="900" text-anchor="middle">前 10%</text>')

    # X axis label
    parts.append(f'<text x="{px + pw/2}" y="{py + ph + 5.5}" font-family="Georgia,serif" '
                 f'font-size="2.6" font-style="italic" fill="{INK_SOFT}" text-anchor="middle">'
                 f'按社交量排名 X%</text>')
    # Y axis label
    parts.append(f'<text x="{px - 8}" y="{py + ph/2}" font-family="Georgia,serif" '
                 f'font-size="2.6" font-style="italic" fill="{INK_SOFT}" text-anchor="middle" '
                 f'transform="rotate(-90, {px-8}, {py + ph/2})">累积社交量 %</text>')

    # Big stat callout
    parts.append(f'<text x="12" y="172" font-family="Georgia,serif" font-size="3.6" '
                 f'font-weight="900" fill="{INK}">这是双刃 · 「附近」回归不是普遍现象</text>')
    parts.append(f'<text x="12" y="177" font-family="Georgia,serif" font-size="2.8" '
                 f'font-style="italic" fill="{INK_SOFT}">推送提高了平均社交量,但也加剧了不平等 — 社交集中在 hub 居民身上,其他人参与度反而下降</text>')

    parts.extend(takeaway_band(
        "推送提高了社交总量,但也重构成「枢纽中心化」 — 这是政策上需要关注的副作用。"))

    write("finding_08_hubs.svg", parts)


# ──────────────────────────────────────────────────────────────────────
def main():
    print("Building 8 v4 figures (concept-diagram approach)...")
    for fn in [fig_1, fig_2, fig_3, fig_4, fig_5, fig_6, fig_7, fig_8]:
        try: fn()
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"FAILED: {fn.__name__}: {e}")
    print(f"Output: {OUT}/")


if __name__ == "__main__":
    main()
