"""
MemoryService — memory 能力的主入口。

职责：
- per-agent MemoryStore 管理
- record / retrieve / recent / all_for 便捷接口
- process_tick：消费 TickResult + AttentionService，写入 memory，
  触发 should_replan → planner.replan
- attach_to(orchestrator)：一键注册 on_tick_end hook
- run_daily_summary：每 agent 1 次 LLM 调用
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime
from typing import TYPE_CHECKING, Any, Mapping

from synthetic_socio_wind_tunnel.memory.carryover import CarryoverContext
from synthetic_socio_wind_tunnel.memory.embedding import EmbeddingProvider, NullEmbedding
from synthetic_socio_wind_tunnel.memory.models import (
    DailySummary,
    MemoryEvent,
    MemoryQuery,
)
from synthetic_socio_wind_tunnel.memory.retrieval import MemoryRetriever
from synthetic_socio_wind_tunnel.memory.store import MemoryStore

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.agent import AgentRuntime, Planner
    from synthetic_socio_wind_tunnel.agent.planner import LLMClient
    from synthetic_socio_wind_tunnel.atlas import Atlas
    from synthetic_socio_wind_tunnel.attention import AttentionService, FeedItem
    from synthetic_socio_wind_tunnel.conversation import ConversationService
    from synthetic_socio_wind_tunnel.memory.embeddings_cache import EmbeddingsCache
    from synthetic_socio_wind_tunnel.memory.importance import ImportanceScorer
    from synthetic_socio_wind_tunnel.memory.reflection import ReflectionService
    from synthetic_socio_wind_tunnel.orchestrator import Orchestrator, TickResult
    from synthetic_socio_wind_tunnel.social_graph import SocialGraphService


# realism-attention-rebalance：把 atlas 的细分 area_type 归一化到 prompt
# 用的 6 类标签。
_LOCATION_KIND_MAP = {
    "park": "park",
    "garden": "park",
    "playground": "park",
    "plaza": "park",
    "street": "street",
    "parking": "street",
}


class MemoryService:
    """Memory capability 的对外入口。"""

    __slots__ = (
        "_stores",
        "_embedding",
        "_retriever",
        "_attention_service",
        "_atlas",
        "_social_graph",
        "_conversation",
        "_consumed_feed_item_ids",
        "_event_counter",
        "_replan_count_today",
        "_replan_no_op_count_today",
        "_last_day_index",
        "_rng",
        # ai-town port (Phase B)
        "_importance_scorer",
        "_reflection_service",
        "_embeddings_cache",
        "_last_reflection_time",
        "_protagonist_ids",
        "_noticing_seed",
    )

    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        retriever_weights: dict[str, float] | None = None,
        attention_service: "AttentionService | None" = None,
        atlas: "Atlas | None" = None,
        social_graph: "SocialGraphService | None" = None,
        conversation: "ConversationService | None" = None,
        seed: int | None = None,
        importance_scorer: "ImportanceScorer | None" = None,
        reflection_service: "ReflectionService | None" = None,
        embeddings_cache: "EmbeddingsCache | None" = None,
        protagonist_ids: tuple[str, ...] = (),
        retrieval_mode: str = "legacy",
    ) -> None:
        # conversation 必须与 social_graph 同时注入（design D3）；否则
        # process_tick 调用 conversation.process_tick 时会缺 tie 信息
        if conversation is not None and social_graph is None:
            raise ValueError(
                "conversation requires social_graph to be injected too "
                "(conversation.process_tick uses tie strength); "
                "construct SocialGraphService alongside ConversationService"
            )
        self._stores: dict[str, MemoryStore] = {}
        self._embedding: EmbeddingProvider = embedding_provider or NullEmbedding()
        self._retriever = MemoryRetriever(
            weights=retriever_weights, mode=retrieval_mode,  # type: ignore[arg-type]
        )
        self._attention_service = attention_service
        # 用于 process_tick 装配 interrupt_ctx 的 current_location_kind
        # （atlas=None 时此字段降级为 "other"）。
        self._atlas = atlas
        # social-graph-capability：注入时把 encounter 同步累积成 pairwise tie，
        # 并让 nearby_agents.is_familiar 走 graph 的 strength 阈值（取代 memory 近似）
        self._social_graph = social_graph
        # conversation-capability：注入时 push delivery 转 Information origin，
        # encounter 触发概率门 propagation
        self._conversation = conversation
        # D.1 修复：per-agent feed_item_id 去重集合。
        # 旧实现用 last_seen_timestamp 过滤；AttentionService.notifications_for
        # 的 `>=` 语义会让同 timestamp 的 notification 在下一次 tick 被
        # 重新 ingest。改为直接记住 "这个 agent 已经 ingest 过的 feed_item_id"。
        self._consumed_feed_item_ids: dict[str, set[str]] = {}
        self._event_counter = 0
        # realism-attention-rebalance：per-agent 当日 replan 次数（疲劳衰减）
        # B7 fix: split into "plan-changed" (replan_count_today) vs
        # "fallback / unchanged" (replan_no_op_count_today). Only the first
        # counts toward the dose-response cap on agent fatigue.
        self._replan_count_today: dict[str, int] = {}
        self._replan_no_op_count_today: dict[str, int] = {}
        self._last_day_index: int = -1
        # seeded rng for should_replan probabilistic gate
        self._rng = random.Random(seed) if seed is not None else random.Random()
        # add-attention-induced-nearby-blindness: store raw seed so the
        # noticing gate's hash-based RNG produces reproducible decisions.
        self._noticing_seed: int = seed if seed is not None else 0
        # ai-town port (Phase B): protagonist set + reflection bookkeeping
        self._importance_scorer = importance_scorer
        self._reflection_service = reflection_service
        self._embeddings_cache = embeddings_cache
        self._protagonist_ids: set[str] = set(protagonist_ids)
        self._last_reflection_time: dict[str, datetime] = {}

    # ---- Snapshot (tick-level-resume 2026-05-16) ----

    def to_snapshot_state(self) -> dict[str, Any]:
        """Serialize all mutable per-agent state.

        MemoryStore: only events list serialized (4 reverse indices are
        derived and rebuilt on restore via `append`). Other fields:
        per-agent replan counters, consumed feed_item_ids, event_counter,
        last_day_index, last_reflection_time, rng state.

        Service references (atlas / social_graph / conversation /
        attention_service) are NOT serialized — caller reattaches.
        """
        from dataclasses import asdict
        from synthetic_socio_wind_tunnel.run_resilience.state_snapshot import (
            _rng_state_to_json,
        )

        agent_events: dict[str, list[dict[str, Any]]] = {}
        for aid, store in self._stores.items():
            agent_events[aid] = [_event_to_json(ev) for ev in store.all()]

        return {
            "agent_events": agent_events,
            "consumed_feed_item_ids": {
                aid: sorted(ids) for aid, ids in self._consumed_feed_item_ids.items()
            },
            "event_counter": self._event_counter,
            "replan_count_today": dict(self._replan_count_today),
            "replan_no_op_count_today": dict(self._replan_no_op_count_today),
            "last_day_index": self._last_day_index,
            "last_reflection_time": {
                aid: t.isoformat() for aid, t in self._last_reflection_time.items()
            },
            "rng_state": _rng_state_to_json(self._rng.getstate()),
            "noticing_seed": self._noticing_seed,
        }

    def from_snapshot_state(self, state: dict[str, Any]) -> None:
        """Replace per-agent state from snapshot. Existing state discarded."""
        from synthetic_socio_wind_tunnel.memory.models import MemoryEvent
        from synthetic_socio_wind_tunnel.run_resilience.state_snapshot import (
            _rng_state_from_json,
        )

        if not isinstance(state, dict):
            raise ValueError(
                f"MemoryService.from_snapshot_state expects dict, "
                f"got {type(state).__name__}",
            )

        self._stores = {}
        for aid, events in (state.get("agent_events") or {}).items():
            store = MemoryStore()
            for ev_data in events:
                store.append(_event_from_json(ev_data))
            self._stores[aid] = store

        self._consumed_feed_item_ids = {
            aid: set(ids) for aid, ids in (state.get("consumed_feed_item_ids") or {}).items()
        }
        self._event_counter = int(state.get("event_counter", 0))
        self._replan_count_today = dict(state.get("replan_count_today") or {})
        self._replan_no_op_count_today = dict(
            state.get("replan_no_op_count_today") or {},
        )
        self._last_day_index = int(state.get("last_day_index", -1))

        self._last_reflection_time = {}
        for aid, iso in (state.get("last_reflection_time") or {}).items():
            try:
                self._last_reflection_time[aid] = datetime.fromisoformat(iso)
            except (TypeError, ValueError):
                pass

        rng_state = state.get("rng_state")
        if rng_state is not None:
            try:
                self._rng.setstate(_rng_state_from_json(rng_state))
            except Exception:  # noqa: BLE001
                pass
        self._noticing_seed = int(state.get("noticing_seed", self._noticing_seed))

    def _store_for(self, agent_id: str) -> MemoryStore:
        if agent_id not in self._stores:
            self._stores[agent_id] = MemoryStore()
        return self._stores[agent_id]

    def _is_encounter_noticed(
        self, agent_a: str, agent_b: str, *, tick: int, day_index: int,
        shared_location_id: str | None = None,
        a_movement_count: int = 0,
        b_movement_count: int = 0,
    ) -> bool:
        """noticing gate combining attention + polygon size + transit discount.

        B6 fix: if either agent passed through many segments this tick
        (driving through), discount noticing — they're transiting, not
        settling. transit_factor = 1 / (1 + max(a_moves, b_moves) / 5).
        """
        if self._attention_service is None:
            return True
        from synthetic_socio_wind_tunnel.attention.noticing import noticed_pair
        a_attn = self._attention_service.get_phone_attention(agent_a)
        b_attn = self._attention_service.get_phone_attention(agent_b)
        # B6 transit penalty: if either agent moved many segments this tick,
        # treat colocation as drive-by rather than settled encounter.
        transit_factor = 1.0 / (1.0 + max(a_movement_count, b_movement_count) / 5.0)
        # Encode into attention max so the existing formula picks it up:
        # higher effective attn → lower noticing prob.
        effective_a = a_attn + (1.0 - transit_factor) * 0.5
        effective_b = b_attn + (1.0 - transit_factor) * 0.5
        pair = tuple(sorted((agent_a, agent_b)))

        # A3 fix: compute polygon extent for the shared location so large
        # parks discount noticing. atlas not always available — None bypass.
        polygon_extent = None
        if shared_location_id is not None and self._atlas is not None:
            loc = (
                self._atlas.get_outdoor_area(shared_location_id)
                or self._atlas.get_building(shared_location_id)
            )
            if loc is not None and loc.polygon and loc.polygon.vertices:
                xs = [v.x for v in loc.polygon.vertices]
                ys = [v.y for v in loc.polygon.vertices]
                polygon_extent = max(max(xs) - min(xs), max(ys) - min(ys))

        return noticed_pair(
            effective_a, effective_b,
            seed=self._noticing_seed, day=day_index, tick=tick, pair=pair,
            polygon_extent_m=polygon_extent,
        )

    def _next_event_id(self, agent_id: str, tick: int) -> str:
        self._event_counter += 1
        return f"ev_{agent_id}_{tick}_{self._event_counter}"

    # ---- 写入 / 查询 ----

    def record(self, agent_id: str, event: MemoryEvent) -> MemoryEvent:
        """
        写入 memory。若 provider 不是 NullEmbedding 且 event.embedding 为空，
        生成 embedding（替换为新 event 副本）。
        """
        if event.embedding is None and not isinstance(self._embedding, NullEmbedding):
            emb = self._embedding.embed(event.content)
            from dataclasses import replace
            event = replace(event, embedding=emb)
        self._store_for(agent_id).append(event)
        return event

    def retrieve(
        self,
        agent_id: str,
        query: MemoryQuery,
        top_k: int = 10,
    ) -> list[MemoryEvent]:
        store = self._stores.get(agent_id)
        if store is None:
            return []
        return self._retriever.retrieve(store, query, top_k=top_k)

    def recent(self, agent_id: str, last_ticks: int = 1) -> list[MemoryEvent]:
        """
        返回最近 `last_ticks` 个 tick 范围的事件。

        锚点：store 内最大 tick。若后续 tick 没有新事件（退化场景），
        max_tick 会"卡住"导致旧事件反复被视为最新——真实 orchestrator
        每 tick 有 action 写入不会卡；退化/测试场景用 `events_at_tick`。
        """
        store = self._stores.get(agent_id)
        if store is None:
            return []
        all_events = store.all()
        if not all_events:
            return []
        max_tick = max(e.tick for e in all_events)
        min_tick = max_tick - last_ticks + 1
        return [e for e in all_events if e.tick >= min_tick]

    def events_at_tick(self, agent_id: str, tick: int) -> list[MemoryEvent]:
        """返回 agent 在**指定** tick 的所有事件（不依赖 max_tick 锚点）。"""
        store = self._stores.get(agent_id)
        if store is None:
            return []
        return [e for e in store.all() if e.tick == tick]

    def all_for(self, agent_id: str) -> list[MemoryEvent]:
        store = self._stores.get(agent_id)
        if store is None:
            return []
        return list(store.all())

    # ---- 跨日检索（multi-day-simulation 引入） ----

    def get_daily_summary(
        self, agent_id: str, day_index: int,
    ) -> DailySummary | None:
        """返回该 agent 在指定 day_index 的 DailySummary；缺失为 None。"""
        store = self._stores.get(agent_id)
        if store is None:
            return None
        for ev in store.by_kind("daily_summary"):
            if ev.day_index == day_index:
                return DailySummary(
                    agent_id=agent_id,
                    date=ev.simulated_time.date().isoformat(),
                    summary_text=ev.content,
                )
        return None

    def get_recent_daily_summaries(
        self,
        agent_id: str,
        *,
        last_n_days: int = 3,
        ref_day_index: int | None = None,
    ) -> tuple[DailySummary, ...]:
        """
        返回从 ref_day_index - last_n_days 到 ref_day_index - 1（含端）的
        历史摘要（不含 ref_day_index 本身），按 day_index 升序。

        ref_day_index=None 时取 store 中最大 daily_summary day_index 作参考。
        """
        store = self._stores.get(agent_id)
        if store is None:
            return ()
        summaries_ev = store.by_kind("daily_summary")
        if not summaries_ev:
            return ()

        if ref_day_index is None:
            ref_day_index = max(ev.day_index for ev in summaries_ev)

        lo = ref_day_index - last_n_days
        hi = ref_day_index  # exclusive
        selected = [
            ev for ev in summaries_ev
            if lo <= ev.day_index < hi
        ]
        selected.sort(key=lambda e: e.day_index)
        return tuple(
            DailySummary(
                agent_id=agent_id,
                date=ev.simulated_time.date().isoformat(),
                summary_text=ev.content,
            )
            for ev in selected
        )

    def get_carryover_context(
        self,
        agent_id: str,
        *,
        current_day_index: int,
    ) -> CarryoverContext:
        """
        组装 planner 次日 prompt 所需的历史上下文。

        - yesterday_summary: day_index == current-1（若有）
        - recent_reflections: last 3 days（不含 yesterday_summary）
        - pending_task_anchors: task_received 且 importance top 5
        """
        if current_day_index <= 0:
            # day 0：没有历史
            return CarryoverContext()

        yesterday = self.get_daily_summary(agent_id, current_day_index - 1)

        # 取 (current-4, current-1) 范围的 3 条（不含 current-1）
        # 即 day_index ∈ [current-4, current-2]
        recent = self.get_recent_daily_summaries(
            agent_id,
            last_n_days=3,
            ref_day_index=current_day_index - 1,
        )

        store = self._stores.get(agent_id)
        pending: tuple[MemoryEvent, ...] = ()
        if store is not None:
            task_evs = list(store.by_kind("task_received"))
            # 按 importance 降序，top 5
            task_evs.sort(key=lambda e: e.importance, reverse=True)
            pending = tuple(task_evs[:5])

        return CarryoverContext(
            yesterday_summary=yesterday,
            recent_reflections=recent,
            pending_task_anchors=pending,
        )

    # ---- orchestrator 集成 ----

    # 注：没有 attach_to 方法。MemoryService 不知道 agents 字典与 planner
    # 实例的所有权；调用方持有它们，手工注册一个 on_tick_end callback 即可：
    #   orch.register_on_tick_end(
    #       lambda tr: memory.process_tick(tr, agents_by_id, planner)
    #   )
    # 见 docs/agent_system/09-memory-and-replan.md 的集成示例。

    def process_tick(
        self,
        tick_result: "TickResult",
        agents: Mapping[str, "AgentRuntime"],
        planner: "Planner | None" = None,
    ) -> list[tuple[str, MemoryEvent]]:
        """
        消费 TickResult + AttentionService：写入 per-agent memory，
        触发 should_replan 并在必要时调 planner.replan。

        Returns:
            list of (agent_id, trigger_event) for replans actually performed.
        """
        tick = tick_result.tick_index
        sim_time = tick_result.simulated_time
        day_index = tick_result.day_index

        # add-attention-induced-nearby-blindness: decay phone_attention once
        # per tick. Notification deliveries (which raise attention) happen
        # later in process_tick, so decay first preserves expected dynamics.
        if self._attention_service is not None:
            self._attention_service.tick_decay_all()

        # 1. 从 commits 派生 action events
        for commit in tick_result.commits:
            self._record_action(
                agent_id=commit.agent_id,
                commit=commit,
                tick=tick,
                sim_time=sim_time,
                day_index=day_index,
            )

        # 2. 从 encounter_candidates 派生双向 encounter events
        #    + 若 social_graph 注入，同步累积 pairwise tie
        # add-attention-induced-nearby-blindness: only attention-gated
        # ("noticed") encounters grow weak ties. Physical co-locations still
        # record as memory events but skip strength accumulation.
        # B6 fix: build per-agent movement count for this tick (transit penalty)
        moves_this_tick: dict[str, int] = {}
        for agent_id, locs in tick_result.movement_traces:
            moves_this_tick[agent_id] = len(locs)

        for enc in tick_result.encounter_candidates:
            # A3 fix: pick first shared location for polygon-size discount
            shared_loc = enc.shared_locations[0] if enc.shared_locations else None
            noticed = self._is_encounter_noticed(
                enc.agent_a, enc.agent_b, tick=tick, day_index=day_index,
                shared_location_id=shared_loc,
                a_movement_count=moves_this_tick.get(enc.agent_a, 0),
                b_movement_count=moves_this_tick.get(enc.agent_b, 0),
            )
            for me, other in ((enc.agent_a, enc.agent_b), (enc.agent_b, enc.agent_a)):
                event = MemoryEvent(
                    event_id=self._next_event_id(me, tick),
                    agent_id=me,
                    tick=tick,
                    simulated_time=sim_time,
                    kind="encounter",
                    content=f"ran into {other} at {', '.join(enc.shared_locations)}",
                    actor_id=other,
                    location_id=enc.shared_locations[0] if enc.shared_locations else None,
                    urgency=0.3,
                    importance=0.5,
                    participants=(other,),
                    tags=("encounter", "noticed" if noticed else "unnoticed"),
                    day_index=day_index,
                )
                self.record(me, event)
            # social-graph-capability: pairwise tie accumulation.
            # noticed → grows strength; unnoticed → physical-only counter.
            if self._social_graph is not None:
                if noticed:
                    self._social_graph.record_noticed_encounter(
                        enc.agent_a, enc.agent_b,
                        tick=tick, day_index=day_index,
                    )
                else:
                    self._social_graph.record_physical_encounter(
                        enc.agent_a, enc.agent_b,
                        tick=tick, day_index=day_index,
                    )

        # 3. 从 AttentionService 派生 notification / task_received events
        #    + 若 conversation 注入：把每条新 ingested 的 push 转 Information
        #      并 record_origin 进对话层
        new_ingested_by_agent: dict[str, list[tuple[MemoryEvent, "FeedItem"]]] = {}
        if self._attention_service is not None:
            for agent_id in agents:
                new_ingested_by_agent[agent_id] = self._ingest_notifications(
                    agent_id, tick, sim_time, day_index=day_index,
                )
        if self._conversation is not None:
            from synthetic_socio_wind_tunnel.conversation import Information
            for agent_id, events in new_ingested_by_agent.items():
                for memory_event, feed_item in events:
                    # push-content-individualization：用 topic_id 作为 info_id key
                    # 让 N 个 personalized FeedItems 聚合成同一 Information
                    info_key = feed_item.topic_id or feed_item.feed_item_id
                    info = Information(
                        info_id=f"info_{info_key}",
                        content=feed_item.content,
                        category="push",
                        salience=self._salience_from_feed(feed_item),
                        origin_tick=tick,
                        origin_agent_id=agent_id,
                        origin_day_index=day_index,
                        source_feed_item_id=feed_item.feed_item_id,
                        target_audience_tags=feed_item.target_audience_tags,
                    )
                    self._conversation.record_origin(info, agent_id, tick=tick)
            # 让信息在本 tick 的 encounters 上按概率传播
            self._conversation.process_tick(
                tick_result, self._social_graph,
                sim_day=day_index, agents=agents,
            )

        # 4. Replan 检查 & 执行
        replans: list[tuple[str, MemoryEvent]] = []
        if planner is None:
            return replans

        # realism-attention-rebalance：跨日 boundary 时清零 replan 计数（疲劳衰减重置）
        if self._last_day_index != -1 and day_index != self._last_day_index:
            self._replan_count_today.clear()
            self._replan_no_op_count_today.clear()
        self._last_day_index = day_index

        for agent_id, agent in agents.items():
            # 用 events_at_tick 而不是 recent(last_ticks=1)：
            # 后者基于 max_tick，在"没有其它事件写入"时会把旧 tick 的
            # 事件反复视为 recent，导致 replan 重复触发。
            recent = self.events_at_tick(agent_id, tick_result.tick_index)
            if not recent:
                continue
            current_step = agent.plan.current() if agent.plan is not None else None
            elapsed_min = agent.current_step_elapsed_min(sim_time)
            replan_count = self._replan_count_today.get(agent_id, 0)
            for candidate in recent:
                if agent.should_replan(
                    recent, candidate,
                    current_step=current_step,
                    current_step_elapsed_min=elapsed_min,
                    replan_count_today=replan_count,
                    rng=self._rng,
                    tick=tick,
                    simulated_time=sim_time,
                ):
                    interrupt_ctx = {
                        "trigger_event": candidate,
                        "recent_memories": recent,
                        "current_time": sim_time,
                        "current_step": current_step,
                        "current_location_kind": self._location_kind_for(agent),
                        "nearby_agents": self._nearby_agents_for(
                            agent_id, tick_result, agent,
                        ),
                    }
                    # A1: render perception 一次给 Planner.replan 看。
                    # agent.perception_pipeline / agent._perception 任一存在时
                    # render；否则降级 None（兼容现有 1190 测试基线）。
                    perceptual_view = self._render_perception_for(agent)
                    try:
                        new_plan, plan_changed = asyncio.run(planner.replan(
                            agent.profile, agent.plan, interrupt_ctx,
                            perceptual_context=perceptual_view,
                        ))
                        agent.plan = new_plan
                        if plan_changed:
                            replans.append((agent_id, candidate))
                            # 累加当日 replan 计数（仅 plan 真改才计 — B7 fix）
                            self._replan_count_today[agent_id] = replan_count + 1
                        else:
                            # plan 未改：fallback / 空 LLM 输出。计入 no-op
                            no_op_n = self._replan_no_op_count_today.get(
                                agent_id, 0,
                            )
                            self._replan_no_op_count_today[agent_id] = no_op_n + 1
                    except Exception:
                        # Planner.replan 内部已有 fallback；外层再兜一次保险
                        pass
                    break  # 一 tick 内至多一次 replan / agent

        return replans

    def _render_perception_for(self, agent: "AgentRuntime") -> Any:
        """A1 / realism-perception-loop: render SubjectiveView for replan prompt.

        Returns SubjectiveView | None — None when agent's perception pipeline
        not injected (backwards compat with current 1190 test baseline).
        """
        pipeline = getattr(agent, "perception_pipeline", None) or getattr(
            agent, "_perception", None,
        )
        if pipeline is None:
            return None
        try:
            from synthetic_socio_wind_tunnel.perception.models import (
                ObserverContext,
            )
            ctx_kwargs = agent.build_observer_context()
            obs_ctx = ObserverContext(**ctx_kwargs)
            return pipeline.render(obs_ctx)
        except Exception:
            return None

    def replan_no_op_count_today_total(self) -> int:
        """Sum of per-agent fallback / no-op replans today.

        Counter resets on day boundary; sample before next day starts to
        capture the day's total. Used by suite-wiring's metric writer to
        populate `RunMetrics.extensions.replan_no_op_count` (B7 fix).
        """
        return sum(self._replan_no_op_count_today.values())

    # ---- realism-attention-rebalance helpers ----

    def _location_kind_for(self, agent: "AgentRuntime") -> str:
        """归一化 agent 当前 location 的 area_type 到 6 类 prompt 标签。

        atlas=None 或 location 不可解析时返回 "other"。
        """
        if self._atlas is None:
            return "other"
        loc_id = agent.current_location
        if not loc_id:
            return "other"
        # home_location 特判
        if loc_id == agent.profile.home_location:
            return "home"
        # 走 atlas 查询；可能是 outdoor_area 或 building
        outdoor = self._atlas._region.outdoor_areas.get(loc_id)
        if outdoor is not None:
            kind = _LOCATION_KIND_MAP.get(outdoor.area_type, "other")
            return kind
        # 检 buildings — building.building_type 用同一种归一化逻辑
        building = self._atlas._region.buildings.get(loc_id)
        if building is not None:
            t = (building.building_type or "").lower()
            if "cafe" in t or "restaurant" in t or "food" in t:
                return "cafe"
            if "office" in t or "commercial" in t:
                return "office"
            if "residential" in t or "house" in t or "apartment" in t:
                return "home"
            return "other"
        return "other"

    def _nearby_agents_for(
        self,
        agent_id: str,
        tick_result: "TickResult",
        agent: "AgentRuntime",
    ) -> list:
        """从本 tick 的 encounter_candidates 装配 NearbyAgent 列表。

        is_familiar 来源（social-graph-capability D5）：
        - 注入了 social_graph：strength > WEAK_TIE_THRESHOLD 才算 familiar
          （阈值化判断；过去 1 次 encounter 不足以构成"认识"）
        - 未注入：降级到 memory 近似（actor_id 是否曾出现过）
        """
        from synthetic_socio_wind_tunnel.agent import NearbyAgent

        if self._social_graph is not None:
            familiar_ids: set[str] = self._social_graph.familiar_with(agent_id)
        else:
            # 降级路径：memory 里有 encounter actor_id 即算 familiar（旧行为）
            familiar_ids = set()
            store = self._stores.get(agent_id)
            if store is not None:
                for ev in store.by_kind("encounter"):
                    if ev.actor_id:
                        familiar_ids.add(ev.actor_id)

        nearby: list = []
        for enc in tick_result.encounter_candidates:
            other: str | None = None
            if enc.agent_a == agent_id:
                other = enc.agent_b
            elif enc.agent_b == agent_id:
                other = enc.agent_a
            if other is None:
                continue
            nearby.append(NearbyAgent(is_familiar=other in familiar_ids))
        return nearby

    def _record_action(self, *, agent_id, commit, tick, sim_time, day_index: int = 0) -> None:
        """From a CommitRecord produce an action MemoryEvent."""
        intent_name = type(commit.intent).__name__
        result_ok = commit.result.success
        content = (
            f"{intent_name} {'succeeded' if result_ok else 'failed'}"
            f"{': ' + commit.result.message if commit.result.message else ''}"
        )
        event = MemoryEvent(
            event_id=self._next_event_id(agent_id, tick),
            agent_id=agent_id,
            tick=tick,
            simulated_time=sim_time,
            kind="action",
            content=content,
            location_id=None,
            urgency=0.0,  # 自己动作不是 replan 触发
            importance=0.3 if result_ok else 0.6,  # 失败更值得记住
            tags=("action", intent_name.lower()),
            day_index=day_index,
        )
        self.record(agent_id, event)

    def _ingest_notifications(
        self, agent_id: str, tick: int, sim_time: datetime, *, day_index: int = 0,
    ) -> list[tuple[MemoryEvent, "FeedItem"]]:
        """
        Pull new-to-this-agent notifications and record them as MemoryEvents.

        D.1 修复：用 per-agent `set[feed_item_id]` 去重而非 timestamp since。

        Returns list of (event, feed_item) for the events ingested in this
        tick — caller (process_tick) uses this to feed conversation origins
        without re-scanning the memory store.
        """
        assert self._attention_service is not None
        consumed = self._consumed_feed_item_ids.setdefault(agent_id, set())
        all_events = self._attention_service.notifications_for(agent_id)
        new_ingested: list[tuple[MemoryEvent, "FeedItem"]] = []
        for ne in all_events:
            feed_item_id = ne.feed_item_id
            if feed_item_id in consumed:
                continue  # 已经消费过，跳过
            feed_item = self._attention_service.get_feed_item(feed_item_id)
            if feed_item is None:
                # Feed item not registered; skip rather than crash
                continue
            kind = "task_received" if feed_item.category == "task" else "notification"
            event = MemoryEvent(
                event_id=self._next_event_id(agent_id, tick),
                agent_id=agent_id,
                tick=tick,
                simulated_time=sim_time,
                kind=kind,
                content=feed_item.content,
                actor_id=None,
                location_id=None,
                urgency=feed_item.urgency,
                importance=0.6,
                tags=(feed_item.source, feed_item.category),
                day_index=day_index,
            )
            self.record(agent_id, event)
            consumed.add(feed_item_id)
            new_ingested.append((event, feed_item))
        return new_ingested

    # ---- ai-town port (Phase B): reflection driver ----

    async def maybe_reflect(
        self,
        agent_id: str,
        agent_name: str,
        *,
        current_tick: int,
        simulated_time: datetime,
        day_index: int,
        force_for_day_end: bool = False,
    ) -> list[MemoryEvent]:
        """Run reflection if (a) ai-town threshold passed, or (b) force=True.

        Only protagonist agents (in self._protagonist_ids) actually reflect;
        scripted agents return empty list immediately. Reflection events are
        recorded into the agent's memory store; returns the new events for
        introspection (inspector / metrics).

        Idempotent within a tick: if `_last_reflection_time[agent_id]` is the
        same as `simulated_time`, reflection is skipped.
        """
        if self._reflection_service is None:
            return []
        if agent_id not in self._protagonist_ids:
            return []
        last_ref = self._last_reflection_time.get(agent_id)
        if last_ref == simulated_time:
            return []  # already reflected this tick
        recent = self.recent(agent_id, last_ticks=288)
        # Filter out reflection events from the input window — we don't want
        # reflections-of-reflections (matches ai-town behavior implicitly:
        # their getReflectionMemories doesn't filter, but excluding helps
        # avoid feedback loops in our higher-frequency tick).
        recent = [e for e in recent if e.kind != "reflection"]
        if not self._reflection_service.should_reflect(
            recent,
            last_reflection_time=last_ref,
            force_for_day_end=force_for_day_end,
        ):
            return []
        new_events = await self._reflection_service.reflect(
            agent_id, agent_name, recent,
            current_tick=current_tick,
            simulated_time=simulated_time,
            day_index=day_index,
            event_id_factory=self._next_event_id,
        )
        for ev in new_events:
            self.record(agent_id, ev)
        self._last_reflection_time[agent_id] = simulated_time
        return new_events

    @staticmethod
    def _salience_from_feed(feed: "FeedItem") -> float:
        """Map a FeedItem to conversation salience ∈ [0, 1] (design D4)."""
        if feed.hyperlocal_radius is not None and feed.hyperlocal_radius < 1000:
            return 0.8
        cat = (feed.category or "").lower()
        if cat in ("local_news", "task"):
            return 0.6
        if cat == "commercial_push":
            return 0.5
        if cat in ("global_news", "global_distraction"):
            return 0.3
        return 0.4

    # ---- Daily summary ----

    async def run_daily_summary(
        self,
        agents: Mapping[str, "AgentRuntime"],
        llm_client: "LLMClient",
    ) -> dict[str, DailySummary]:
        """
        每 agent 1 次 LLM 调用，产出 DailySummary 并回填 tags / importance。
        LLM 失败时 fallback：summary_text="(unavailable)"，不抛异常。
        """
        summaries: dict[str, DailySummary] = {}
        for agent_id, agent in agents.items():
            all_events = self.all_for(agent_id)
            if not all_events:
                summaries[agent_id] = DailySummary(
                    agent_id=agent_id,
                    date=str(
                        all_events[0].simulated_time.date() if all_events else ""
                    ),
                    summary_text="(no events)",
                )
                continue

            # 只拿当前"最大 day_index"那一天的事件来总结——避免把历史天的
            # 事件重复 summarize（多日 run 关键：每天独立 daily_summary）
            current_day_index = max(ev.day_index for ev in all_events)
            today_events = [
                ev for ev in all_events
                if ev.day_index == current_day_index and ev.kind != "daily_summary"
            ]
            if not today_events:
                # 没有当日非-summary 事件（可能是 run 起步无动作）；跳过
                continue

            date_str = str(today_events[0].simulated_time.date())
            prompt = self._build_summary_prompt(agent, today_events)
            try:
                # capability 1.9 follow-up (2026-05-19): D2 attempt 5
                # caught seed42 pf hanging here at day-11 end — the
                # underlying httpx timeout failed (half-open TCP to
                # DeepSeek). asyncio.wait_for is the only reliable
                # bound. 60s matches reflection (same scale: per-agent
                # one LLM call producing summary text).
                raw = await asyncio.wait_for(
                    llm_client.generate(
                        prompt, model=agent.profile.base_model
                    ),
                    timeout=60.0,
                )
                summary = DailySummary(
                    agent_id=agent_id,
                    date=date_str,
                    summary_text=raw.strip(),
                )
            except asyncio.TimeoutError:
                summary = DailySummary(
                    agent_id=agent_id,
                    date=date_str,
                    summary_text="(daily summary timed out)",
                )
            except Exception:
                summary = DailySummary(
                    agent_id=agent_id,
                    date=date_str,
                    summary_text="(unavailable)",
                )
            summaries[agent_id] = summary

            # 写一条 daily_summary 事件作为索引入口；day_index 继承当天
            self.record(agent_id, MemoryEvent(
                event_id=self._next_event_id(agent_id, -1),
                agent_id=agent_id,
                tick=-1,  # special "end-of-day" tick
                simulated_time=today_events[-1].simulated_time,
                kind="daily_summary",
                content=summary.summary_text,
                urgency=0.0,
                importance=0.8,
                tags=("summary",),
                day_index=current_day_index,
            ))
        return summaries

    @staticmethod
    def _build_summary_prompt(
        agent: "AgentRuntime",
        events: list[MemoryEvent],
    ) -> str:
        lines = [f"{agent.profile.name} 一天的经历，请用 3-5 句话概括："]
        for e in events[-50:]:  # 最近 50 条避免 prompt 爆炸
            lines.append(f"- [{e.simulated_time.strftime('%H:%M')}] {e.content}")
        lines.append("\n只输出概要文字，不要列表。")
        return "\n".join(lines)


# ---- MemoryEvent serialization helpers (tick-level-resume 2026-05-16) ----
# MemoryEvent is a frozen dataclass (not Pydantic) — explicit serialization
# handles datetime ISO format + tuple → list (and back) so the JSON-roundtrip
# preserves types correctly.

# capability 1.14-quick-B (2026-05-19): cache field names. py-spy showed
# dataclasses.fields() introspection was 15% of total CPU during snapshot
# write — called per-event × 1000 agents × hundreds of events. Compute once
# at module import; field name list is identical for every MemoryEvent.
_MEMORY_EVENT_FIELD_NAMES: tuple[str, ...] | None = None


def _event_to_json(ev) -> dict[str, Any]:
    """frozen MemoryEvent → JSON-safe dict."""
    global _MEMORY_EVENT_FIELD_NAMES
    if _MEMORY_EVENT_FIELD_NAMES is None:
        from dataclasses import fields
        _MEMORY_EVENT_FIELD_NAMES = tuple(f.name for f in fields(ev))
    out: dict[str, Any] = {}
    for name in _MEMORY_EVENT_FIELD_NAMES:
        v = getattr(ev, name)
        if isinstance(v, datetime):
            out[name] = v.isoformat()
        elif isinstance(v, tuple):
            out[name] = list(v)
        else:
            out[name] = v
    return out


def _event_from_json(data: dict[str, Any]):
    """dict → MemoryEvent (with datetime / tuple coercion)."""
    from synthetic_socio_wind_tunnel.memory.models import MemoryEvent
    from dataclasses import fields as _fields

    kwargs: dict[str, Any] = {}
    for f in _fields(MemoryEvent):
        if f.name not in data:
            continue
        v = data[f.name]
        if v is None:
            kwargs[f.name] = None
            continue
        # Best-effort type coercion based on the field's annotation
        # (we keep it simple — known cases: datetime ISO str, list → tuple)
        if f.name in ("simulated_time", "last_access") and isinstance(v, str):
            try:
                kwargs[f.name] = datetime.fromisoformat(v)
            except ValueError:
                kwargs[f.name] = v
        elif f.name in ("participants", "tags", "embedding", "related_memory_ids") \
                and isinstance(v, list):
            kwargs[f.name] = tuple(v)
        else:
            kwargs[f.name] = v
    return MemoryEvent(**kwargs)
