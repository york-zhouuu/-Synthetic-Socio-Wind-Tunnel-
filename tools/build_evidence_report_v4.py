"""Evidence Report v4 — based on post-fix metric schema (round-1 + round-2 + A1 + B).

Differences from v3:
- Reads new RunMetrics fields: trajectory_deviation_m_all (sanity column),
  reproducibility_lock.provider, replan_no_op_count
- All 4 variants in one consolidated HTML
- Honest framing per docs/audit/2026-05-09-bug-hunt.md (no false "hp -6.8% reverse"
  narrative; uses real post-fix data)
- Consumes a suite output dir directly (no /tmp/*.json indirection)

Usage:
    python3 tools/build_evidence_report_v4.py <suite_dir> [--out report_v4.html]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any


_HTML_HEAD = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Synthetic Socio Wind Tunnel — Evidence Report v4</title>
<style>
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC",
               "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  max-width: 1100px; margin: 0 auto; padding: 60px 40px;
  line-height: 1.7; color: #1f1f1f; background: #fbfaf6;
}
h1 { font-size: 32px; margin: 0 0 8px; }
h2 { font-size: 22px; margin: 60px 0 20px; padding-bottom: 8px;
     border-bottom: 2px solid #1f1f1f; }
h3 { font-size: 18px; margin: 28px 0 10px; }
.subtitle { color: #888; font-size: 14px; letter-spacing: 0.1em;
            text-transform: uppercase; margin-bottom: 30px; }
table { border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 14px; }
th, td { padding: 10px 14px; border-bottom: 1px solid #e5e2d6; text-align: left; }
th { background: #f4f1e8; font-weight: 600; }
tr:nth-child(even) td { background: #fff; }
.metric-key { font-family: ui-monospace, "SF Mono", monospace; font-size: 13px;
              color: #555; }
.bar { display: inline-block; height: 16px; background: #c8553d; border-radius: 2px;
       vertical-align: middle; margin-right: 8px; min-width: 2px; }
.bar.baseline { background: #888; }
.bar.hp { background: #c8553d; }
.bar.gd { background: #fd7e14; }
.bar.pf { background: #198754; }
.note { background: #fff4cc; padding: 12px 18px; border-left: 4px solid #c8553d;
        margin: 16px 0; font-size: 14px; }
.metadata { background: #fff; border: 1px solid #e5e2d6; border-radius: 6px;
            padding: 16px 20px; font-size: 13px; font-family: ui-monospace, monospace; }
.success { color: #1e7e34; }
.warn { color: #c8553d; }
</style>
</head>
<body>
"""


def _load_suite(suite_dir: Path) -> dict[str, list[dict]]:
    by_variant: dict[str, list[dict]] = {}
    for vd in sorted(suite_dir.iterdir()):
        if not vd.is_dir() or not vd.name.startswith("variant_"):
            continue
        for sf in sorted(vd.glob("seed_*.json")):
            with sf.open(encoding="utf-8") as fh:
                by_variant.setdefault(vd.name, []).append(json.load(fh))
    return by_variant


def _stat(values: list[float]) -> dict[str, float]:
    if not values:
        return {"median": 0, "min": 0, "max": 0, "n": 0}
    return {
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "n": len(values),
    }


def _aggregate(seeds: list[dict]) -> dict[str, Any]:
    """Collect cross-seed stats per metric of interest."""
    encs = [s.get("run_metrics", {}).get("encounter_stats", {}).get("total", 0)
            for s in seeds]
    enc_med = [s.get("run_metrics", {}).get("encounter_stats", {}).get("per_day_median", 0)
               for s in seeds]
    weak_tie = [s.get("run_metrics", {}).get("weak_tie_formation_count", 0) or 0
                for s in seeds]
    traj_subset = [s.get("run_metrics", {}).get("trajectory_deviation_m") or 0
                   for s in seeds]
    traj_all = [s.get("run_metrics", {}).get("trajectory_deviation_m_all") or 0
                for s in seeds]
    replan = [s.get("run_metrics", {}).get("extensions", {}).get("replan_count", 0)
              for s in seeds]
    replan_noop = [s.get("run_metrics", {}).get("extensions", {}).get(
                       "replan_no_op_count", 0) for s in seeds]
    cost_total = sum(
        (s.get("run_metrics", {}).get("cost_breakdown") or {}).get("total", 0)
        for s in seeds
    )
    rep = (seeds[0].get("run_metrics", {}).get("extensions", {}).get(
        "reproducibility_lock", {})) if seeds else {}
    return {
        "encs": _stat(encs),
        "enc_med": _stat(enc_med),
        "weak_tie": _stat(weak_tie),
        "traj_subset": _stat(traj_subset),
        "traj_all": _stat(traj_all),
        "replan": _stat(replan),
        "replan_noop": _stat(replan_noop),
        "cost_total": cost_total,
        "rep": rep,
        "n_seeds": len(seeds),
    }


def _bar_html(value: float, max_value: float, css_class: str = "") -> str:
    if max_value <= 0:
        return ""
    width = max(2, int(200 * value / max_value))
    return f'<span class="bar {css_class}" style="width:{width}px;"></span>'


