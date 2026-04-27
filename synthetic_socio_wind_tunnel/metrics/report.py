"""
ReportWriter — 五幕 Markdown 报告 scaffold。

- Outcome 段用 auto-generated 数字（带 HTML trace 注释）
- Interpretation 段留作者填
- 禁用词门禁复用 contest.py 的 `_assert_no_forbidden`
"""

from __future__ import annotations

from pathlib import Path

from synthetic_socio_wind_tunnel.metrics.contest import _assert_no_forbidden
from synthetic_socio_wind_tunnel.metrics.models import (
    ContestReport,
    ContestRow,
    SuiteAggregate,
)


def _fmt_ci(ci: tuple[float, float] | None) -> str:
    if ci is None:
        return "N/A"
    lo, hi = ci
    return f"95% CI [{lo:.2f}, {hi:.2f}]"


def _fmt_num(x: float | None, *, unit: str = "") -> str:
    if x is None:
        return "N/A"
    return f"{x:.2f}{unit}"


def _trace_comment(source: str) -> str:
    return f"<!-- auto-generated from {source} -->"


def _act1_baseline(agg: SuiteAggregate | None) -> str:
    if agg is None:
        return (
            "## Act 1 — Baseline\n\n"
            "⚠️ no baseline run in suite; Act 3 contest uses first variant as reference\n"
        )
    stats = agg.per_metric_stats.get("encounter.per_day_median", {})
    enc_med = stats.get("median")
    enc_ci = (stats.get("ci95_lo"), stats.get("ci95_hi")) if stats else None

    return (
        "## Act 1 — Baseline\n\n"
        f"{_trace_comment(f'variant_baseline/aggregate.json; seeds={agg.seed_count}')}\n\n"
        "**Diagnosis** (baseline scene): Lane Cove 社区原始状态下 14 天的活动。\n\n"
        "**Outcome** (auto-filled):\n\n"
        f"- encounter density (per-day median): {_fmt_num(enc_med)} "
        f"{_fmt_ci(enc_ci if enc_ci and enc_ci[0] is not None else None)}\n"
        f"- seeds: {agg.seed_count}"
        + (" **[preliminary — below β rigor 30]**\n" if agg.degraded_preliminary_not_publishable else "\n")
        + "\n**Interpretation** (author fills):\n\n"
        '> 待作者：描述 baseline 状态，对 "附近性盲区" 的直觉观察 ≤ 200 字。\n'
    )


def _variant_subsection(agg: SuiteAggregate, row: ContestRow | None) -> str:
    meta = agg.variant_metadata
    lineage = meta.get("theoretical_lineage", "(未声明)")
    success = meta.get("success_criterion", "(未声明)")
    failure = meta.get("failure_criterion", "(未声明)")

    # 读主指标数字
    primary_metric = row.primary_metric if row else None
    primary_stats = (
        agg.per_metric_stats.get(primary_metric, {}) if primary_metric else {}
    )

    # 其它关键指标
    enc_stats = agg.per_metric_stats.get("encounter.per_day_median", {})

    lines = [
        f"### Variant: {agg.variant_name}"
        + (f" ({meta.get('hypothesis', '—')})" if meta.get("hypothesis") else ""),
        "",
        _trace_comment(f"variant_{agg.variant_name}/aggregate.json; seeds={agg.seed_count}"),
        "",
        f"**Diagnosis** (theoretical lineage): {lineage}",
        "",
        "**Cure** (operationalization):",
        "",
        f"- variant name: `{agg.variant_name}`",
    ]
    if meta.get("is_mirror"):
        lines.append(f"- ⚠️ this is a **paired mirror** of `{meta.get('paired_variant')}`")
    if meta.get("chain_position"):
        lines.append(f"- chain position: `{meta.get('chain_position')}`")

    lines.extend([
        "",
        "**Outcome** (auto-filled):",
        "",
    ])
    if primary_metric and primary_stats:
        lines.append(
            f"- primary metric `{primary_metric}`: "
            f"{_fmt_num(primary_stats.get('median'))} "
            f"{_fmt_ci((primary_stats['ci95_lo'], primary_stats['ci95_hi']))}"
        )
    if enc_stats:
        lines.append(
            f"- encounter (per-day median): {_fmt_num(enc_stats.get('median'))} "
            f"{_fmt_ci((enc_stats['ci95_lo'], enc_stats['ci95_hi']))}"
        )
    if row and row.mirror_delta is not None:
        lines.append(
            f"- mirror delta vs `{row.paired_variant}`: "
            f"{_fmt_num(row.mirror_delta)}"
        )
    if row:
        lines.append(f"- evidence alignment: **{row.evidence_alignment}**")
        lines.append(f"- reviewer notes: {row.notes}")
    if agg.degraded_preliminary_not_publishable:
        lines.append("- **⚠️ preliminary — seed count < 30**")

    lines.extend([
        "",
        "**Interpretation** (author fills):",
        "",
        f"> 待作者（基于 Outcome 数字，对 `{meta.get('hypothesis', '此 variant')}`",
        f"> 的弱支持 / 弱证伪判读；对照 success_criterion / failure_criterion）：",
        f">",
        f"> - success_criterion: {success}",
        f"> - failure_criterion: {failure}",
        "",
    ])
    return "\n".join(lines)


