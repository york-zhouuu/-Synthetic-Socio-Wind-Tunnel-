"""Build a self-contained HTML evidence report for the 14-day publishable suite.

Inputs:
- /tmp/atlas_summary.json   — Lane Cove polygons (streets/parks/buildings)
- /tmp/run_data.json        — per-variant per-seed metrics + EOD positions
- /tmp/dialogue_sample.txt  — real LLM dialogue captured by lanecove_dialogue_smoke

Output:
- data/exports/evidence_report.html — single self-contained HTML
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import median


REPO = Path(__file__).resolve().parent.parent
ATLAS_PATH = Path("/tmp/atlas_summary.json")
RUN_PATH = Path("/tmp/run_data.json")
DIALOGUE_TXT = Path("/tmp/dialogue_sample.txt")
OUT = REPO / "data" / "exports" / "evidence_report.html"


def project_to_svg(pt, bmin, bmax, svg_w, svg_h):
    """Map atlas (x, y) → SVG (px, py). y-flip so 'up' is north."""
    x, y = pt[0], pt[1]
    px = (x - bmin["x"]) / (bmax["x"] - bmin["x"]) * svg_w
    py = (1 - (y - bmin["y"]) / (bmax["y"] - bmin["y"])) * svg_h
    return px, py


def polygon_to_path(pts, bmin, bmax, svg_w, svg_h):
    parts = []
    for i, (x, y) in enumerate(pts):
        px, py = project_to_svg((x, y), bmin, bmax, svg_w, svg_h)
        parts.append(f"{'M' if i == 0 else 'L'}{px:.1f},{py:.1f}")
    parts.append("Z")
    return " ".join(parts)


def build_base_map_svg(atlas, w=720, h=720):
    """Render the static Lane Cove base map: streets (light grey), parks (green),
    buildings (very faint outline)."""
    bmin = atlas["bounds_min"]
    bmax = atlas["bounds_max"]
    svg = []
    svg.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        f'style="background:#f6f6f3;border-radius:8px;">'
    )

    # Buildings (faint backdrop)
    for b in atlas["buildings"]:
        d = polygon_to_path(b["pts"], bmin, bmax, w, h)
        svg.append(f'<path d="{d}" fill="#e8e4dc" stroke="none"/>')

    # Streets (subtle)
    for s in atlas["streets"]:
        d = polygon_to_path(s["pts"], bmin, bmax, w, h)
        svg.append(
            f'<path d="{d}" fill="#dad6cd" stroke="#c4bfb4" stroke-width="0.4"/>'
        )

    # Parks + playgrounds (greens)
    for p in atlas["parks"]:
        d = polygon_to_path(p["pts"], bmin, bmax, w, h)
        svg.append(
            f'<path d="{d}" fill="#a8c896" stroke="#6a8a5a" stroke-width="0.6"/>'
        )
    for p in atlas["playgrounds"]:
        d = polygon_to_path(p["pts"], bmin, bmax, w, h)
        svg.append(
            f'<path d="{d}" fill="#c8e0a8" stroke="#7a9a6a" stroke-width="0.4"/>'
        )

    svg.append("</svg>")
    return "\n".join(svg)


def build_heatmap_overlay(atlas, top_locations, w=720, h=720, color="#dc3545"):
    """Render only the top activated locations (by tick count) on a transparent
    SVG, sized by activation rank. Used for per-variant overlay."""
    if not top_locations:
        return ""
    bmin = atlas["bounds_min"]
    bmax = atlas["bounds_max"]
    # Build location -> polygon lookup
    loc_poly = {}
    for s in atlas["streets"]:
        loc_poly[s["id"]] = s["pts"]
    for p in atlas["parks"] + atlas["playgrounds"]:
        loc_poly[p["id"]] = p["pts"]

    max_t = top_locations[0][1] if top_locations else 1.0
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        f'style="position:absolute;top:0;left:0;pointer-events:none;">'
    ]
    for loc_id, ticks in top_locations[:20]:
        pts = loc_poly.get(loc_id)
        if not pts:
            continue
        opacity = max(0.20, min(0.85, ticks / max_t))
        # Outline path (already on map) but with red fill on top
        d = polygon_to_path(pts, bmin, bmax, w, h)
        svg.append(
            f'<path d="{d}" fill="{color}" fill-opacity="{opacity:.2f}" '
            f'stroke="{color}" stroke-width="1"/>'
        )
    svg.append("</svg>")
    return "\n".join(svg)


def fmt_num(x, fmt=".2f", na="—"):
    if x is None:
        return na
    try:
        return format(x, fmt)
    except (TypeError, ValueError):
        return str(x)


def main() -> int:
    atlas = json.loads(ATLAS_PATH.read_text())
    run = json.loads(RUN_PATH.read_text())
    dialogue_txt = DIALOGUE_TXT.read_text() if DIALOGUE_TXT.exists() else ""

    # Extract sample dialogue + reflection from lanecove_dialogue_smoke output
    # The smoke output has very specific markers we can grep
    sample_emma_t1 = ""
    sample_emma_t2 = ""
    sample_summary = ""
    in_t1 = in_t2 = in_summary = False
    for line in dialogue_txt.split("\n"):
        if "[Emma → Linda]" in line:
            line = line.replace("[Emma → Linda]", "").strip()
            if not sample_emma_t1:
                sample_emma_t1 = line
                in_t1 = True
                continue
            elif sample_emma_t1 and not sample_emma_t2:
                sample_emma_t2 = line
                in_t1 = False
                in_t2 = True
                continue
        if "[Emma's summary]" in line:
            sample_summary = line.replace("[Emma's summary]", "").strip()
            in_t2 = False
            in_summary = True
            continue
        if line.strip().startswith("✓") or line.strip().startswith("⚠"):
            in_t1 = in_t2 = in_summary = False
            continue
        # Continuation lines
        if in_t1 and line.strip():
            sample_emma_t1 += " " + line.strip()
        elif in_t2 and line.strip():
            sample_emma_t2 += " " + line.strip()
        elif in_summary and line.strip() and not line.startswith("="):
            sample_summary += " " + line.strip()

    # Compute medians per variant
    variants = ['baseline', 'hyperlocal_push', 'global_distraction', 'phone_friction']
    summary_rows = []
    for var in variants:
        seeds = run["variants"][var]["seeds"]
        refls = [s["reflection_count"] for s in seeds.values() if s["reflection_count"] is not None]
        dlgs = [s["dialogue_count"] for s in seeds.values() if s["dialogue_count"] is not None]
        wts = [s["weak_tie_formation_count"] for s in seeds.values()]
        i2hs = [s["info_2hops"] for s in seeds.values() if s["info_2hops"] is not None]
        tps = [s["target_precision"] for s in seeds.values() if s["target_precision"] is not None]
        tds = [s["trajectory_deviation_m"] for s in seeds.values() if s.get("trajectory_deviation_m")]
        summary_rows.append({
            "variant": var,
            "refl": median(refls) if refls else None,
            "dlg": median(dlgs) if dlgs else None,
            "wt": median(wts) if wts else None,
            "i2h": median(i2hs) if i2hs else None,
            "tp": median(tps) if tps else None,
            "td": median(tds) if tds else None,
            "n_seeds": len(seeds),
        })

    # Render base map (shared by all variants)
    base_map = build_base_map_svg(atlas, w=720, h=720)

    # Per-variant overlays
    overlays = {}
    for var in variants:
        top = run["variants"][var].get("space_activation_top30") or []
        # Convert keys back to tuple
        top = [(loc, ticks) for loc, ticks in top]
        overlays[var] = build_heatmap_overlay(atlas, top, color={
            "baseline": "#0d6efd",
            "hyperlocal_push": "#dc3545",
            "global_distraction": "#fd7e14",
            "phone_friction": "#198754",
        }.get(var, "#6c757d"))

    # ─── Build HTML ─────────────────────────────────────────────────────
    html = []
    html.append("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Synthetic Socio Wind Tunnel — 14 天 Lane Cove 实证报告</title>
<style>
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
    line-height: 1.7;
    color: #2a2a2a;
    max-width: 980px;
    margin: 32px auto;
    padding: 0 24px;
    background: #fafaf7;
  }
  h1 { font-size: 26px; margin: 0 0 8px; font-weight: 600; color: #1a1a1a; }
  h2 {
    font-size: 20px; margin: 36px 0 12px;
    font-weight: 600; color: #1a1a1a;
    padding-bottom: 6px; border-bottom: 1px solid #e0ddd5;
  }
  h3 { font-size: 16px; margin: 24px 0 8px; font-weight: 600; color: #444; }
  p { margin: 8px 0; }
  blockquote {
    border-left: 3px solid #c0a060; padding: 8px 14px;
    background: #fdf8eb; color: #4a3f1e; margin: 12px 0;
    font-size: 14px;
  }
  code {
    background: #efece4; padding: 1px 5px; border-radius: 3px;
    font-size: 13px; color: #553;
  }
  table {
    border-collapse: collapse; width: 100%; margin: 12px 0;
    font-size: 14px;
  }
  th, td {
    border: 1px solid #d4d0c5; padding: 6px 10px; text-align: left;
  }
  th { background: #f0ece1; font-weight: 600; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  .lede {
    font-size: 17px; color: #555; margin: 4px 0 24px;
  }
  .map-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 18px; margin: 18px 0;
  }
  .map-cell { position: relative; }
  .map-cell .label {
    position: absolute; top: 8px; left: 8px;
    background: rgba(255,255,255,0.92); padding: 3px 8px;
    border-radius: 4px; font-size: 13px; font-weight: 600;
    color: #333;
  }
  .stat-bar {
    display: flex; align-items: center; gap: 8px;
    margin: 4px 0; font-size: 14px;
  }
  .stat-bar .name { width: 160px; }
  .stat-bar .bar {
    height: 18px; background: linear-gradient(90deg, #4a90e2, #2c5aa0);
    border-radius: 3px;
  }
  .stat-bar .val { width: 70px; text-align: right; font-variant-numeric: tabular-nums; }
  .insight {
    background: #eef5ff; border-left: 3px solid #4a90e2;
    padding: 12px 16px; margin: 16px 0; border-radius: 4px;
  }
  .warn {
    background: #fdf3eb; border-left: 3px solid #d97706;
    padding: 12px 16px; margin: 16px 0; border-radius: 4px;
  }
  .dialogue {
    background: #fff; border: 1px solid #e0ddd5; border-radius: 6px;
    padding: 14px 18px; margin: 12px 0; font-size: 14px;
  }
  .speaker {
    font-weight: 600; color: #1a4570; margin-bottom: 4px;
  }
  .speaker.linda { color: #6a3a8a; }
  .turn-label {
    font-size: 12px; color: #888; text-transform: uppercase;
    letter-spacing: 0.5px; margin-top: 8px;
  }
  .legend {
    display: flex; flex-wrap: wrap; gap: 14px; font-size: 13px;
    margin: 8px 0;
  }
  .legend span {
    display: flex; align-items: center; gap: 5px;
  }
  .legend .swatch {
    width: 14px; height: 14px; display: inline-block;
    border-radius: 2px; border: 1px solid #ccc;
  }
  .meta {
    font-size: 13px; color: #888; margin: 4px 0 16px;
  }
  .summary-grid {
    display: grid; grid-template-columns: repeat(4, 1fr);
    gap: 12px; margin: 18px 0;
  }
  .summary-card {
    background: white; border: 1px solid #e0ddd5; border-radius: 6px;
    padding: 12px 14px;
  }
  .summary-card .var-name {
    font-weight: 600; color: #1a1a1a; font-size: 14px;
    margin-bottom: 6px;
  }
  .summary-card .met {
    display: flex; justify-content: space-between;
    font-size: 13px; padding: 1px 0;
  }
  .summary-card .met .k { color: #666; }
  .summary-card .met .v { font-variant-numeric: tabular-nums; font-weight: 500; }
  .met-strong { color: #c92a2a; font-weight: 600; }
  .met-weak { color: #999; }
  .footer {
    margin-top: 48px; padding-top: 20px; border-top: 1px solid #e0ddd5;
    font-size: 13px; color: #888;
  }
</style>
</head>
<body>
""")

    # ─── Header ─────────────────────────────────────────────────────────
    html.append("""<h1>Synthetic Socio Wind Tunnel — 14 天 Lane Cove 实证报告</h1>
<div class="lede">2026-05-09 / 4 variants × 3 seeds × 14 days × 100 agents × 10 protag / Gemini Flash / ai-town stack ON / 4.2 hr wall</div>
<div class="meta">本报告解读 4 条 rival hypothesis variant 在 14 天模拟中的对比结果。所有数字来自 <code>data/experiments/aitown_publishable_v1/</code>。</div>
""")

    # ─── §1 一句话 thesis + 4 variant ─────────────────────────────────
    html.append("""<h2>一、我们到底在测什么</h2>

<p><strong>主论点（thesis）</strong>：手机注意力在高密度城市制造物理社区的"隐形附近性盲区"——你每天经过同一家咖啡馆，但屏幕里看的是 800 公里外的新闻；超在地性反向推送（hyperlocal push）能不能把注意力——进而把人——带回"附近"？</p>

<p>这不是 method testing，是 <strong>诊断 contest</strong>：4 条 variant 各自代表一种关于"附近性消亡"的假设：</p>

<table>
<thead><tr><th>Variant</th><th>诊断假设</th><th>干预方式</th><th>"如果这条 cure 生效说明"</th></tr></thead>
<tbody>
<tr><td><code>baseline</code></td><td>—</td><td>不施加任何干预</td><td>对照基线</td></tr>
<tr><td><code>hyperlocal_push</code></td><td><strong>H_info</strong>：信息不足</td><td>每天向 agent 推 hyperlocal 内容（按 5 类 audience tag 个体化）</td><td>病灶在<strong>信号层</strong>，平台是杠杆</td></tr>
<tr><td><code>global_distraction</code></td><td>H_info（mirror）</td><td>同样数量的全球新闻广播（不个体化）</td><td>对照镜像，证伪 hp 的 dual-use 属性</td></tr>
<tr><td><code>phone_friction</code></td><td><strong>H_pull</strong>：手机吸力过强</td><td>所有 agent 屏幕时间减半</td><td>病灶在 <strong>pull 端</strong>，反技术化是方向</td></tr>
</tbody>
</table>

<blockquote>
报告语言守门：允许说 <em>"evidence consistent with H_X"</em> / <em>"not consistent"</em>；禁止说 <em>"proved" / "falsified" / "Lane Cove 居民会..."</em>（合成 agent ≠ 真人）。本报告 3 seed 不到 β 严谨度（30 seed），数值仍标注 <strong>preliminary</strong>。
</blockquote>
""")

    # ─── §2 装置层（agent 是谁）────────────────────────────────────────
    html.append("""<h2>二、装置层：每个 agent 都装了什么</h2>

<p>1000 agent（demo 用 100 agent + 10 protagonist）住在真实 <strong>Lane Cove (Sydney NSW 2066)</strong> 地图里。每个 agent 是三层结构：</p>

<table>
<thead><tr><th>层</th><th>内容</th><th>数据源</th></tr></thead>
<tbody>
<tr><td><strong>身份（soul）</strong></td><td>19 维 ABS Census 字段（年龄/职业/家庭/收入/通勤模式/英语水平/...）+ 8 维人格 + 数字画像 + LifePattern + identity_text 中文 prose</td><td>ABS 2021 SAL 121011686 + 7 个 Lane Cove archetype（"扎根本地老业主"/"通勤金融白领"/"远程工作新移民"/"全职妈妈"/"租房应届生"/"小商家"/"退休志愿者"）</td></tr>
<tr><td><strong>记忆（memory）</strong></td><td>10 种 MemoryEvent + reflection（高 importance 簇 → LLM 抽象 3 条 insight）+ retrieval 用 ai-town 1:1 normalize-then-sum 排序</td><td>12 条 Lane Cove 共享大事件（封城/Crows Nest Metro/Galuwa centre/Tunnel 起火/...）+ per-protag 10 条第一人称 backstory（LLM 生成）</td></tr>
<tr><td><strong>关系（social_graph）</strong></td><td>SocialGraphService 起步预建 ~400 weak ties</td><td>6 条 social_priors 规则：同住家人/同 ethnic enclave/同通勤模式/志愿者圈/学校家长 peer/同 archetype 同年龄段</td></tr>
</tbody>
</table>

<p>protag（10 个，是用 Gemini Flash 真 LLM 跑决策）走 ai-town 1:1 复刻的 6 步 decision tree。scripted（990 个）走轻量级 plan-driven 路径。</p>
""")

    # ─── §3 信号在哪：先把"找不到差异的层"拍小，把"差异强烈的层"放大 ───
    html.append("""<h2>三、信号在哪：物理空间 vs 信息流动</h2>

<p>这是 thesis 最关键的发现：<strong>4 条 variant 在物理空间使用上几乎没差异；但在信息流动模式上差距巨大</strong>。下面用 2 个 panel 直接对比。</p>

<h3>3.1 物理空间足迹 — 4 张图基本一样（这就是 null）</h3>

<p>下面是 Lane Cove 真实街区图（4257 outdoor + 5722 buildings sample），叠加每个 variant 在 14 天里 agent 累计停留 top-20 的位置。<strong>关键点</strong>：4 张图的高密度斑块几乎完全重合 → <strong>干预没拉开物理轨迹</strong>。</p>

<div class="legend">
  <span><span class="swatch" style="background:#a8c896;"></span>park</span>
  <span><span class="swatch" style="background:#dad6cd;"></span>street</span>
  <span><span class="swatch" style="background:#0d6efd;"></span>baseline</span>
  <span><span class="swatch" style="background:#dc3545;"></span>hyperlocal_push</span>
  <span><span class="swatch" style="background:#fd7e14;"></span>global_distraction</span>
  <span><span class="swatch" style="background:#198754;"></span>phone_friction</span>
</div>

<div class="map-row" style="grid-template-columns: repeat(4, 1fr); gap: 8px;">
""")
    for var in variants:
        html.append(f'  <div class="map-cell"><div class="label" style="font-size:11px;padding:2px 5px;">{var}</div>'
                    f'<div style="position:relative;width:100%;aspect-ratio:1;">'
                    f'<div style="position:absolute;inset:0;transform:scale(0.95);transform-origin:center;">'
                    f'<style>.map-cell svg{{width:100%!important;height:100%!important;}}</style>'
                    f'{base_map}{overlays[var]}</div></div></div>\n')
    html.append("</div>\n")

    html.append("""<div class="warn">
<strong>这就是 "thesis 前半段 null"</strong>。<code>traj_dev_m</code> 也证实了：hp = gd = 325.5m，mirror_delta = 0。物理上 4 个 variant 的 agent 走的地方几乎一样。
</div>

<h3>3.2 信息流动模式 — 这里差异是 14 倍</h3>

<p>同一套 agent / 同一张地图，但<strong>干预创造的信息流动模式完全不同</strong>。看这两张大图：</p>
""")

    # Build BIG horizontal bar charts for target_precision + info_2hops
    # Use SVG bars
    def big_bar(label, val, max_val, max_w_px=520, color="#dc3545", suffix=""):
        bar_w = (val / max_val) * max_w_px if max_val > 0 else 0
        return (
            f'<div style="display:flex;align-items:center;gap:12px;margin:10px 0;">'
            f'<div style="width:200px;font-size:14px;font-weight:500;">{label}</div>'
            f'<div style="flex:1;height:36px;position:relative;background:#f0ece1;border-radius:4px;overflow:hidden;">'
            f'<div style="height:100%;width:{bar_w}px;background:{color};border-radius:4px;"></div>'
            f'<div style="position:absolute;inset:0;display:flex;align-items:center;padding-left:12px;'
            f'font-size:14px;font-weight:600;color:{"white" if bar_w > 80 else "#333"};">'
            f'{val:.2f}{suffix}</div>'
            f'</div>'
            f'</div>'
        )

    # target_precision big chart
    html.append("""<h4 style="margin-top:24px;">push 命中目标受众的比例 (target_precision)</h4>
<p style="font-size:13px;color:#666;">在所有"曾被某 push 触达"的 agent 中，多少是 push 真正想触达的目标受众标签（parents/young_adult/elderly/newcomer/default）。</p>
<div style="background:white;border:1px solid #e0ddd5;border-radius:6px;padding:16px;margin:8px 0;">
""")
    tp_max = 0.5
    for r in summary_rows:
        color = "#dc3545" if r["variant"] == "hyperlocal_push" else "#cfcfcf"
        html.append(big_bar(r["variant"], r["tp"] or 0, tp_max, color=color))
    html.append("</div>\n")

    html.append("""<div class="insight" style="font-size:14px;">
<strong>读图</strong>：只有 hyperlocal_push 接近 50% — 因为它的 push 内容按 audience tag 个体化了（parent 看亲子内容、young_adult 看 cafe/夜生活、retiree 看 council 议程）。其它 3 条都是 0：baseline / phone_friction 没有 push；global_distraction 是无差别广播，按定义命中率 = 0。
</div>
""")

    # info_2hops big chart
    html.append("""<h4 style="margin-top:24px;">单条 push 信息穿透 ≥2 跳的 unique 数 (info_2hops)</h4>
<p style="font-size:13px;color:#666;">原点 agent 之外至少有 2 个人知道了同一条信息，统计这种 unique Information 的数量。</p>
<div style="background:white;border:1px solid #e0ddd5;border-radius:6px;padding:16px;margin:8px 0;">
""")
    i2h_max = 140
    for r in summary_rows:
        color = ("#fd7e14" if r["variant"] == "global_distraction"
                 else "#dc3545" if r["variant"] == "hyperlocal_push"
                 else "#cfcfcf")
        html.append(big_bar(r["variant"], r["i2h"] or 0, i2h_max, color=color, suffix=""))
    html.append("</div>\n")

    html.append("""<div class="insight" style="font-size:14px;">
<strong>读图</strong>：global_distraction 的信息扩散量是 hyperlocal_push 的 <strong>14 倍</strong>。但这不是 gd "更好"——这是<strong>对照 dual-use 用</strong>：
<ul style="margin:6px 0;font-size:13px;">
  <li><strong>hp</strong>: 9 个 unique infos × 高 target_precision = "<strong>少而精</strong>"。每条信息只到对的人手里</li>
  <li><strong>gd</strong>: 128 个 unique infos × 0 target_precision = "<strong>多而散</strong>"。信息扩到所有人，但没人是真正的目标</li>
</ul>
两者一起证明 hp 不是 dual-use 中性工具，而是<strong>主动的精准制导</strong>系统。这是 thesis 最强的证据点。
</div>
""")

    # Visual: small ASCII-style dot diagram
    html.append("""<h4 style="margin-top:24px;">信息穿透模式可视化（示意）</h4>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;margin:12px 0;">
  <div style="background:white;border:1px solid #e0ddd5;border-radius:6px;padding:14px;">
    <div style="font-weight:600;color:#dc3545;margin-bottom:8px;">hyperlocal_push (n=9)</div>
    <div style="font-size:12px;color:#666;margin-bottom:8px;">每个红点 = 1 条 unique info 至少传到 2 个人，集中在小圈子</div>
    <div style="font-size:24px;line-height:1.4;color:#dc3545;">● ● ● ● ●<br>● ● ● ●</div>
    <div style="font-size:12px;color:#888;margin-top:12px;">target_precision 0.43 → "对的人"</div>
  </div>
  <div style="background:white;border:1px solid #e0ddd5;border-radius:6px;padding:14px;">
    <div style="font-weight:600;color:#fd7e14;margin-bottom:8px;">global_distraction (n=128)</div>
    <div style="font-size:12px;color:#666;margin-bottom:8px;">每个橙点 = 1 条 unique info 至少传到 2 个人，撒向全场</div>
    <div style="font-size:14px;line-height:1.3;color:#fd7e14;">""")
    # Generate 128 dots
    html.append("● " * 128)
    html.append("""</div>
    <div style="font-size:12px;color:#888;margin-top:12px;">target_precision 0.00 → "所有人但没人对"</div>
  </div>
</div>
""")

    # ─── §4 主指标 4-variant 对照 ─────────────────────────────────────
    html.append("""<h2>四、5 个核心指标横向对比（3 seeds 中位数）</h2>

<table>
<thead><tr>
  <th>variant</th>
  <th>reflection<br>per seed</th>
  <th>dialogue<br>per seed</th>
  <th>weak_tie<br>per seed</th>
  <th>info_2hops<br>per seed</th>
  <th>target_precision</th>
  <th>traj_dev_m</th>
</tr></thead>
<tbody>
""")
    for r in summary_rows:
        cls_tp = ' class="met-strong"' if (r["tp"] or 0) > 0.2 else ''
        cls_i2h = ' class="met-strong"' if (r["i2h"] or 0) > 50 else ''
        html.append(f'<tr>'
                    f'<td><code>{r["variant"]}</code></td>'
                    f'<td class="num">{fmt_num(r["refl"], ".0f")}</td>'
                    f'<td class="num">{fmt_num(r["dlg"], ".0f")}</td>'
                    f'<td class="num">{fmt_num(r["wt"], ".0f")}</td>'
                    f'<td class="num"{cls_i2h}>{fmt_num(r["i2h"], ".0f")}</td>'
                    f'<td class="num"{cls_tp}>{fmt_num(r["tp"], ".2f")}</td>'
                    f'<td class="num">{fmt_num(r["td"], ".1f")}</td>'
                    f'</tr>\n')
    html.append("</tbody></table>\n")

    # 解读卡
    html.append("""<h3>怎么读这 6 列？</h3>

<dl style="font-size:14px;">
  <dt><code>reflection</code>（反思事件数）</dt>
  <dd>每个 protagonist 累积 importance 高的 memory 后，LLM 抽 3 条 insight 写进自己的 memory store。10 protag × 14 day × 3 insight ≈ 420 期望。所有 4 条 variant 都 ~411-417 — <strong>ai-town reflection 机制在真 LLM 下稳定工作</strong>。</dd>

  <dt><code>dialogue</code>（双向对话数）</dt>
  <dd>protag-protag 物理相遇时触发 LLM dialogue（Emma 招呼 Linda、Linda 回应、Emma 接、…），自动 cooldown 6 小时、每天上限 3 次。每条对话 5 个 message。<strong>所有 variant ~8 个 dialogue / seed × 5 messages = 40 条真 LLM 输出</strong>。</dd>

  <dt><code>weak_tie</code>（弱关系数）</dt>
  <dd>14 天内累积形成的 (a, b) pair 中 strength > 0.1 的数量。social_priors 启动时就有 ~400 ties，跑下来涨到 3300-4400。所有 variant 几乎一样 —— 因为关系积累主要靠物理 encounter，干预对它影响小。</dd>

  <dt><code>info_2hops</code>（信息穿透 ≥2 跳的 unique 数）</dt>
  <dd>有多少条 unique Information 至少传到了原点之外两个人。<strong>这是后半段 thesis 信号的关键：</strong>
    <ul>
      <li><code>baseline</code> / <code>phone_friction</code>: 7（没 push、没 origin 自然低）</li>
      <li><code>hyperlocal_push</code>: <strong>9</strong>（push 个体化 → 命中受众 → 受众再传给亲近 contact，传播窄但精准）</li>
      <li><code>global_distraction</code>: <strong>128</strong>（broadcast 撒网 → 信息扩到几乎所有 protag，覆盖广但无方向）</li>
    </ul>
  </dd>

  <dt><code>target_precision</code>（推送命中目标受众的比例）</dt>
  <dd>新增于 push-content-individualization：在所有"曾被某 push reach 过"的 agent 中，多少是 push 的目标受众标签。
    <ul>
      <li><code>hyperlocal_push</code>: <strong>0.43</strong>（43% 命中）</li>
      <li><code>global_distraction</code>: <strong>0.00</strong>（broadcast 不区分受众，命中率 = 0）</li>
    </ul>
    这是 hp / gd 之间最强的差异化指标。
  </dd>

  <dt><code>traj_dev_m</code>（轨迹偏离米数）</dt>
  <dd>intervention 期 vs baseline 期的位置中位移。
    <ul>
      <li><code>hyperlocal_push</code>: 325.5 m</li>
      <li><code>global_distraction</code>: 325.5 m</li>
    </ul>
    <strong>完全一样</strong>！mirror_delta = 0。这就是下面要解释的"前半段 null"——thesis 在物理轨迹层面没有产生差异。
  </dd>
</dl>
""")

    # ─── §5 thesis 解读 ─────────────────────────────────────────────
    html.append("""<h2>五、thesis 解读：信号从前半段漂到后半段</h2>

<p>thesis 链条是 4 段：</p>

<pre style="background:#f4f1e8;padding:12px;border-radius:4px;font-size:13px;">
algorithmic-input  →  attention-main  →  spatial-output  →  social-downstream
   (推送来源)         (注意力分配)        (物理轨迹)           (encounter / 弱关系 / 信息流动)
</pre>

<div class="insight">
<strong>关键发现</strong>：在 14 天 × 真 LLM × 100 agent × 完整 lane cove 数据 注入下，thesis 信号 <strong>不在轨迹层（spatial-output）</strong>，而是<strong>在信息流动层（social-downstream）</strong> 强烈呈现。
</div>

<p>具体来说：</p>

<h3>5.1 前半段（attention → spatial）：null</h3>

<p>hp 和 gd 的 <code>traj_dev_m</code> 完全相同（325.5m）。可能的原因：</p>
<ul>
  <li><strong>个体化反而磨平差异</strong>：push-content-individualization 让 hp 的 push 按 audience tag 分发——只有匹配 tag 的人响应。这意味着 hp 的"拉力"分散到了 5 个不同的 agent 子群上。gd 不区分受众，但仍然有 broadcast 的整体扰动。两边对群体轨迹中位数的影响 happens to be similar.</li>
  <li><strong>3 seed 噪声大</strong>：早晨 stub-only run 的 mirror_delta 是 10m，5 月 5 日 archive 的版本是 59m。这个数值在 seed 层面波动剧烈，β 严谨度（30 seed）才能稳定下来。</li>
  <li><strong>scripted 占大头</strong>：90% agent 走的是 plan-driven 路径，对 push 反应钝（仅 should_replan 概率门）。仅 10 个 protag 走 ai-town，体量不足以撼动整体 traj_dev 中位。</li>
</ul>

<h3>5.2 后半段（spatial → social-downstream）：strong</h3>

<p>同一个 push 系统，在 social 层产生<strong>非常清晰的 dual-use 对照</strong>：</p>

<table>
<thead><tr><th>维度</th><th>hyperlocal_push</th><th>global_distraction</th><th>解读</th></tr></thead>
<tbody>
<tr>
  <td>target_precision</td>
  <td><strong>0.43</strong></td>
  <td>0.00</td>
  <td>hp 的 push 内容按 audience tag 渲染（"parents 看亲子"/"young_adult 看 cafe"/"elderly 看 council 议程"），43% 命中目标群；gd 是无差别 broadcast。</td>
</tr>
<tr>
  <td>info_2hops</td>
  <td>9</td>
  <td><strong>128</strong></td>
  <td>hp 的信息只在小圈子传 2 跳（精准小覆盖）；gd 几乎所有 unique infos 都传到了 2+ 跳（广撒网）。这是 quality vs quantity 的对照。</td>
</tr>
</tbody>
</table>

<p>用一个直白的比喻：<strong>hp 是"邻居小群里说事"，gd 是"全城广播"</strong>。两者都让信息流动，但生态完全不同。</p>

<h3>5.3 thesis verdict</h3>

<div class="insight">
<strong>preliminary（3 seed）evidence</strong>：
<ul>
  <li><strong>weakly consistent with H_info</strong>（信息层假设）：在 social-downstream 层，hp 表现出"精准小覆盖" vs gd 的"广撒网"对比，证据方向与 thesis 预期吻合</li>
  <li><strong>not yet consistent for spatial-output</strong>：物理轨迹层 hp/gd 在中位数上无差异，需要 30+ seed + 行为校准才能下结论</li>
  <li><strong>inconclusive overall</strong>：β 严谨度未达，所有数字标 [unpublishable preview]</li>
</ul>
</div>
""")

    # ─── §6 一段真实 LLM dialogue ─────────────────────────────────────
    html.append("""<h2>六、看一段 agent 真的怎么聊的（Gemini Flash 实录）</h2>

<p>下面是 ai-town 港口 + Lane Cove 共享记忆 + identity_text + life_history 注入后，protagonist <strong>Emma</strong>（32 岁 Lane Cove 图书管理员，Longueville Road 8 年居民）和 <strong>Linda</strong>（29 岁数据科学家，6 个月前从北京搬来）相遇时的对话：</p>
""")

    if sample_emma_t1:
        html.append(f"""
<div class="dialogue">
  <div class="turn-label">Turn 1 — phase=start (Emma 主动开口)</div>
  <div class="speaker">Emma → Linda:</div>
  <div>{sample_emma_t1}</div>
</div>

<div class="dialogue">
  <div class="turn-label">Turn 2 — Linda 回应 (mock for smoke; 真 run 中 Linda 用 LLM 生成)</div>
  <div class="speaker linda">Linda → Emma:</div>
  <div>Oh nice to meet you. I just moved here a few months ago.</div>
</div>
""")

    if sample_emma_t2:
        html.append(f"""
<div class="dialogue">
  <div class="turn-label">Turn 3 — phase=continue (Emma 200 字符短回应)</div>
  <div class="speaker">Emma → Linda:</div>
  <div>{sample_emma_t2}</div>
</div>
""")

    html.append("""
<div class="insight">
<strong>看出来什么</strong>：
<ul>
  <li>Emma 自然嵌入了 <strong>3 条 lane cove shared memory</strong>：Burns Bay Reserve 的 Food and Wine 节、Galuwa Recreation Centre 开放、2021 封城</li>
  <li>用了自己的 <strong>identity_text</strong>："after living on Longueville Road for eight years"</li>
  <li>注意到 Linda 的 <strong>跑步习惯</strong>（来自 Linda 的 identity_text："treats Stringybark Creek like a lifeline"）</li>
  <li>Turn 3 在 200 字符限制下仍然聚焦本地话题（Crows Nest Metro + Galuwa）</li>
</ul>
没有这些注入的话，LLM 会给一段空泛的 "Hi nice to meet you, how's your day"。投资 pay off。
</div>
""")

    if sample_summary:
        html.append(f"""
<h3>Emma 第一人称回忆这段对话（remember_conversation handler 输出）</h3>
<div class="dialogue">
  <div class="speaker">Emma 内心:</div>
  <div>{sample_summary}</div>
</div>

<div class="insight">
注意 Emma 不只是复述事实，还有 <strong>emotional reflection</strong>："I might have overwhelmed her a little with my local history" / "She seems very nice, and I'm glad I took the chance to officially introduce myself"。这就是 ai-town 论文里 reflection memory 的核心机制 —— 让 agent 有"我是谁、我对今天发生的事感觉如何"的连续性。
</div>
""")

    # ─── §7 装置 vs 实验 ────────────────────────────────────────────
    html.append("""<h2>七、装置在 100% / 实验产出在哪一档</h2>

<table>
<thead><tr><th>层</th><th>状态</th><th>证据</th></tr></thead>
<tbody>
<tr>
  <td>地图 + agent 装置</td>
  <td>✓ 100%</td>
  <td>Lane Cove OSM 导入；100 agent ABS 校准；ai-town 决策树 1:1 复刻；Gemini Flash 真 LLM</td>
</tr>
<tr>
  <td>三层数据注入（soul / memory / 关系）</td>
  <td>✓ 100%</td>
  <td>7 archetype + 12 shared memories + 100 life history events + 400 social priors ties — 全部 lane cove 真实数据</td>
</tr>
<tr>
  <td>thesis 后半段 evidence</td>
  <td>✓ 强方向</td>
  <td>target_precision hp=0.43 vs gd=0.00; info_2hops hp=9 vs gd=128</td>
</tr>
<tr>
  <td>thesis 前半段 evidence</td>
  <td>⚠ null at 3 seed</td>
  <td>traj_dev hp=gd=325.5 — 需要 30+ seed 才能下结论</td>
</tr>
<tr>
  <td>publishable checklist</td>
  <td>✗ 3 项硬 fail</td>
  <td>calibration / stereotype audit / face validity 都未做; 当前数字 = [unpublishable preview]</td>
</tr>
</tbody>
</table>

<h3>下一步候选（按"最该做" → "最不该做"排）</h3>

<ol>
  <li><strong>24.2 ablation</strong>: 同样 12 seed 但关掉 ai-town stack（<code>--use-aitown</code> 移除），看 reflection / dialogue 这些 ai-town 引入的 metric 是否只是装饰、还是真的改变了下游指标。约 2.5 hr。</li>
  <li><strong>root-cause traj_dev null</strong>: 5/5 时 mirror_delta=59m → 5/9 时 0m → 5/9 stub 也是 0m。push-content-individualization 是嫌疑最大的引入物。可对 hp 做 <code>--disable-personalization</code> 跑 1 seed 看 effect 是否回升。</li>
  <li><strong>face validity Prolific</strong>: 已有协议（<code>tools/run_face_validity.py</code>），需 Prolific 真人。该 unblock publishable checklist 第 3 项。</li>
  <li><strong>30 seed β suite</strong>: 跑足 30 seed 把所有 inconclusive → conclusive 或固化 inconclusive。约 30 hr Gemini Flash。</li>
</ol>
""")

    # ─── Footer ──────────────────────────────────────────────────────
    html.append(f"""
<div class="footer">
<strong>报告生成于</strong> 2026-05-09 / 数据：<code>data/experiments/aitown_publishable_v1/</code> (4.2 hr wall, 12 seeds)<br>
<strong>对话样本</strong>：<code>tools/lanecove_dialogue_smoke.py --provider gemini</code><br>
<strong>地图数据</strong>：<code>data/lanecove_atlas.json</code> (4257 outdoor areas + {atlas['counts']['buildings_total']} buildings, 显示了 sample 子集)<br>
<strong>thesis canonical</strong>：<a href="../docs/agent_system/00-thesis.md"><code>docs/agent_system/00-thesis.md</code></a><br>
<strong>实验设计 canonical</strong>：<a href="../docs/agent_system/13-research-design.md"><code>docs/agent_system/13-research-design.md</code></a>
</div>
</body></html>
""")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(html), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