def _render_table(by_variant: dict[str, dict]) -> str:
    """Comparison table across 4 variants."""
    rows = []
    rows.append("<thead><tr><th>variant</th>"
                "<th>encounter total (median)</th>"
                "<th>encounter per_day_median</th>"
                "<th>weak ties</th>"
                "<th>traj_dev_m (protag)</th>"
                "<th>traj_dev_m_all</th>"
                "<th>replan</th>"
                "<th>no_op</th>"
                "</tr></thead><tbody>")
    enc_max = max((d["encs"]["median"] for d in by_variant.values()), default=1)
    for name, d in by_variant.items():
        css = name.replace("variant_", "").replace("_", "")[:2]
        if css == "ba": css = "baseline"
        elif css == "hy": css = "hp"
        elif css == "gl": css = "gd"
        elif css == "ph": css = "pf"
        rows.append(
            f"<tr>"
            f"<td><strong>{name.replace('variant_','')}</strong></td>"
            f"<td>{_bar_html(d['encs']['median'], enc_max, css)}{d['encs']['median']:.0f}</td>"
            f"<td>{d['enc_med']['median']:.0f}</td>"
            f"<td>{d['weak_tie']['median']:.0f}</td>"
            f"<td>{d['traj_subset']['median']:.1f}</td>"
            f"<td>{d['traj_all']['median']:.1f}</td>"
            f"<td>{d['replan']['median']:.0f}</td>"
            f"<td>{d['replan_noop']['median']:.0f}</td>"
            f"</tr>"
        )
    rows.append("</tbody>")
    return "<table>" + "\n".join(rows) + "</table>"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("suite_dir", type=Path)
    p.add_argument("--out", type=Path, default=None,
                   help="Output HTML path (default: <suite_dir>/report_v4.html)")
    args = p.parse_args()

    if not args.suite_dir.is_dir():
        print(f"error: not a directory: {args.suite_dir}", file=sys.stderr)
        return 2

    raw = _load_suite(args.suite_dir)
    if not raw:
        print(f"error: no variant_*/seed_*.json found", file=sys.stderr)
        return 2

    by_variant = {name: _aggregate(seeds) for name, seeds in raw.items()}

    out_path = args.out or args.suite_dir / "report_v4.html"

    # Build HTML
    parts = [_HTML_HEAD]
    parts.append(f'<p class="subtitle">Synthetic Socio Wind Tunnel · Evidence Report v4</p>')
    parts.append("<h1>Lane Cove publishable run · 真实数据答卷</h1>")
    parts.append(f"<p>套件路径：<span class='metric-key'>{args.suite_dir}</span></p>")

    # Reproducibility metadata
    parts.append("<h2>① 可复现指纹</h2>")
    sample_rep = next(iter(by_variant.values()))["rep"]
    parts.append('<div class="metadata">')
    for k in ["provider", "model_version", "code_commit", "seed_pool",
              "phase_config", "LANE_COVE_PROFILE_hash"]:
        v = sample_rep.get(k, "?")
        if isinstance(v, dict):
            v = json.dumps(v, ensure_ascii=False)
        elif isinstance(v, list):
            v = ", ".join(str(x) for x in v)
        elif isinstance(v, str) and len(v) > 80:
            v = v[:60] + "…(SHA256)"
        parts.append(f"<div><strong>{k}:</strong> {v}</div>")
    parts.append("</div>")

    # 4 variant comparison
    parts.append("<h2>② 4 variant 主要指标对比</h2>")
    parts.append(_render_table(by_variant))

    # Cost
    total_cost = sum(d["cost_total"] for d in by_variant.values())
    parts.append("<h2>③ 真 LLM 成本</h2>")
    if total_cost > 0:
        parts.append(f"<p>本次跑 <strong>${total_cost:.2f}</strong>（"
                     f"provider={sample_rep.get('provider', '?')}）。</p>")
    else:
        parts.append('<p class="warn">cost_breakdown.total = 0；'
                     "如果 provider 是 gemini/anthropic，可能 token 没记上。"
                     "stub provider 下 0 是预期。</p>")

    # Methodological notes
    parts.append("<h2>④ 解读说明</h2>")
    parts.append('<div class="note">'
                 "<strong>注意</strong>：本报告基于 round-1 + round-2 + A1 + B 全套修复后的数据。"
                 "之前 14-day suite 里出现的 \"hp encounter -6.8% 反向\" 是 measurement bug "
                 "(B9 encounter 漏算 stationary co-presence) 制造的，已修。"
                 "trajectory_deviation_m 现在是 protag-only median；"
                 "trajectory_deviation_m_all 是 sanity 对照（all-agent median，受 90% scripted "
                 "agent 主导，仅供诊断 spillover 用）。"
                 "</div>")

    parts.append("<h2>⑤ 各 variant per-seed detail</h2>")
    for name, d in by_variant.items():
        parts.append(f"<h3>{name}</h3>")
        parts.append(f'<p>n_seeds = {d["n_seeds"]}; '
                     f'replan_no_op_count median = {d["replan_noop"]["median"]:.0f} '
                     f'(0 = stub 工作正常 / 真 LLM 没 fallback)</p>')

    parts.append("</body></html>")

    out_path.write_text("".join(parts), encoding="utf-8")
    print(f"✅ wrote {out_path}")
    print(f"   {sum(d['n_seeds'] for d in by_variant.values())} seed records "
          f"across {len(by_variant)} variants")
    return 0


if __name__ == "__main__":
    sys.exit(main())
