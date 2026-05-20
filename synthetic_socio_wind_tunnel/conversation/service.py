"""ConversationService — probabilistic information propagation."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Mapping

from synthetic_socio_wind_tunnel.conversation.models import (
    Information,
    Propagation,
    ShareEvent,
)

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.agent import AgentRuntime
    from synthetic_socio_wind_tunnel.orchestrator.models import TickResult
    from synthetic_socio_wind_tunnel.social_graph import SocialGraphService


# V1 公式参数（design D1）；先验拍板，e2e 后视情况调
_BASE_SHARE_PROB = 0.15
_RECENCY_HALFLIFE_DAYS = 3.0  # exp(-days/3) → 3 day half-life
_MIN_2PLUS_HOPS = 2  # threshold for "info_reaching_2plus_hops" metric


@dataclass(frozen=True)
class _Knowledge:
    """Internal: when + how-far for a single (agent, info) pair."""
    first_learned_tick: int
    hops_at_learn: int


class ConversationService:
    """Per-(agent, info) information propagation tracker.

    Strength formula:
        P(share) = base × tie_mod × pers_mod × salience × recency_decay

    Where:
        base = 0.15
        tie_mod = 0.5 + 1.0 × tie.strength       (no tie → 0.5)
        pers_mod = avg(extraversion_a, extraversion_b)
        salience = info.salience
        recency_decay = exp(-days_since_origin / 3)
    """

    __slots__ = (
        "_rng",
        "_infos",
        "_known",
        "_known_by_info",
        "_share_count",
        "_relevance_provider",
        "_audience_tag_provider",
    )

    def __init__(
        self,
        *,
        seed: int | None = None,
        relevance_provider: Callable[[str, str], float] | None = None,
        audience_tag_provider: Callable[[str], str] | None = None,
    ) -> None:
        self._rng = random.Random(seed) if seed is not None else random.Random()
        self._infos: dict[str, Information] = {}
        self._known: dict[str, dict[str, _Knowledge]] = {}
        self._known_by_info: dict[str, set[str]] = {}
        self._share_count: dict[str, int] = {}
        # push-content-individualization
        self._relevance_provider = relevance_provider
        self._audience_tag_provider = audience_tag_provider

    # ------------------------------------------------------------ writes

    def record_origin(
        self, info: Information, agent_id: str, tick: int,
    ) -> None:
        """Register `info` and mark `agent_id` as origin (hops=0).

        Idempotent: re-registering the same info_id is a no-op (after the
        first call); re-recording origin for a different agent has no
        effect (origin is fixed).
        """
        if info.info_id not in self._infos:
            self._infos[info.info_id] = info
            self._known_by_info[info.info_id] = set()
            self._share_count[info.info_id] = 0
        self._learn(agent_id, info.info_id, tick=tick, hops=0)

    def _learn(
        self, agent_id: str, info_id: str, *, tick: int, hops: int,
    ) -> bool:
        """Insert (agent, info) into ledger ONLY if not already known.

        Shortest-path semantics: subsequent re-learns (e.g. via a longer
        path) leave hops_at_learn unchanged. Returns True iff this was the
        agent's first learn.
        """
        per_agent = self._known.setdefault(agent_id, {})
        if info_id in per_agent:
            return False
        per_agent[info_id] = _Knowledge(first_learned_tick=tick, hops_at_learn=hops)
        self._known_by_info.setdefault(info_id, set()).add(agent_id)
        return True

    def process_tick(
        self,
        tick_result: "TickResult",
        social_graph: "SocialGraphService",
        sim_day: int,
        agents: Mapping[str, "AgentRuntime"],
    ) -> list[ShareEvent]:
        """Walk this tick's encounters; probabilistically propagate info.

        For each encounter pair (a, b):
        - For each info known by exactly one side, roll the share gate.
        - On hit, the unknowing side learns it with hops = sender's_hops + 1.
        - Record the event in returned list (for inspector / debug).
        """
        events: list[ShareEvent] = []
        tick = tick_result.tick_index
        for enc in tick_result.encounter_candidates:
            a, b = enc.agent_a, enc.agent_b
            if a == b:
                continue
            agent_a = agents.get(a)
            agent_b = agents.get(b)
            if agent_a is None or agent_b is None:
                # caller passed an incomplete agent map; skip silently
                continue

            tie = social_graph.get_tie(a, b)
            tie_strength = tie.strength if tie is not None else 0.0
            tie_mod = 0.5 + 1.0 * tie_strength
            pers_mod = (
                agent_a.profile.personality.extraversion
                + agent_b.profile.personality.extraversion
            ) / 2.0

            for sender, receiver in ((a, b), (b, a)):
                sender_known = self._known.get(sender, {})
                receiver_known = self._known.get(receiver, {})
                for info_id, knowledge in list(sender_known.items()):
                    if info_id in receiver_known:
                        continue
                    info = self._infos.get(info_id)
                    if info is None:
                        continue
                    days_since = max(0, sim_day - info.origin_day_index)
                    recency_decay = math.exp(-days_since / _RECENCY_HALFLIFE_DAYS)
                    # push-content-individualization: per-(info, agent) relevance
                    if self._relevance_provider is not None:
                        s_rel = self._clamp01(self._relevance_provider(info_id, sender))
                        r_rel = self._clamp01(self._relevance_provider(info_id, receiver))
                    else:
                        s_rel = 1.0
                        r_rel = 1.0
                    p = (
                        _BASE_SHARE_PROB
                        * tie_mod
                        * pers_mod
                        * info.salience
                        * recency_decay
                        * s_rel
                        * r_rel
                    )
                    if self._rng.random() < p:
                        new_hops = knowledge.hops_at_learn + 1
                        if self._learn(receiver, info_id, tick=tick, hops=new_hops):
                            self._share_count[info_id] = (
                                self._share_count.get(info_id, 0) + 1
                            )
                            events.append(ShareEvent(
                                info_id=info_id,
                                from_agent=sender,
                                to_agent=receiver,
                                tick=tick,
                                receiver_hops=new_hops,
                            ))
        return events

    # ------------------------------------------------------------ queries

    def get_propagation(self, info_id: str) -> Propagation | None:
        """Aggregate Propagation view; None if info_id unknown."""
        if info_id not in self._infos:
            return None
        agents = self._known_by_info.get(info_id, set())
        if not agents:
            return Propagation(
                info_id=info_id, reach=0, max_hops=0, mean_hops=0.0,
                known_at={}, hops_at={},
            )
        known_at: dict[str, int] = {}
        hops_at: dict[str, int] = {}
        for aid in agents:
            k = self._known[aid][info_id]
            known_at[aid] = k.first_learned_tick
            hops_at[aid] = k.hops_at_learn
        max_h = max(hops_at.values())
        mean_h = sum(hops_at.values()) / len(hops_at)
        return Propagation(
            info_id=info_id,
            reach=len(agents),
            max_hops=max_h,
            mean_hops=mean_h,
            known_at=known_at,
            hops_at=hops_at,
        )

    def info_known_by(self, agent_id: str) -> set[str]:
        """Set of info_ids known by `agent_id`."""
        return set(self._known.get(agent_id, {}).keys())

    def all_infos(self) -> list[Information]:
        return list(self._infos.values())

    def info_count(self) -> int:
        return len(self._infos)

    def max_hops(self) -> int:
        """Largest hops_at_learn observed across all (agent, info) pairs."""
        m = 0
        for per_agent in self._known.values():
            for k in per_agent.values():
                if k.hops_at_learn > m:
                    m = k.hops_at_learn
        return m

    def count_reaching(self, min_hops: int = _MIN_2PLUS_HOPS) -> int:
        """Number of distinct infos with at least one agent reached at hops≥min."""
        out: set[str] = set()
        for per_agent in self._known.values():
            for info_id, k in per_agent.items():
                if k.hops_at_learn >= min_hops:
                    out.add(info_id)
        return len(out)

    def avg_reach(self) -> float:
        """Mean number of agents reached per info."""
        if not self._infos:
            return 0.0
        total = sum(len(s) for s in self._known_by_info.values())
        return total / len(self._infos)

    def top_propagated(self, n: int = 10) -> list[Propagation]:
        all_props = [
            self.get_propagation(info_id) for info_id in self._infos.keys()
        ]
        all_props = [p for p in all_props if p is not None]
        all_props.sort(key=lambda p: (p.reach, p.max_hops), reverse=True)
        return all_props[:n]

    # ---------- daily counters (for metrics recorder) ----------

    def origins_on_day(self, day_index: int) -> int:
        return sum(
            1 for info in self._infos.values()
            if info.origin_day_index == day_index
        )

    def shares_on_day(self, day_index: int, ticks_per_day: int = 288) -> int:
        """Number of distinct infos that had at least one share on `day_index`.

        Approximated via _Knowledge entries: an info has a "share on day X"
        if any non-origin agent's first_learned_tick falls in X's tick window.
        """
        lo = day_index * ticks_per_day
        hi = (day_index + 1) * ticks_per_day
        out: set[str] = set()
        for per_agent in self._known.values():
            for info_id, k in per_agent.items():
                if k.hops_at_learn >= 1 and lo <= k.first_learned_tick < hi:
                    out.add(info_id)
        return len(out)

    def reaching_2plus_on_day(self, day_index: int, ticks_per_day: int = 288) -> int:
        """Distinct infos that reached hops≥2 first time on `day_index`."""
        lo = day_index * ticks_per_day
        hi = (day_index + 1) * ticks_per_day
        out: set[str] = set()
        for per_agent in self._known.values():
            for info_id, k in per_agent.items():
                if k.hops_at_learn >= _MIN_2PLUS_HOPS and lo <= k.first_learned_tick < hi:
                    out.add(info_id)
        return len(out)

    @staticmethod
    def _clamp01(x: float) -> float:
        if x < 0.0:
            return 0.0
        if x > 1.0:
            return 1.0
        return x

    # ---------- target audience metrics (push-content-individualization) ----------

    def within_target_count(self, info_id: str) -> int:
        """触达 agents 中 audience_tag ∈ info.target_audience_tags 的数量。

        若 audience_tag_provider 未注入或 info.target_audience_tags 为空则返回 0。
        """
        if self._audience_tag_provider is None:
            return 0
        info = self._infos.get(info_id)
        if info is None or not info.target_audience_tags:
            return 0
        targets = set(info.target_audience_tags)
        agents = self._known_by_info.get(info_id, set())
        n = 0
        for aid in agents:
            try:
                tag = self._audience_tag_provider(aid)
            except Exception:
                continue
            if tag in targets:
                n += 1
        return n

    def outside_target_count(self, info_id: str) -> int:
        if self._audience_tag_provider is None:
            return 0
        info = self._infos.get(info_id)
        if info is None or not info.target_audience_tags:
            return 0
        targets = set(info.target_audience_tags)
        agents = self._known_by_info.get(info_id, set())
        n = 0
        for aid in agents:
            try:
                tag = self._audience_tag_provider(aid)
            except Exception:
                continue
            if tag not in targets:
                n += 1
        return n

    def target_precision_for(self, info_id: str) -> float:
        """within / total reach；audience_tag_provider 缺失返回 0."""
        within = self.within_target_count(info_id)
        outside = self.outside_target_count(info_id)
        total = within + outside
        if total == 0:
            return 0.0
        return within / total

    def mean_target_precision(self) -> float:
        """跨所有 info 的均值；无 info / 无 provider 时返回 0."""
        if self._audience_tag_provider is None or not self._infos:
            return 0.0
        ratios = [self.target_precision_for(info_id) for info_id in self._infos]
        ratios = [r for r in ratios if r > 0.0 or self.outside_target_count]  # include 0s
        if not ratios:
            return 0.0
        return sum(ratios) / len(ratios)

    def total_within_target(self) -> int:
        """全部 info 累加的 within_target reach（个数）。"""
        return sum(self.within_target_count(info_id) for info_id in self._infos)

    def total_outside_target(self) -> int:
        return sum(self.outside_target_count(info_id) for info_id in self._infos)

    def info_target_reach_today(self, day_index: int, ticks_per_day: int = 288) -> int:
        """当天 first-learned 事件中，learner 是 within-target 的数量。"""
        if self._audience_tag_provider is None:
            return 0
        lo = day_index * ticks_per_day
        hi = (day_index + 1) * ticks_per_day
        n = 0
        for aid, per_agent in self._known.items():
            for info_id, k in per_agent.items():
                if not (lo <= k.first_learned_tick < hi):
                    continue
                info = self._infos.get(info_id)
                if info is None or not info.target_audience_tags:
                    continue
                try:
                    tag = self._audience_tag_provider(aid)
                except Exception:
                    continue
                if tag in info.target_audience_tags:
                    n += 1
        return n

    def avg_hops_on_day(self, day_index: int, ticks_per_day: int = 288) -> float:
        lo = day_index * ticks_per_day
        hi = (day_index + 1) * ticks_per_day
        hops_list: list[int] = []
        for per_agent in self._known.values():
            for k in per_agent.values():
                if lo <= k.first_learned_tick < hi:
                    hops_list.append(k.hops_at_learn)
        if not hops_list:
            return 0.0
        return sum(hops_list) / len(hops_list)

    # ----------------------------------------------------------- snapshot
    # 2026-05-21 RESUME-DETERMINISM (D): per audit, _rng drives the
    # P(share) gate in process_tick → ShareEvent emission. Without
    # round-trip the resumed sim diverges from fresh at first share
    # decision. Also persist _infos / _known / _known_by_info /
    # _share_count so propagation state continues from the snap point.
    # _relevance_provider / _audience_tag_provider are callables —
    # rebuilt at runner init; not snapshotted.

    def to_snapshot_state(self) -> dict:
        from synthetic_socio_wind_tunnel.run_resilience.state_snapshot import (
            _rng_state_to_json,
        )
        return {
            "rng_state": _rng_state_to_json(self._rng.getstate()),
            "infos": {
                info_id: {
                    "info_id": info.info_id,
                    "content": info.content,
                    "category": info.category,
                    "salience": info.salience,
                    "origin_tick": info.origin_tick,
                    "origin_agent_id": info.origin_agent_id,
                    "origin_day_index": info.origin_day_index,
                    "source_feed_item_id": info.source_feed_item_id,
                    "source_location_id": info.source_location_id,
                    "target_audience_tags": list(info.target_audience_tags),
                }
                for info_id, info in self._infos.items()
            },
            "known": {
                agent_id: {
                    info_id: {
                        "first_learned_tick": k.first_learned_tick,
                        "hops_at_learn": k.hops_at_learn,
                    }
                    for info_id, k in per_agent.items()
                }
                for agent_id, per_agent in self._known.items()
            },
            "known_by_info": {
                info_id: sorted(agents)
                for info_id, agents in self._known_by_info.items()
            },
            "share_count": dict(self._share_count),
        }

    def from_snapshot_state(self, state: dict) -> None:
        from synthetic_socio_wind_tunnel.run_resilience.state_snapshot import (
            _rng_state_from_json,
        )
        if not isinstance(state, dict):
            raise ValueError(
                f"ConversationService.from_snapshot_state expects dict, "
                f"got {type(state).__name__}"
            )
        rng_state = state.get("rng_state")
        if rng_state is not None:
            try:
                self._rng.setstate(_rng_state_from_json(list(rng_state)))
            except Exception:  # noqa: BLE001
                pass
        self._infos = {
            info_id: Information(
                info_id=raw["info_id"],
                content=raw["content"],
                category=raw["category"],
                salience=raw["salience"],
                origin_tick=raw["origin_tick"],
                origin_agent_id=raw["origin_agent_id"],
                origin_day_index=raw["origin_day_index"],
                source_feed_item_id=raw.get("source_feed_item_id"),
                source_location_id=raw.get("source_location_id"),
                target_audience_tags=tuple(raw.get("target_audience_tags") or ()),
            )
            for info_id, raw in (state.get("infos") or {}).items()
        }
        self._known = {
            agent_id: {
                info_id: _Knowledge(
                    first_learned_tick=raw["first_learned_tick"],
                    hops_at_learn=raw["hops_at_learn"],
                )
                for info_id, raw in per_agent.items()
            }
            for agent_id, per_agent in (state.get("known") or {}).items()
        }
        self._known_by_info = {
            info_id: set(agents)
            for info_id, agents in (state.get("known_by_info") or {}).items()
        }
        self._share_count = dict(state.get("share_count") or {})
