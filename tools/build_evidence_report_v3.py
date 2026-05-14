"""V3 evidence report — honest thesis verdict.

Framing fix: thesis 主信号在 spatial-output 层（trajectory / 空间激活度 /
encounter 密度）。target_precision / info_2hops 是 push 工艺指标，不是
thesis 信号。诚实陈述 hp 在 spatial 层 NULL or NEGATIVE。
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import median


REPO = Path(__file__).resolve().parent.parent
ATLAS = json.loads((Path("/tmp/atlas_summary.json")).read_text())
RUN = json.loads((Path("/tmp/run_data.json")).read_text())
SPATIAL = json.loads((Path("/tmp/spatial_signal.json")).read_text())
DIALOGUE = Path("/tmp/dialogue_sample.txt").read_text() if Path("/tmp/dialogue_sample.txt").exists() else ""

OUT = REPO / "data" / "exports" / "evidence_report.html"
VARIANTS = ['baseline', 'hyperlocal_push', 'global_distraction', 'phone_friction']


def project_to_svg(pt, bmin, bmax, w, h):
    px = (pt[0] - bmin["x"]) / (bmax["x"] - bmin["x"]) * w
    py = (1 - (pt[1] - bmin["y"]) / (bmax["y"] - bmin["y"])) * h
    return px, py


def polygon_to_path(pts, bmin, bmax, w, h):
    parts = []
    for i, (x, y) in enumerate(pts):
        px, py = project_to_svg((x, y), bmin, bmax, w, h)
        parts.append(f"{'M' if i == 0 else 'L'}{px:.1f},{py:.1f}")
    parts.append("Z")
    return " ".join(parts)


def build_base_map(atlas, w=600, h=600):
    bmin, bmax = atlas["bounds_min"], atlas["bounds_max"]
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
           f'width="{w}" height="{h}" style="background:#f6f6f3;border-radius:6px;">']
    for b in atlas["buildings"]:
        svg.append(f'<path d="{polygon_to_path(b["pts"], bmin, bmax, w, h)}" '
                   f'fill="#e8e4dc" stroke="none"/>')
    for s in atlas["streets"]:
        svg.append(f'<path d="{polygon_to_path(s["pts"], bmin, bmax, w, h)}" '
                   f'fill="#dad6cd" stroke="#c4bfb4" stroke-width="0.4"/>')
    for p in atlas["parks"] + atlas["playgrounds"]:
        svg.append(f'<path d="{polygon_to_path(p["pts"], bmin, bmax, w, h)}" '
                   f'fill="#a8c896" stroke="#6a8a5a" stroke-width="0.6"/>')
    svg.append("</svg>")
    return "\n".join(svg)


def build_overlay(atlas, top_locs, w=600, h=600, color="#dc3545"):
    if not top_locs: return ""
    bmin, bmax = atlas["bounds_min"], atlas["bounds_max"]
    loc_poly = {s["id"]: s["pts"] for s in atlas["streets"]}
    for p in atlas["parks"] + atlas["playgrounds"]:
        loc_poly[p["id"]] = p["pts"]
    max_t = top_locs[0][1] if top_locs else 1
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
           f'width="{w}" height="{h}" style="position:absolute;top:0;left:0;pointer-events:none;">']
    for loc, ticks in top_locs[:20]:
        pts = loc_poly.get(loc)
        if not pts: continue
        opacity = max(0.20, min(0.85, ticks / max_t))
        svg.append(f'<path d="{polygon_to_path(pts, bmin, bmax, w, h)}" '
                   f'fill="{color}" fill-opacity="{opacity:.2f}" '
                   f'stroke="{color}" stroke-width="1"/>')
    svg.append("</svg>")
    return "\n".join(svg)


def big_bar(label, val, max_val, color, suffix="", precision=2, max_w=500, neutral=False):
    """Render a horizontal bar SVG."""
    bar_w = abs(val) / max_val * max_w if max_val > 0 else 0
    text_color = "white" if bar_w > 100 else "#333"
    return (
        f'<div style="display:flex;align-items:center;gap:10px;margin:8px 0;">'
        f'<div style="width:200px;font-size:14px;font-weight:500;font-family:monospace;">{label}</div>'
        f'<div style="flex:1;height:32px;position:relative;background:{("#f0ece1" if not neutral else "#fef0f0")};border-radius:3px;overflow:hidden;">'
        f'<div style="height:100%;width:{bar_w}px;background:{color};border-radius:3px;"></div>'
        f'<div style="position:absolute;inset:0;display:flex;align-items:center;padding-left:10px;'
        f'font-size:14px;font-weight:600;color:{text_color};">'
        f'{val:.{precision}f}{suffix}</div></div></div>'
    )


def fmt(x, p=".2f"):
    if x is None: return "—"
    try: return format(x, p)
    except: return str(x)


def extract_dialogue_samples(txt):
    """Pull 2 Emma turns + summary out of lanecove_dialogue_smoke output."""
    t1, t2, summary = "", "", ""
    in_t1 = in_t2 = in_summary = False
    for line in txt.split("\n"):
        if "[Emma → Linda]" in line:
            line = line.replace("[Emma → Linda]", "").strip()
            if not t1:
                t1 = line; in_t1 = True; continue
            elif t1 and not t2:
                t2 = line; in_t1 = False; in_t2 = True; continue
        if "[Emma's summary]" in line:
            summary = line.replace("[Emma's summary]", "").strip()
            in_t2 = False; in_summary = True; continue
        if line.strip().startswith("✓") or line.strip().startswith("⚠"):
            in_t1 = in_t2 = in_summary = False; continue
        if in_t1 and line.strip(): t1 += " " + line.strip()
        elif in_t2 and line.strip(): t2 += " " + line.strip()
        elif in_summary and line.strip() and not line.startswith("="):
            summary += " " + line.strip()
    return t1, t2, summary


def main() -> int:
    base_map = build_base_map(ATLAS, w=600, h=600)
    colors = {"baseline": "#0d6efd", "hyperlocal_push": "#dc3545",
              "global_distraction": "#fd7e14", "phone_friction": "#198754"}
    overlays = {var: build_overlay(ATLAS, RUN["variants"][var].get("space_activation_top30", []),
                                    w=600, h=600, color=colors[var])
                for var in VARIANTS}

    sample_t1, sample_t2, sample_summary = extract_dialogue_samples(DIALOGUE)

    # Build summary stats per variant (use SPATIAL median data)
    rows = []
    for var in VARIANTS:
        m = SPATIAL[var]["medians"]
        d = SPATIAL[var]["delta_vs_baseline"]
        # Get reflection / dialogue / target_precision from RUN data
        seeds = RUN["variants"][var]["seeds"]
        refl = median([s["reflection_count"] for s in seeds.values() if s.get("reflection_count")])
        dlg = median([s["dialogue_count"] for s in seeds.values() if s.get("dialogue_count") is not None])
        tps = [s["target_precision"] for s in seeds.values() if s.get("target_precision") is not None]
        i2hs = [s["info_2hops"] for s in seeds.values() if s.get("info_2hops") is not None]
        rows.append({
            "variant": var,
            "encs": m["encs_total"],
            "encs_pct": d["encs_total_pct"],
            "pairs": m["distinct_pairs"],
            "pairs_pct": d["distinct_pairs_pct"],
            "wt": m["weak_tie"],
            "wt_pct": d["weak_tie_pct"],
            "td": m["traj_dev_m"],
            "refl": refl,
            "dlg": dlg,
            "tp": median(tps) if tps else None,
            "i2h": median(i2hs) if i2hs else None,
        })

    html = []
    html.append("""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>SSWT 14 天 Lane Cove 实证报告 (v3 — honest)</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
    line-height: 1.7; color: #2a2a2a; max-width: 1000px; margin: 32px auto;
    padding: 0 24px; background: #fafaf7; }
  h1 { font-size: 26px; margin: 0 0 6px; color: #1a1a1a; }
  h2 { font-size: 21px; margin: 36px 0 12px; padding-bottom: 6px;
    border-bottom: 1px solid #e0ddd5; color: #1a1a1a; }
  h3 { font-size: 16px; margin: 22px 0 8px; color: #333; }
  h4 { font-size: 15px; margin: 16px 0 6px; color: #444; }
  p { margin: 8px 0; }
  code { background: #efece4; padding: 1px 5px; border-radius: 3px;
    font-size: 13px; color: #553; font-family: monospace; }
  table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 14px; }
  th, td { border: 1px solid #d4d0c5; padding: 6px 10px; text-align: left; }
  th { background: #f0ece1; font-weight: 600; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  .lede { font-size: 17px; color: #555; margin: 4px 0 24px; }
  .meta { font-size: 13px; color: #888; margin: 4px 0 16px; }
  .verdict {
    background: #fef0f0; border: 2px solid #c92a2a; border-radius: 6px;
    padding: 16px 20px; margin: 18px 0;
  }
  .verdict h3 { margin-top: 0; color: #c92a2a; font-size: 17px; }
  .insight {
    background: #eef5ff; border-left: 3px solid #4a90e2;
    padding: 10px 14px; margin: 12px 0; border-radius: 3px; font-size: 14px;
  }
  .insight-warn {
    background: #fef3eb; border-left: 3px solid #d97706;
    padding: 10px 14px; margin: 12px 0; border-radius: 3px; font-size: 14px;
  }
  .secondary {
    background: #f5f3ee; border: 1px dashed #c4bfb4;
    padding: 12px 16px; margin: 12px 0; border-radius: 4px;
    font-size: 13px; color: #555;
  }
  .map-grid {
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px;
    margin: 12px 0;
  }
  .map-cell { position: relative; }
  .map-cell .label {
    position: absolute; top: 4px; left: 4px; background: rgba(255,255,255,0.92);
    padding: 2px 6px; border-radius: 3px; font-size: 11px; font-weight: 600;
  }
  .map-cell svg { width: 100%; height: auto; aspect-ratio: 1; }
  .legend { display: flex; gap: 12px; font-size: 12px; margin: 6px 0; flex-wrap: wrap; }
  .legend span { display: flex; align-items: center; gap: 4px; }
  .swatch { width: 12px; height: 12px; display: inline-block;
    border-radius: 2px; border: 1px solid #ccc; }
  .dialogue {
    background: white; border: 1px solid #e0ddd5; border-radius: 6px;
    padding: 12px 16px; margin: 10px 0; font-size: 14px;
  }
  .speaker { font-weight: 600; color: #1a4570; margin-bottom: 4px; font-size: 13px; }
  .speaker.linda { color: #6a3a8a; }
  .turn-label { font-size: 11px; color: #888; text-transform: uppercase; }
  .neg { color: #c92a2a; font-weight: 600; }
  .pos { color: #2c8a4a; font-weight: 600; }
  .footer {
    margin-top: 48px; padding-top: 18px; border-top: 1px solid #e0ddd5;
    font-size: 13px; color: #888;
  }
</style></head><body>
""")

    # ─── Header + thesis 重申 ────────────────────────────────────────
    html.append("""<h1>SSWT 14 天 Lane Cove 实证报告 (v3 honest)</h1>
<div class="lede">2026-05-09 / 4 variants × 3 seeds × 14 days × 100 agents × 10 protag / Gemini Flash / ai-town stack ON / 4.2 hr wall</div>
<div class="meta">本版报告纠正前两版的 framing 错误：thesis 主信号在 <strong>spatial-output</strong> 层（trajectory / 空间激活 / encounter 密度），<code>target_precision</code> / <code>info_2hops</code> 是 push 系统自身工艺指标 ≠ thesis 证据。</div>

<h2>0. Thesis 重申（避免再 framing 偏差）</h2>

<blockquote style="border-left: 3px solid #c0a060; padding: 8px 14px; background: #fdf8eb; color: #4a3f1e; margin: 12px 0; font-size: 14px;">
<strong>主论点</strong>：手机注意力在高密度城市制造物理社区的"<strong>隐形附近性盲区</strong>"——你每天经过的咖啡馆、邻居、公园都"看不见"，因为屏幕里在看 800 公里外的事。<strong>超在地性反向推送（hyperlocal push）能否把注意力——<u>进而把人</u>——带回"附近"</strong>？
</blockquote>

<p>thesis 关心的<strong>核心 measurement</strong>（来自 <code>00-thesis.md</code>）：</p>
<ul style="font-size:14px;">
  <li><strong>研究对象</strong>：agent 对 &lt;500m 范围内物理事件的感知强度 vs 对手机推流内容的感知强度</li>
  <li><strong>产出信号</strong>：<strong>trajectory 偏离、空间激活度、encounter 密度</strong>（全是 spatial-output 层）</li>
  <li><strong>下游验证</strong>：encounter→conversation 转化、弱关系增量（social-downstream，<u>需 spatial 信号先到</u>）</li>
</ul>

<p>用大白话讲：thesis 看 <strong>"agent 真的被拉到附近了吗"</strong>。如果 agent 物理活动没变化，<strong>装置层做得再漂亮、push 工艺再精准都不算 thesis 证据</strong>。</p>
""")

    # ─── §1 thesis verdict — front and center ──────────────────────
    hp = next(r for r in rows if r["variant"] == "hyperlocal_push")
    bl = next(r for r in rows if r["variant"] == "baseline")
    html.append(f"""<h2>1. Thesis Verdict（一句话先放出来）</h2>

<div class="verdict">
<h3>⚠ Preliminary evidence NOT consistent with H_info（信息不足假设）</h3>
<p style="margin:8px 0;font-size:15px;">
在 14 天 / Gemini 真 LLM / 完整 lane cove 数据注入下，<code>hyperlocal_push</code>
<strong>没有把 agent 拉回附近</strong>。物理 trajectory 中位偏离与 <code>global_distraction</code> 完全相同（mirror_delta = 0），
encounter 密度<strong>反而比 baseline 少 {abs(hp['encs_pct']):.1f}%</strong>（消失 ~{int(bl['encs'] - hp['encs'])} 次相遇 / seed），
distinct pair diversity 少 {abs(hp['pairs_pct']):.1f}%。
</p>
<p style="margin:8px 0;font-size:14px;color:#555;">
这是 3 seed preliminary 数据，β 严谨度需要 30 seed。但<strong>方向</strong>已经稳定：所有 3 个 seed 对（baseline → hp）都呈现一致的负向 delta。
</p>
</div>
""")

    # ─── §2 Spatial signal table — 带 delta vs baseline ────────────
    html.append("""<h2>2. Spatial-output 层数据 — thesis 主战场</h2>

<table>
<thead><tr>
  <th>variant</th>
  <th>encs total</th>
  <th>Δ vs baseline</th>
  <th>distinct pairs</th>
  <th>Δ vs baseline</th>
  <th>weak_tie</th>
  <th>traj_dev_m</th>
</tr></thead>
<tbody>
""")
    for r in rows:
        encs_cls = ' class="neg"' if r["encs_pct"] < -3 else (' class="pos"' if r["encs_pct"] > 3 else '')
        pairs_cls = ' class="neg"' if r["pairs_pct"] < -3 else (' class="pos"' if r["pairs_pct"] > 3 else '')
        td_str = f'{r["td"]:.1f}' if r["td"] else '—'
        html.append(f'<tr>'
                    f'<td><code>{r["variant"]}</code></td>'
                    f'<td class="num">{r["encs"]:.0f}</td>'
                    f'<td class="num"{encs_cls}>{r["encs_pct"]:+.1f}%</td>'
                    f'<td class="num">{r["pairs"]:.0f}</td>'
                    f'<td class="num"{pairs_cls}>{r["pairs_pct"]:+.1f}%</td>'
                    f'<td class="num">{r["wt"]:.0f}</td>'
                    f'<td class="num">{td_str}</td>'
                    f'</tr>\n')
    html.append("</tbody></table>\n")

    # Visual: encounter delta as bar chart
    html.append("""<h3>encounter 密度变化（thesis 核心信号之一）</h3>
<div style="background:white;border:1px solid #e0ddd5;border-radius:6px;padding:14px;margin:8px 0;">
""")
    for r in rows:
        pct = r["encs_pct"]
        color = "#c92a2a" if pct < -3 else "#198754" if pct > 3 else "#999"
        html.append(big_bar(
            r["variant"],
            pct,
            8,  # max_val so -7% renders to ~80%
            color=color,
            suffix="%",
            precision=1,
            neutral=(abs(pct) > 0.5),
        ))
    html.append("</div>\n")

    html.append("""<div class="insight-warn">
<strong>核心发现 ①</strong>：hyperlocal_push <strong>降低</strong> encounter 密度 <strong>−6.8%</strong>。thesis 假设是 hp 把人拉到附近 → encounter 应该 <strong>↑</strong>。结果反了。
</div>

<h3>distinct pair diversity（多少不同的人见到了对方）</h3>
<div style="background:white;border:1px solid #e0ddd5;border-radius:6px;padding:14px;margin:8px 0;">
""")
    for r in rows:
        pct = r["pairs_pct"]
        color = "#c92a2a" if pct < -3 else "#198754" if pct > 3 else "#999"
        html.append(big_bar(r["variant"], pct, 8, color=color, suffix="%", precision=1, neutral=(abs(pct) > 0.5)))
    html.append("</div>\n")

    html.append("""<div class="insight-warn">
<strong>核心发现 ②</strong>：hp 让 distinct pair count 也降了 −6.2%。<strong>不光是相遇次数变少，相遇的"人种"也少了</strong>——更少不同的 agent 在物理上碰到对方。
</div>
""")

    # ─── §3 物理空间 — 4 张图基本一样 ──────────────────────────────
    html.append("""<h2>3. 空间使用模式（thesis 信号之三）</h2>

<p>下面是 4 个 variant 在 14 天里 agent 累计停留 top-20 位置的叠加图（同一张 Lane Cove 街区图，红/橙/蓝/绿对应 4 条 variant）：</p>

<div class="legend">
  <span><span class="swatch" style="background:#a8c896;"></span>park</span>
  <span><span class="swatch" style="background:#dad6cd;"></span>street</span>
  <span><span class="swatch" style="background:#0d6efd;"></span>baseline</span>
  <span><span class="swatch" style="background:#dc3545;"></span>hyperlocal_push</span>
  <span><span class="swatch" style="background:#fd7e14;"></span>global_distraction</span>
  <span><span class="swatch" style="background:#198754;"></span>phone_friction</span>
</div>

<div class="map-grid">
""")
    for var in VARIANTS:
        html.append(f'  <div class="map-cell"><div class="label">{var}</div>'
                    f'<div style="position:relative;width:100%;">'
                    f'{base_map}{overlays[var]}</div></div>\n')
    html.append("</div>\n")

    html.append("""<div class="insight-warn">
<strong>核心发现 ③</strong>：4 张图的高密度区基本重合。per-seed 检查 hp top-20 vs baseline top-20，在每个 seed 内 <strong>set 完全相同</strong>（只是排名顺序略有重洗）。<strong>hp 没有开发新的"附近热点"</strong>——人去的还是同样的地方。
</div>
""")

    # ─── §4 三条核心信号一起看 ──────────────────────────────────────
    html.append("""<h2>4. 三条 thesis 信号的合并诊断</h2>

<table>
<thead><tr><th>信号</th><th>thesis 期望（如果 hp 起效）</th><th>实测</th><th>verdict</th></tr></thead>
<tbody>
<tr>
  <td>trajectory_deviation_m</td>
  <td>hp &lt; gd（hp 把人拉得更靠近 target_location）</td>
  <td>hp 325.5m = gd 325.5m，mirror_delta = 0</td>
  <td><span class="neg">null</span></td>
</tr>
<tr>
  <td>encounter density</td>
  <td>hp &gt; baseline（人聚到 target → 物理共处增加）</td>
  <td>hp <strong>−6.8%</strong> vs baseline，3 seed 一致</td>
  <td><span class="neg">反向</span></td>
</tr>
<tr>
  <td>空间使用 top-20 set</td>
  <td>hp 出现 baseline 没有的"新热点"（push 提到的本地点）</td>
  <td>per-seed set 与 baseline 完全相同，仅排名重洗</td>
  <td><span class="neg">null</span></td>
</tr>
</tbody>
</table>

<div class="verdict">
<h3>三个信号一致：thesis 主问题没有正向证据</h3>
<p>装置工艺（push 个体化、reflection、dialogue）跑得很好，但 <strong>agent "没上钩"</strong>。<u>看到了 push、知道了内容、聊了天，但身体没真的跟着走</u>。这是诚实的 14-day Gemini run 给出的答案。</p>
</div>
""")

    # ─── §5 root-cause 推测 + 下一步 ───────────────────────────────
    html.append("""<h2>5. 可能的 root cause（推测，需进一步验证）</h2>

<ol>
  <li><strong>push-content-individualization 反噬</strong>：5 个 audience cluster
    （parents / young_adult / elderly / newcomer / default）各被推到不同地点
    → 5 股拉力分散 → 群体中位轨迹几乎不变，agent 之间反而更分散（这能解释 encounter −7%）</li>
  <li><strong>should_replan 概率门设计偏低</strong>：
    <code>realism-attention-rebalance</code> 把 push 触发 replan 的"goldilocks band"
    设在 5–15%。若 push 大多数时候被 agent "看到但不行动"，effect 就被稀释。</li>
  <li><strong>scripted_plan 刚性</strong>：90/100 scripted agent 走 plan-driven
    路径，对 push 反应钝。10 protag 走 ai-town 决策树但样本太少，
    无法主导整体中位数。</li>
  <li><strong>target_location 选择不当</strong>：每 seed 随机选
    <code>destinations[0]</code>，可能不在 agent 自然路径上 → push 让 agent
    看到一个"从来不会去的远地方"，反应自然弱。</li>
</ol>

<h3>建议下一步（按"诊断价值 × 工时"排）</h3>

<ol>
  <li><strong>关闭 push 个体化做对照</strong>（约 4 hr Gemini）：<code>--use-aitown</code>
    保留，但加 <code>--disable-push-personalization</code>，看 hp 的 spatial signal
    是否回升。如果是 → push 个体化吃掉了 thesis 信号；如果不是 → 是更底层的问题。</li>
  <li><strong>调高 should_replan 灵敏度做敏感性</strong>（30 min）：把概率门
    p_threshold 从 5% 试到 25%、50%，看 hp 的 encounter 变化曲线。如果 hp 在
    高响应度下 encounter 才 ↑ → 是 attention→replan 链断；否则是更深问题。</li>
  <li><strong>看 protag-only encounter 子指标</strong>（半天）：把
    encounter_stats 拆成 "protag-protag / protag-scripted / scripted-scripted"
    三组。protag 是真正受 ai-town stack 影响的群体，他们的 encounter 变化才是
    干净的 thesis signal。</li>
  <li><strong>对照 5/5 archive 版本</strong>（半天）：5 月 5 日 stub-only run 的
    mirror_delta 是 59m，今天是 0m。把那时的代码 + 数据捞出来，diff 哪个 commit
    把 hp signal 抹掉了——很可能是 push-content-individualization
    （5/8 archive）的副作用。</li>
</ol>
""")

    # ─── §6 装置工艺指标 — 降级为辅证 ───────────────────────────────
    html.append("""<h2>6. 装置层确实运转（但这<u>不是</u>thesis 证据）</h2>

<div class="secondary">
<strong>本节的目的是承认装置层的工程价值，但明确把它<u>从 thesis 证据中移除</u></strong>。
之前两版 v1 / v2 把这些当 "thesis 后半段强信号" 是 framing 错误。下面列出的指标
是 push 系统自身的工艺指标 — push 内容能不能精准命中受众、信息能不能
广播到全场，但这些不直接证明 "thesis: agent 物理被拉回附近"。
</div>

<h3>6.1 装置工艺指标（per seed median）</h3>

<table>
<thead><tr><th>指标</th><th>baseline</th><th>hyperlocal_push</th><th>global_distraction</th><th>phone_friction</th></tr></thead>
<tbody>
""")

    metrics_rows = [
        ("reflection_count（ai-town 反思事件 / seed）", "refl"),
        ("dialogue_count（LLM 对话场次 / seed）", "dlg"),
        ("target_precision（push 命中目标受众率）", "tp"),
        ("info_2hops（信息穿透 ≥2 跳的 unique 数）", "i2h"),
    ]
    for label, key in metrics_rows:
        html.append("<tr>")
        html.append(f"<td>{label}</td>")
        for var in VARIANTS:
            r = next(rr for rr in rows if rr["variant"] == var)
            v = r.get(key)
            html.append(f'<td class="num">{fmt(v, ".2f" if key == "tp" else ".0f")}</td>')
        html.append("</tr>\n")
    html.append("</tbody></table>\n")

    html.append("""<p style="font-size:13px;color:#666;">
解读（如果只看装置层）：
<ul style="font-size:13px;">
  <li>reflection 4 个 variant 都 ~411 — ai-town 反思机制稳定（10 protag × 14 day × 3 insight ≈ 期望值）</li>
  <li>dialogue 全部 ~8 — auto-invite 在所有 variant 一样起效</li>
  <li>target_precision: hp 0.43 唯一非零，说明 push 个体化算法工作</li>
  <li>info_2hops: gd 128 vs hp 9 — broadcast vs targeted 信息传播形态对比</li>
</ul>
但 <strong>这些都没有进入 spatial-output 层</strong>。push 个体化做得很精准，
agent 也确实聊了天反思了，但 thesis 关心的"人有没有真被拉到附近"——没有证据。
</p>
""")

    # ─── §7 一段真 dialogue（保持，但定位为"装置确实跑了"）──────────
    if sample_t1:
        html.append(f"""<h3>6.2 一段真 LLM 对话样例（Gemini Flash 实录）</h3>
<p style="font-size:13px;color:#666;">这段证明装置层运转完整 — Emma 自然嵌入了 lane cove
shared memories（Galuwa centre / 2021 封城 / Food and Wine festival）和自己的
identity_text（Longueville Road 8 年居民）。但<u>请注意</u>：dialogue
丰富度 ≠ thesis 信号；agent 之间聊得多，不代表他们在物理上更靠近。</p>

<div class="dialogue">
  <div class="turn-label">Turn 1 — phase=start</div>
  <div class="speaker">Emma → Linda:</div>
  <div>{sample_t1}</div>
</div>
""")

    if sample_summary:
        html.append(f"""
<div class="dialogue" style="background:#fafaf3;">
  <div class="turn-label">Emma 第一人称回忆（remember_conversation）</div>
  <div class="speaker">Emma 内心:</div>
  <div>{sample_summary}</div>
</div>
""")

    # ─── Footer ─────────────────────────────────────────────────────
    html.append(f"""
<div class="footer">
<strong>报告生成于</strong> 2026-05-09 / 数据：<code>data/experiments/aitown_publishable_v1/</code> (4.2 hr wall, 12 seeds)<br>
<strong>thesis canonical</strong>：<code>docs/agent_system/00-thesis.md</code><br>
<strong>实验设计</strong>：<code>docs/agent_system/13-research-design.md</code><br>
<strong>注</strong>：3 seed 不到 β 严谨度（30 seed），所有数字标记 [unpublishable preview]。但 verdict 方向（hp 在 spatial 层 null/negative）在 3/3 seed 一致。
</div>
</body></html>
""")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(html), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    main()
