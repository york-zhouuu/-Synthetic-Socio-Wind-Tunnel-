"""
RunMetrics 的工厂：从 TickMetricsRecorder + MultiDayResult + variant_metadata
组装完整 RunMetrics。

分开写在 factory.py（不放 models.py）避免 models 依赖 Ledger/Atlas。
"""

from __future__ import annotations

import math
import statistics
from typing import TYPE_CHECKING, Any

from synthetic_socio_wind_tunnel.metrics.models import (
    DayMetricsSummary,
    RunMetrics,
)

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.atlas import Atlas
    from synthetic_socio_wind_tunnel.attention.service import AttentionService
    from synthetic_socio_wind_tunnel.metrics.recorder import TickMetricsRecorder
    from synthetic_socio_wind_tunnel.orchestrator import MultiDayResult


# ---------------------------------------------------------------------------
# Phase helpers
# ---------------------------------------------------------------------------

def _phase_days(phase_config: dict[str, Any]) -> tuple[int, int, int]:
    return (
        int(phase_config.get("baseline_days", 4)),
        int(phase_config.get("intervention_days", 6)),
        int(phase_config.get("post_days", 4)),
    )


def _baseline_end_day(phase_config: dict[str, Any]) -> int:
    b, _, _ = _phase_days(phase_config)
    return b - 1  # inclusive end


def _intervention_end_day(phase_config: dict[str, Any]) -> int:
    b, i, _ = _phase_days(phase_config)
    return b + i - 1


# ---------------------------------------------------------------------------
# Trajectory deviation (per variant dispatch)
# ---------------------------------------------------------------------------

def _compute_trajectory_deviation_m(
    per_day: list[DayMetricsSummary],
    *,
    atlas: "Atlas | None",
    variant_name: str,
    variant_metadata: dict[str, Any],
    phase_config: dict[str, Any],
) -> float | None:
    """
    对 A (hyperlocal_push) / A' (global_distraction) 计算 intervention 末日
    到 target_location 的 median 距离（across target agents）。

    其它 variant 留 None（留给未来 variant-specific 算子）。
    """
    if atlas is None:
        return None
    if variant_name not in {"hyperlocal_push", "global_distraction"}:
        return None

    target_location = variant_metadata.get("target_location")
    if target_location is None:
        # 从 extensions / parameters 找（variant 实例构造时传入的 field）
        target_location = variant_metadata.get("parameters", {}).get("target_location")
    if target_location is None:
        return None

    try:
        target_area = atlas.get_outdoor_area(target_location)
    except Exception:
        return None
    if target_area is None:
        return None
    target_center = target_area.center

    interv_end = _intervention_end_day(phase_config)
    if interv_end < 0 or interv_end >= len(per_day):
        return None

    end_locations = per_day[interv_end].end_of_day_location_by_agent
    if not end_locations:
        return None

    distances: list[float] = []
    for _agent_id, loc_id in end_locations.items():
        try:
            area = atlas.get_outdoor_area(loc_id)
        except Exception:
            continue
        if area is None:
            continue
        dx = area.center.x - target_center.x
        dy = area.center.y - target_center.y
        distances.append(math.sqrt(dx * dx + dy * dy))

    if not distances:
        return None
    return float(statistics.median(distances))


# ---------------------------------------------------------------------------
# Encounter stats
# ---------------------------------------------------------------------------

def _encounter_stats(per_day: list[DayMetricsSummary]) -> dict[str, float]:
    totals = [d.encounter_count_total for d in per_day]
    pairs = [d.distinct_encounter_pairs for d in per_day]
    return {
        "total": float(sum(totals)),
        "per_day_median": float(statistics.median(totals) if totals else 0.0),
        "per_day_max": float(max(totals) if totals else 0.0),
        "diversity_pairs_total": float(sum(pairs)),
    }


# ---------------------------------------------------------------------------
# Space activation
# ---------------------------------------------------------------------------

def _space_activation(per_day: list[DayMetricsSummary]) -> dict[str, float]:
    totals: dict[str, int] = {}
    for d in per_day:
        for loc, ticks in d.location_dwell_ticks.items():
            totals[loc] = totals.get(loc, 0) + ticks
    return {k: float(v) for k, v in totals.items()}


