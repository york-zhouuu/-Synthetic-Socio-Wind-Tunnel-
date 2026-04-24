"""
ContestReport — 跨 variant 的 rival hypothesis contest 打分器。

判据（见 design D4）：
- CI 不重叠 → "consistent" / "not_consistent"
- CI 重叠 → "inconclusive"

措辞门禁（experimental-design spec 要求）：生成的 `notes` 禁用
"proved / falsified / confirmed / refuted"（大小写不敏感）。
"""

from __future__ import annotations

from typing import Any

from synthetic_socio_wind_tunnel.metrics.models import (
    ContestReport,
    ContestRow,
    EvidenceAlignment,
    SuiteAggregate,
)


# variant_name → 哪个 per_metric_stats key 作 primary effect size
_PRIMARY_METRIC_DISPATCH: dict[str, str] = {
    "hyperlocal_push": "trajectory_deviation_m",
    "global_distraction": "trajectory_deviation_m",
    # 其它 variant 选 "encounter.per_day_median" 作 primary——简化第一版；
    # phone_friction 理想用 "attention.physical_world"（本 change 只有
    # phone_feed_proxy；未来扩展）
    "phone_friction": "attention.phone_feed_proxy",
    "shared_anchor": "encounter.per_day_median",
    "catalyst_seeding": "encounter.per_day_median",
    "baseline": "encounter.per_day_median",
}


# variant_name → "higher is better" / "lower is better"（相对 baseline）
# 用于 evidence_alignment 方向判定
#
# hyperlocal_push: target agents 向 target_location 靠近 → distance 降低
#   → lower is "better"（更支持 H_info）
# global_distraction: 同 feed channel 反向 → distance 升高 →
#   higher is "consistent with 镜像假设"（但我们比较 baseline 时 lower still means same pattern as baseline）
#   实际上是"与 baseline 有 delta 即证 channel dual-use"——方向不定
# phone_friction: phone_feed_proxy 应 lower（friction 降低 phone 占用）
# shared_anchor: encounter 应 higher（共享锚点导致 co-visit）
# catalyst_seeding: encounter 应 higher（connector 增加连接）
_DIRECTION_DISPATCH: dict[str, str] = {
    "hyperlocal_push": "lower",     # 距离 target_location 越小越 support
    "global_distraction": "higher",  # 距离 target 越大越 support "distraction dual-use"
    "phone_friction": "lower",       # phone_feed_proxy 应下降
    "shared_anchor": "higher",       # encounter 应上升
    "catalyst_seeding": "higher",    # encounter 应上升
    "baseline": "lower",             # placeholder；baseline 不做 alignment
}


_FORBIDDEN_WORDS = ("proved", "falsified", "confirmed", "refuted")


def _assert_no_forbidden(text: str) -> None:
    lower = text.lower()
    for w in _FORBIDDEN_WORDS:
        if w in lower:
            raise ValueError(
                f"ContestReport notes contains forbidden word {w!r}; "
                "use 'evidence consistent with / not consistent with' instead",
            )


def _evidence_alignment(
    *,
    variant_ci: tuple[float, float] | None,
    baseline_ci: tuple[float, float] | None,
    direction: str,
) -> EvidenceAlignment:
    """
    CI 对比：
    - direction="lower"：期望 variant 的值 < baseline；若 variant_hi < baseline_lo → consistent
    - direction="higher"：期望 variant > baseline；若 variant_lo > baseline_hi → consistent
    - 反向同理判 not_consistent
    - 其它（重叠 / 缺数据）→ inconclusive
    """
    if variant_ci is None or baseline_ci is None:
        return "inconclusive"
    v_lo, v_hi = variant_ci
    b_lo, b_hi = baseline_ci

    if direction == "lower":
        if v_hi < b_lo:
            return "consistent"
        if v_lo > b_hi:
            return "not_consistent"
        return "inconclusive"
    elif direction == "higher":
        if v_lo > b_hi:
            return "consistent"
        if v_hi < b_lo:
            return "not_consistent"
        return "inconclusive"
    return "inconclusive"


def _metric_stats(agg: SuiteAggregate, metric: str) -> dict[str, float] | None:
    return agg.per_metric_stats.get(metric)