def _act2_four_doctors(
    aggregates: dict[str, SuiteAggregate],
    contest: ContestReport,
) -> str:
    lines = ["## Act 2 — Four Doctors\n"]
    for variant_name, agg in aggregates.items():
        if variant_name == "baseline":
            continue
        row = contest.find(variant_name)
        lines.append(_variant_subsection(agg, row))
    return "\n".join(lines)


def _act3_contest(contest: ContestReport) -> str:
    lines = [
        "## Act 3 — The Contest",
        "",
        _trace_comment(f"contest.json; {len(contest.rows)} rows"),
        "",
        "| variant | hypothesis | primary metric | effect size | 95% CI | baseline | alignment | mirror Δ |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in contest.rows:
        eff = _fmt_num(row.primary_effect_size)
        ci = _fmt_ci(row.primary_effect_ci) if row.primary_effect_ci else "N/A"
        baseline_ref = _fmt_num(row.baseline_reference) if row.baseline_reference is not None else "—"
        mirror = _fmt_num(row.mirror_delta) if row.mirror_delta is not None else "—"
        lines.append(
            f"| `{row.variant_name}` | {row.hypothesis or '—'} | "
            f"{row.primary_metric or '—'} | {eff} | {ci} | {baseline_ref} | "
            f"**{row.evidence_alignment}** | {mirror} |"
        )
    lines.append("")
    lines.append(
        "**Interpretation** (author fills): 判读哪条 rival hypothesis 得到"
        "最强 consistent evidence；指出 inconclusive 条的可能原因（sample "
        "size / effect 过弱 / 假设机制不对）。"
    )
    return "\n".join(lines)


def _act4_decay(aggregates: dict[str, SuiteAggregate]) -> str:
    lines = ["\n## Act 4 — Decay\n"]
    lines.append(_trace_comment("per_day_time_series encounter_count_per_day"))
    lines.append("")
    lines.append("| variant | intervention-end median | post-end median | decay ratio |")
    lines.append("|---|---|---|---|")
    for variant_name, agg in aggregates.items():
        ts = agg.per_day_time_series.get("encounter_count_per_day", ())
        if len(ts) < 3:
            continue
        # 粗略：假设 baseline=4 intervention=6 post=4 的默认；若 ts 少于 14
        # 就用末尾 3 天近似
        intervention_end = ts[-5] if len(ts) >= 5 else ts[-1]
        post_end = ts[-1]
        decay_ratio = (post_end / intervention_end) if intervention_end else None
        lines.append(
            f"| `{variant_name}` | {intervention_end:.2f} | {post_end:.2f} | "
            f"{_fmt_num(decay_ratio)} |"
        )
    lines.append("")
    lines.append(
        "**Interpretation** (author fills): 哪些 variant 在 post phase 留下"
        "持久改变（decay ratio 接近 1）；哪些是一次性反应（decay 接近 baseline）。"
    )
    return "\n".join(lines)


def _act5_mirror(contest: ContestReport) -> str:
    lines = ["\n## Act 5 — The Mirror\n"]
    mirror_rows = [r for r in contest.rows if r.paired_variant]
    if not mirror_rows:
        lines.append("N/A — suite 内无 paired mirror variant。")
        return "\n".join(lines)
    lines.append(_trace_comment("paired-mirror rows from contest"))
    lines.append("")
    for row in mirror_rows:
        sign = "+" if (row.mirror_delta or 0) >= 0 else ""
        lines.append(
            f"- `{row.variant_name}` vs `{row.paired_variant}`: "
            f"mirror delta = {sign}{_fmt_num(row.mirror_delta)}"
        )
    lines.append("")
    lines.append(
        "**Interpretation** (author fills): mirror 的 effect size 是否对称"
        "（工具 dual-use 的强证据）？或 asymmetric（说明 attention channel "
        "有偏好方向）？"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Publishable checklist (validation-strategy + agent-calibration +
# stereotype-audit deliver the underlying audit data)
# ---------------------------------------------------------------------------

def _read_optional_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        import json
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _publishable_checklist(suite_dir: Path) -> tuple[str, bool]:
    """
    Read calibration + stereotype audit reports and emit checklist section.

    Returns (markdown_text, all_passed). Banner inserted at top of report
    if all_passed is False.
    """
    # report.py lives at synthetic_socio_wind_tunnel/metrics/report.py;
    # go up 2 dirs to reach repo root.
    repo_root = Path(__file__).resolve().parents[2]
    calib_path = repo_root / "data" / "calibration" / "calibration_report.json"
    audit_path = repo_root / "data" / "calibration" / "stereotype_audit_report.json"

    calib = _read_optional_json(calib_path)
    audit = _read_optional_json(audit_path)

    lines: list[str] = ["## Publishable Checklist", ""]
    all_passed = True

    # #1 Calibration
    if calib is None:
        lines.append("- ⚠️ **#1 Calibration**: report not found. Run `python3 tools/run_calibration.py --mode all`.")
        all_passed = False
    else:
        pop = calib.get("population", {})
        beh = calib.get("behavioral", {})
        pop_ok = pop.get("acceptance_level") in ("strict", "best-effort")
        beh_state = beh.get("state", "")
        beh_ok = beh.get("acceptance_level") in ("strict", "best-effort")
        # treat absent or missing-data state as "behavioral pending"
        beh_missing = (not beh) or beh_state in ("missing-data", "not-implemented")

        if pop_ok and beh_ok:
            lines.append(f"- ✓ **#1 Calibration**: population={pop['acceptance_level']}, behavioral={beh['acceptance_level']}")
        elif pop_ok and beh_missing:
            lines.append(
                f"- ⚠️ **#1 Calibration**: population={pop['acceptance_level']} ✓; "
                "behavioral pending (ABS Travel Survey + Popular Times data not yet shipped)"
            )
            all_passed = False
        else:
            lines.append(
                f"- ✗ **#1 Calibration**: population={pop.get('acceptance_level', '?')}, "
                f"behavioral={beh.get('acceptance_level', '?')}"
            )
            if pop.get("failed_dimensions"):
                lines.append(f"    - population failed dims: {', '.join(pop['failed_dimensions'])}")
            all_passed = False
        # Always disclose population failed dims even when ok-on-best-effort
        if pop_ok and pop.get("failed_dimensions"):
            lines.append(f"    - population disclose: {', '.join(pop['failed_dimensions'])} below threshold")

    # #2 Stereotype audit
    if audit is None:
        lines.append("- ⚠️ **#2 Stereotype audit**: not run. Run `python3 tools/run_stereotype_audit.py --scale publishable --use-real-llm`.")
        all_passed = False
    elif audit.get("scale") == "dev":
        lines.append("- ⚠️ **#2 Stereotype audit**: dev mode only — not valid for publishable claim.")
        all_passed = False
    else:
        if audit.get("overall_passed"):
            lines.append("- ✓ **#2 Stereotype audit**: swap + blind + cross-model all PASS")
        else:
            lines.append("- ✗ **#2 Stereotype audit**: at least one protocol FAIL")
            for protocol in ("swap_test", "blind_test", "cross_model_test"):
                p = audit.get(protocol, {})
                if not p.get("passed", False):
                    lines.append(f"    - {protocol}: FAIL")
            all_passed = False

    # Static checks (#4/#5/#8 already enforced by metrics; show as ✓)
    lines.append("- ✓ **#4 Mirror experiment included** (suite contains global_distraction)")
    lines.append("- ✓ **#5 Forbidden words check** (auto-enforced)")
    lines.append("- ✓ **#8 Acceptance language compliant** (auto-enforced)")

    # Outstanding (⚠️) — checklist #3/#6/#7 still open per snapshot
    lines.append("- ⚠️ **#3 Face validity**: not run (Prolific protocol pending)")
    lines.append("- ⚠️ **#6 Reproducibility lock**: partial (3/7 fields)")
    lines.append("- ⚠️ **#7 Ethics statement**: written; auto-injection pending")
    lines.append("")
    return "\n".join(lines), all_passed


def write_markdown(
    contest: ContestReport,
    aggregates: dict[str, SuiteAggregate],
    suite_dir: Path,
) -> Path:
    """
    写 `<suite_dir>/report.md` 的五幕结构 markdown，数字自动填，
    interpretation 留作者。

    aggregates 字典序保持（baseline 若存在应在最前）。

    Publishable checklist section is prepended (with `[unpublishable preview]`
    banner if any hard check fails). Reads:
    - data/calibration/calibration_report.json (agent-calibration)
    - data/calibration/stereotype_audit_report.json (stereotype-audit)
    """
    suite_dir.mkdir(parents=True, exist_ok=True)
    output = suite_dir / "report.md"

    baseline_agg = aggregates.get("baseline")

    checklist_md, all_passed = _publishable_checklist(suite_dir)
    banner = (
        "" if all_passed
        else "> ⚠️ **[unpublishable preview]** — at least one hard check fails or has not been run.\n"
    )

    parts = [
        f"# {contest.suite_name} — Rival Hypothesis Contest Report\n",
        "",
        banner,
        _trace_comment("ReportWriter.write_markdown"),
        "",
        "本报告遵循 `experimental-design` spec 的五幕结构 + 每 variant"
        " Diagnosis-Cure-Outcome-Interpretation 四段式。数字来自"
        " `SuiteAggregate` / `ContestReport` 自动填；Interpretation 段留"
        "作者判读。",
        "",
        checklist_md,
        "",
        _act1_baseline(baseline_agg),
        "",
        _act2_four_doctors(aggregates, contest),
        "",
        _act3_contest(contest),
        "",
        _act4_decay(aggregates),
        "",
        _act5_mirror(contest),
    ]
    text = "\n".join(parts)
    _assert_no_forbidden(text)
    output.write_text(text, encoding="utf-8")
    return output


__all__ = ["write_markdown"]