# ---------------------------------------------------------------------------
# Feed stats from attention delivery log
# ---------------------------------------------------------------------------

def _feed_stats(
    attention_service: "AttentionService | None",
) -> dict[str, int]:
    if attention_service is None:
        return {}
    stats: dict[str, int] = {}

    # export_feed_log 返回 tuple[FeedDeliveryRecord, ...]
    log = attention_service.export_feed_log()
    # 用 feed_index 查 source（delivery record 没存 source）
    for rec in log:
        feed = attention_service.get_feed_item(rec.feed_item_id)
        source = feed.source if feed is not None else "unknown"
        if rec.delivered:
            key = f"{source}.delivered"
        else:
            key = f"{source}.suppressed"
        stats[key] = stats.get(key, 0) + 1
    return stats


def _attention_allocation_proxy(
    attention_service: "AttentionService | None",
    num_agents: int,
    num_days: int,
) -> dict[str, float] | None:
    """
    简化 proxy：
    - `phone_feed` = 每 agent-day 平均 delivered notifications（归一到 [0, 1]
      by capping at 20/day）
    - 其它三项（physical_world / task / conversation）留 None —— 需要
      perception 层扩展，超出本 change。

    返回 None 若 attention_service 为 None 或 num_agents * num_days 为 0。
    """
    if attention_service is None or num_agents == 0 or num_days == 0:
        return None
    log = attention_service.export_feed_log()
    total_delivered = sum(1 for r in log if r.delivered)
    per_agent_day = total_delivered / (num_agents * num_days)
    # 归一化：20 条/agent-day 作为 "phone_feed 完全占满" 参考（对齐
    # GlobalDistractionVariant 的默认 daily_push_count）
    normalised = min(1.0, per_agent_day / 20.0)
    return {"phone_feed_proxy": normalised}


# ---------------------------------------------------------------------------
# Main factory
# ---------------------------------------------------------------------------

def build_run_metrics(
    recorder: "TickMetricsRecorder",
    *,
    multi_day_result: "MultiDayResult",
    atlas: "Atlas | None" = None,
    variant_name: str = "baseline",
    variant_metadata: dict[str, Any] | None = None,
    phase_config: dict[str, Any] | None = None,
) -> RunMetrics:
    """
    从 recorder + MultiDayResult 组装 RunMetrics。

    - `variant_name` / `variant_metadata` / `phase_config` 由调用方（CLI）
      传入；默认 baseline + 14-day PhaseController
    """
    per_day = recorder.snapshot()
    variant_metadata = variant_metadata or {"name": variant_name}
    phase_config = phase_config or {"baseline_days": 4, "intervention_days": 6, "post_days": 4}

    trajectory = _compute_trajectory_deviation_m(
        per_day,
        atlas=atlas,
        variant_name=variant_name,
        variant_metadata=variant_metadata,
        phase_config=phase_config,
    )

    encounter_stats = _encounter_stats(per_day)
    space_activation = _space_activation(per_day)
    feed_stats = _feed_stats(recorder.attention_service)

    num_agents = (
        len(per_day[-1].end_of_day_location_by_agent) if per_day else 0
    )
    attention_ratio = _attention_allocation_proxy(
        recorder.attention_service, num_agents, len(per_day),
    )

    # social-graph-capability：注入 graph 时填 weak_tie_formation_count
    weak_tie_count: int | None = None
    if recorder.social_graph is not None:
        weak_tie_count = recorder.social_graph.weak_count()

    # conversation-capability：注入 conversation 时填 info_propagation_hops dict
    # push-content-individualization：加 within/outside target reach + target_precision
    info_hops: dict[str, int] | None = None
    if recorder.conversation is not None:
        conv = recorder.conversation
        within = conv.total_within_target()
        outside = conv.total_outside_target()
        total_target = within + outside
        target_precision = (within / total_target) if total_target > 0 else 0.0
        info_hops = {
            "info_count_total": conv.info_count(),
            "max_hop_observed": conv.max_hops(),
            "info_reaching_2plus_hops": conv.count_reaching(min_hops=2),
            "avg_reach_per_info": int(round(conv.avg_reach())),
            "info_within_target_reach": within,
            "info_outside_target_reach": outside,
            # target_precision is float; stored as float in dict (RunMetrics
            # info_propagation_hops type is dict[str, int] originally, but
            # we widen via int-cast where possible; keep float here)
            "target_precision": target_precision,  # type: ignore[dict-item]
        }

    # ai-town port (Phase E task 21): pull metrics from injected services
    # via TickMetricsRecorder accessors. All None when those services
    # weren't wired into the recorder — backwards compat.
    reflection_count = _aitown_reflection_count(recorder)
    dialogue_count, dialogue_avg_length = _aitown_dialogue_stats(recorder)
    op_timeout_count, cost_breakdown = _aitown_op_pool_stats(recorder)

    return RunMetrics(
        seed=multi_day_result.seed,
        variant_name=variant_name,
        num_days=len(per_day),
        per_day=tuple(per_day),
        trajectory_deviation_m=trajectory,
        encounter_stats=encounter_stats,
        space_activation=space_activation,
        feed_stats=feed_stats,
        attention_allocation_ratio=attention_ratio,
        weak_tie_formation_count=weak_tie_count,
        info_propagation_hops=info_hops,
        reflection_count=reflection_count,
        dialogue_count=dialogue_count,
        dialogue_avg_length=dialogue_avg_length,
        op_timeout_count=op_timeout_count,
        cost_breakdown=cost_breakdown,
    )