def _ci_tuple(stats: dict[str, float] | None) -> tuple[float, float] | None:
    if stats is None:
        return None
    return (stats["ci95_lo"], stats["ci95_hi"])


def _effect_size(stats: dict[str, float] | None) -> float | None:
    if stats is None:
        return None
    return stats["median"]


def build_contest_report(
    aggregates: dict[str, SuiteAggregate],
    *,
    suite_name: str,
) -> ContestReport:
    """
    跨 variant 组装 ContestReport。

    - 若 aggregates 含 `baseline`：其它 variant 与 baseline 比较 alignment
    - 若无 baseline：第一个 variant 作 reference，每行注明
    """
    baseline_agg = aggregates.get("baseline")
    reference_agg = baseline_agg
    reference_note_missing = False
    if reference_agg is None and aggregates:
        reference_agg = next(iter(aggregates.values()))
        reference_note_missing = True

    rows: list[ContestRow] = []
    baseline_row: ContestRow | None = None

    for variant_name, agg in aggregates.items():
        meta = agg.variant_metadata or {}
        hypothesis = meta.get("hypothesis") if variant_name != "baseline" else None
        paired = meta.get("paired_variant")

        primary_metric = _PRIMARY_METRIC_DISPATCH.get(variant_name)
        direction = _DIRECTION_DISPATCH.get(variant_name, "lower")

        v_stats = _metric_stats(agg, primary_metric) if primary_metric else None
        v_eff = _effect_size(v_stats)
        v_ci = _ci_tuple(v_stats)

        # baseline ref
        if variant_name == "baseline":
            alignment: EvidenceAlignment = "inconclusive"
            baseline_ref = v_eff
            notes = "baseline reference; evidence alignment not computed"
        else:
            if reference_agg is None or primary_metric is None:
                alignment = "inconclusive"
                baseline_ref = None
                notes = (
                    "evidence not consistent nor consistent—missing reference or "
                    "primary metric"
                )
            else:
                ref_stats = _metric_stats(reference_agg, primary_metric)
                ref_ci = _ci_tuple(ref_stats)
                baseline_ref = _effect_size(ref_stats)
                alignment = _evidence_alignment(
                    variant_ci=v_ci, baseline_ci=ref_ci, direction=direction,
                )
                if alignment == "consistent":
                    notes = (
                        f"evidence consistent with {hypothesis or 'this variant'}: "
                        f"primary metric {primary_metric} CI "
                        f"{'below' if direction == 'lower' else 'above'} baseline CI"
                    )
                elif alignment == "not_consistent":
                    notes = (
                        f"evidence not consistent with {hypothesis or 'this variant'}: "
                        f"primary metric trends opposite to expected direction"
                    )
                else:
                    notes = (
                        f"inconclusive: CI overlap between variant and reference "
                        f"for {primary_metric}"
                    )
                if reference_note_missing:
                    notes += " (NB: baseline missing; reference is first variant)"
                if agg.degraded_preliminary_not_publishable:
                    notes += " [preliminary—seed count < 30]"

        # mirror delta: 找 paired variant
        mirror_delta: float | None = None
        if paired and paired in aggregates:
            paired_agg = aggregates[paired]
            paired_stats = _metric_stats(paired_agg, primary_metric) if primary_metric else None
            paired_eff = _effect_size(paired_stats)
            if v_eff is not None and paired_eff is not None:
                mirror_delta = v_eff - paired_eff

        _assert_no_forbidden(notes)

        row = ContestRow(
            variant_name=variant_name,
            hypothesis=hypothesis,
            primary_metric=primary_metric,
            primary_effect_size=v_eff,
            primary_effect_ci=v_ci,
            baseline_reference=baseline_ref,
            evidence_alignment=alignment,
            mirror_delta=mirror_delta,
            paired_variant=paired,
            notes=notes,
        )
        rows.append(row)
        if variant_name == "baseline":
            baseline_row = row

    return ContestReport(
        suite_name=suite_name,
        rows=tuple(rows),
        baseline_row=baseline_row,
    )


__all__ = ["build_contest_report"]
