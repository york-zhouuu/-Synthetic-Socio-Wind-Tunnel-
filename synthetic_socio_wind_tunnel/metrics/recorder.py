"""
TickMetricsRecorder — orchestrator.on_tick_end 订阅者

每 tick 采样 per-agent：
- location_id（from Ledger）
- encounter/move/commit counters（from TickResult）

per-day 累积为 `DayMetricsSummary`；`snapshot()` 产出全 run 列表。

Attention metrics 通过 `AttentionService.export_feed_log()` 在 run 结束后
读取聚合（不 per-tick 采，避免重复遍历）。
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from synthetic_socio_wind_tunnel.metrics.models import DayMetricsSummary

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.attention.service import AttentionService
    from synthetic_socio_wind_tunnel.ledger import Ledger
    from synthetic_socio_wind_tunnel.orchestrator.models import TickResult


class _DayBucket:
    """per-day 内部累加器。"""
    __slots__ = (
        "day_index",
        "encounter_count_total",
        "distinct_pairs",
        "move_success",
        "move_fail",
        "location_dwell",
        "end_of_day_locations",
    )

    def __init__(self, day_index: int) -> None:
        self.day_index = day_index
        self.encounter_count_total = 0
        self.distinct_pairs: set[tuple[str, str]] = set()
        self.move_success = 0
        self.move_fail = 0
        self.location_dwell: dict[str, int] = defaultdict(int)
        self.end_of_day_locations: dict[str, str] = {}

    def finalize(self) -> DayMetricsSummary:
        return DayMetricsSummary(
            day_index=self.day_index,
            encounter_count_total=self.encounter_count_total,
            distinct_encounter_pairs=len(self.distinct_pairs),
            move_success_count=self.move_success,
            move_fail_count=self.move_fail,
            location_dwell_ticks=dict(self.location_dwell),
            end_of_day_location_by_agent=dict(self.end_of_day_locations),
        )


class TickMetricsRecorder:
    """orchestrator.on_tick_end 订阅者，跨天累计指标。"""

    __slots__ = ("_ledger", "_attention_service", "_buckets", "_current_day")

    def __init__(
        self,
        *,
        ledger: "Ledger",
        attention_service: "AttentionService | None" = None,
    ) -> None:
        self._ledger = ledger
        self._attention_service = attention_service
        self._buckets: dict[int, _DayBucket] = {}
        self._current_day: int = -1

    @property
    def attention_service(self) -> "AttentionService | None":
        return self._attention_service

    # ---- orchestrator hook ----

    def on_tick_end(self, tick_result: "TickResult") -> None:
        """每 tick 末被 orchestrator 调用。"""
        day_index = tick_result.day_index
        bucket = self._buckets.get(day_index)
        if bucket is None:
            bucket = _DayBucket(day_index)
            self._buckets[day_index] = bucket
            self._current_day = day_index

        # encounter 统计
        bucket.encounter_count_total += len(tick_result.encounter_candidates)
        for enc in tick_result.encounter_candidates:
            # 有序 pair 保证 canonical（小字典序在前）
            pair = tuple(sorted((enc.agent_a, enc.agent_b)))
            bucket.distinct_pairs.add(pair)  # type: ignore[arg-type]

        # commit 统计（move success / fail）
        for commit in tick_result.commits:
            if commit.result.success:
                bucket.move_success += 1
            else:
                bucket.move_fail += 1

        # per-agent current_location（tick 末 ledger 状态；记入 dwell &
        # end_of_day 位置——每 tick 都更新，end_of_day 自然是最后一 tick 的值）
        for agent_id in self._ledger.list_entity_ids():
            entity = self._ledger.get_entity(agent_id)
            if entity is None:
                continue
            loc = entity.location_id
            bucket.location_dwell[loc] += 1
            bucket.end_of_day_locations[agent_id] = loc

    # ---- snapshot / aggregate ----

    def snapshot(self) -> list[DayMetricsSummary]:
        """rollup 所有 bucket 为 DayMetricsSummary list（按 day_index 升序）。"""
        days = sorted(self._buckets.keys())
        return [self._buckets[d].finalize() for d in days]


__all__ = ["TickMetricsRecorder"]