# ---------------------------------------------------------------------------
# ai-town port helpers
# ---------------------------------------------------------------------------


def _aitown_reflection_count(recorder: "TickMetricsRecorder") -> int | None:
    """Sum reflection MemoryEvents across all protagonist memory stores.

    Returns None if memory_service wasn't injected (backwards compat).
    """
    msvc = recorder.memory_service
    if msvc is None:
        return None
    total = 0
    for agent_id in getattr(msvc, "_protagonist_ids", set()):
        events = msvc.all_for(agent_id)
        total += sum(1 for ev in events if ev.kind == "reflection")
    return total


def _aitown_dialogue_stats(
    recorder: "TickMetricsRecorder",
) -> tuple[int | None, float | None]:
    """Return (dialogue_count, avg_message_count) from DialogueService.

    Returns (None, None) if dialogue_service wasn't injected.
    """
    dsvc = recorder.dialogue_service
    if dsvc is None:
        return None, None
    return dsvc.ended_count(), dsvc.avg_message_count()


def _aitown_op_pool_stats(
    recorder: "TickMetricsRecorder",
) -> tuple[int | None, dict[str, float] | None]:
    """Return (timeout_count, cost_breakdown) from OperationPool.

    cost_breakdown structure: {"sonnet": $X, "haiku": $Y, "nano": $Z, "total": $S}
    Token counts are summed from completed_log; per-tier cost computed
    via simple per-MTok rates (best-effort; can be tuned later).
    """
    pool = recorder.operation_pool
    if pool is None:
        return None, None
    timeout_count = len(getattr(pool, "_timeout_log", []))
    completed = getattr(pool, "_completed_log", [])

    # Per-tier $/Mtok rates (input/output averaged for simplicity).
    # Numbers here are illustrative defaults; production should plumb a
    # rate-card from cost-budget service.
    rates_per_mtok: dict[str, float] = {
        "sonnet": 6.0,
        "haiku": 0.8,
        "nano": 0.4,
    }
    tier_for_kind = getattr(
        pool, "_tier_for_kind", {},
    )
    breakdown: dict[str, float] = {"sonnet": 0.0, "haiku": 0.0, "nano": 0.0}
    for result in completed:
        tier = tier_for_kind.get(result.kind, "sonnet")
        tokens = (result.prompt_tokens or 0) + (result.completion_tokens or 0)
        rate = rates_per_mtok.get(tier, 1.0)
        cost = (tokens / 1_000_000.0) * rate
        breakdown[tier] = breakdown.get(tier, 0.0) + cost
    breakdown["total"] = sum(breakdown.values())
    return timeout_count, breakdown


__all__ = ["build_run_metrics"]
