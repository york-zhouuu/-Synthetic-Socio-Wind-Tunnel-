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
from typing import TYPE_CHECKING, Any

from synthetic_socio_wind_tunnel.metrics.models import DayMetricsSummary

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.attention.service import AttentionService
    from synthetic_socio_wind_tunnel.conversation import ConversationService
    from synthetic_socio_wind_tunnel.ledger import Ledger
    from synthetic_socio_wind_tunnel.orchestrator.models import TickResult
    from synthetic_socio_wind_tunnel.social_graph import SocialGraphService


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

    __slots__ = (
        "_ledger", "_attention_service", "_social_graph", "_conversation",
        "_buckets", "_current_day",
        # ai-town port (Phase E task 21)
        "_dialogue_service", "_memory_service", "_operation_pool",
    )

    def __init__(
        self,
        *,
        ledger: "Ledger",
        attention_service: "AttentionService | None" = None,
        social_graph: "SocialGraphService | None" = None,
        conversation: "ConversationService | None" = None,
        # ai-town port additions — all optional; None when capability not wired.
        dialogue_service: "Any | None" = None,
        memory_service: "Any | None" = None,
        operation_pool: "Any | None" = None,
    ) -> None:
        self._ledger = ledger
        self._attention_service = attention_service
        self._social_graph = social_graph
        self._conversation = conversation
        self._buckets: dict[int, _DayBucket] = {}
        self._current_day: int = -1
        self._dialogue_service = dialogue_service
        self._memory_service = memory_service
        self._operation_pool = operation_pool

    @property
    def attention_service(self) -> "AttentionService | None":
        return self._attention_service

    @property
    def social_graph(self) -> "SocialGraphService | None":
        return self._social_graph

    @property
    def conversation(self) -> "ConversationService | None":
        return self._conversation

    @property
    def dialogue_service(self):
        return self._dialogue_service

    @property
    def memory_service(self):
        return self._memory_service

    @property
    def operation_pool(self):
        return self._operation_pool

    def attach_aitown_services(
        self,
        *,
        dialogue_service=None,
        memory_service=None,
        operation_pool=None,
    ) -> None:
        """Set ai-town service refs after construction (allows wiring
        order: build_recorder → register_on_tick_end → setup_aitown_stack
        → recorder.attach_aitown_services). build_run_metrics will pick
        up these refs to fill reflection_count / dialogue_count etc."""
        if dialogue_service is not None:
            self._dialogue_service = dialogue_service
        if memory_service is not None:
            self._memory_service = memory_service
        if operation_pool is not None:
            self._operation_pool = operation_pool

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
        """rollup 所有 bucket 为 DayMetricsSummary list（按 day_index 升序）。

        若 social_graph 注入：每天的 summary 含累积 tie 指标（截至该 day 末
        的整张图状态）。注：因 graph 是 in-memory 单实例，"day N 末"的快照
        实际上等于 "现在"——日级 tie_count_* 严格意义上是"截至 N 末的累积"，
        new_ties_today 是 first_seen_day == N 的 tie 数。
        """
        days = sorted(self._buckets.keys())
        out: list[DayMetricsSummary] = []
        for d in days:
            base = self._buckets[d].finalize()
            if self._social_graph is not None:
                end_of_day_locs = base.end_of_day_location_by_agent
                num_agents = max(1, len(end_of_day_locs))
                ties_per_agent = sum(
                    len(self._social_graph.ties_for(aid))
                    for aid in end_of_day_locs.keys()
                )
                base = base.model_copy(update={
                    "tie_count_total": self._social_graph.total_count(),
                    "tie_count_weak": self._social_graph.weak_count(),
                    "tie_count_strong": self._social_graph.strong_count(),
                    "new_ties_today": self._social_graph.new_ties_on_day(d),
                    "avg_ties_per_agent": ties_per_agent / num_agents,
                })
            if self._conversation is not None:
                base = base.model_copy(update={
                    "info_origins_today": self._conversation.origins_on_day(d),
                    "info_shares_today": self._conversation.shares_on_day(d),
                    "info_reaching_2plus_today":
                        self._conversation.reaching_2plus_on_day(d),
                    "avg_hops_today": self._conversation.avg_hops_on_day(d),
                    "info_target_reach_today":
                        self._conversation.info_target_reach_today(d),
                })
            out.append(base)
        return out


__all__ = ["TickMetricsRecorder"]
