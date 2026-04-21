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
from datetime import datetime
from typing import TYPE_CHECKING, Mapping

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
    from synthetic_socio_wind_tunnel.attention import AttentionService
    from synthetic_socio_wind_tunnel.orchestrator import Orchestrator, TickResult


class MemoryService:
    """Memory capability 的对外入口。"""

    __slots__ = (
        "_stores",
        "_embedding",
        "_retriever",
        "_attention_service",
        "_consumed_feed_item_ids",
        "_event_counter",
    )

    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        retriever_weights: dict[str, float] | None = None,
        attention_service: "AttentionService | None" = None,
    ) -> None:
        self._stores: dict[str, MemoryStore] = {}
        self._embedding: EmbeddingProvider = embedding_provider or NullEmbedding()
        self._retriever = MemoryRetriever(weights=retriever_weights)
        self._attention_service = attention_service
        # D.1 修复：per-agent feed_item_id 去重集合。
        # 旧实现用 last_seen_timestamp 过滤；AttentionService.notifications_for
        # 的 `>=` 语义会让同 timestamp 的 notification 在下一次 tick 被
        # 重新 ingest。改为直接记住 "这个 agent 已经 ingest 过的 feed_item_id"。
        self._consumed_feed_item_ids: dict[str, set[str]] = {}
        self._event_counter = 0

    def _store_for(self, agent_id: str) -> MemoryStore:
        if agent_id not in self._stores:
            self._stores[agent_id] = MemoryStore()
        return self._stores[agent_id]

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

        # 1. 从 commits 派生 action events
        for commit in tick_result.commits:
            self._record_action(
                agent_id=commit.agent_id,
                commit=commit,
                tick=tick,
                sim_time=sim_time,
            )

        # 2. 从 encounter_candidates 派生双向 encounter events
        for enc in tick_result.encounter_candidates:
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
                    tags=("encounter",),
                )
                self.record(me, event)

        # 3. 从 AttentionService 派生 notification / task_received events
        if self._attention_service is not None:
            for agent_id in agents:
                self._ingest_notifications(agent_id, tick, sim_time)

        # 4. Replan 检查 & 执行
        replans: list[tuple[str, MemoryEvent]] = []
        if planner is None:
            return replans

        for agent_id, agent in agents.items():
            # 用 events_at_tick 而不是 recent(last_ticks=1)：
            # 后者基于 max_tick，在"没有其它事件写入"时会把旧 tick 的
            # 事件反复视为 recent，导致 replan 重复触发。
            recent = self.events_at_tick(agent_id, tick_result.tick_index)
            if not recent:
                continue
            for candidate in recent:
                if agent.should_replan(recent, candidate):
                    interrupt_ctx = {
                        "trigger_event": candidate,
                        "recent_memories": recent,
                        "current_time": sim_time,
                    }
                    try:
                        new_plan = asyncio.run(planner.replan(
                            agent.profile, agent.plan, interrupt_ctx,
                        ))
                        agent.plan = new_plan
                        replans.append((agent_id, candidate))
                    except Exception:
                        # Planner.replan 内部已有 fallback；外层再兜一次保险
                        pass
                    break  # 一 tick 内至多一次 replan / agent

        return replans

    def _record_action(self, *, agent_id, commit, tick, sim_time) -> None:
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
        )
        self.record(agent_id, event)

    def _ingest_notifications(
        self, agent_id: str, tick: int, sim_time: datetime
    ) -> None:
        """
        Pull new-to-this-agent notifications and record them as MemoryEvents.

        D.1 修复：用 per-agent `set[feed_item_id]` 去重而非 timestamp since。
        """
        assert self._attention_service is not None
        consumed = self._consumed_feed_item_ids.setdefault(agent_id, set())
        all_events = self._attention_service.notifications_for(agent_id)
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
            )
            self.record(agent_id, event)
            consumed.add(feed_item_id)

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
            date_str = str(all_events[0].simulated_time.date())
            prompt = self._build_summary_prompt(agent, all_events)
            try:
                raw = await llm_client.generate(
                    prompt, model=agent.profile.base_model
                )
                summary = DailySummary(
                    agent_id=agent_id,
                    date=date_str,
                    summary_text=raw.strip(),
                )
            except Exception:
                summary = DailySummary(
                    agent_id=agent_id,
                    date=date_str,
                    summary_text="(unavailable)",
                )
            summaries[agent_id] = summary

            # 写一条 daily_summary 事件作为索引入口
            self.record(agent_id, MemoryEvent(
                event_id=self._next_event_id(agent_id, -1),
                agent_id=agent_id,
                tick=-1,  # special "end-of-day" tick
                simulated_time=all_events[-1].simulated_time,
                kind="daily_summary",
                content=summary.summary_text,
                urgency=0.0,
                importance=0.8,
                tags=("summary",),
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
