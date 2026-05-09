"""SocialGraphService — accumulate pairwise ties from encounter stream."""

from __future__ import annotations

from dataclasses import replace

from synthetic_socio_wind_tunnel.social_graph.models import Tie, canonical_pair


# Tie strength thresholds (V1 — design D1)
WEAK_TIE_THRESHOLD: float = 0.1   # ~ 1 encounter → 0.091
STRONG_TIE_THRESHOLD: float = 0.5  # ~ 10 encounters → 0.500 (with K=10)


class SocialGraphService:
    """In-memory accumulator of pairwise ties.

    Strength formula: ``N / (N + K)`` where N = encounter_count, K is
    construction-time half-saturation point (default 10 — at K encounters,
    strength = 0.5, the weak/strong boundary).

    Service instance state is single-process only; not persisted across runs.
    No historical backfill from memory store — accumulates only from
    record_encounter calls received after construction.
    """

    __slots__ = (
        "_K",
        "_ties",
        "_seen_in_tick",
        "_agent_to_pairs",
    )

    def __init__(self, *, K: int = 10) -> None:
        if K <= 0:
            raise ValueError(f"K (half-saturation) must be > 0, got {K}")
        self._K = K
        self._ties: dict[tuple[str, str], Tie] = {}
        # idempotency guard: same (pair, tick) won't double-increment
        # encounter_count. Cleared at most once per tick switch (lazy).
        self._seen_in_tick: dict[int, set[tuple[str, str]]] = {}
        # adjacency index: agent_id -> set of pair-keys involving them.
        # O(1) ties_for / familiar_with on top of dict.
        self._agent_to_pairs: dict[str, set[tuple[str, str]]] = {}

    @property
    def K(self) -> int:
        return self._K

    # ---- 写入 ----

    def record_encounter(
        self, agent_a: str, agent_b: str, tick: int, day_index: int = 0,
    ) -> Tie:
        """Accumulate or create a tie for the (a, b) pair at this tick.

        Idempotent within a single tick: calling repeatedly with the same
        (pair, tick) increments encounter_count only on the first call.
        Different ticks always increment.
        """
        key = canonical_pair(agent_a, agent_b)

        seen_this_tick = self._seen_in_tick.setdefault(tick, set())
        if key in seen_this_tick:
            # already counted in this tick — return current state without changes
            return self._ties[key]
        seen_this_tick.add(key)

        existing = self._ties.get(key)
        if existing is None:
            tie = Tie(
                agent_a=key[0], agent_b=key[1],
                encounter_count=1,
                strength=self._strength(1),
                first_seen_tick=tick,
                last_seen_tick=tick,
                first_seen_day=day_index,
            )
            self._ties[key] = tie
            self._agent_to_pairs.setdefault(key[0], set()).add(key)
            self._agent_to_pairs.setdefault(key[1], set()).add(key)
        else:
            new_count = existing.encounter_count + 1
            tie = replace(
                existing,
                encounter_count=new_count,
                strength=self._strength(new_count),
                last_seen_tick=tick,
            )
            self._ties[key] = tie
        return tie

    def _strength(self, encounter_count: int) -> float:
        """Asymptotic strength formula: N / (N + K)."""
        return encounter_count / (encounter_count + self._K)

    def preload_ties(self, prior_records, *, day_index: int = -1) -> int:
        """Bulk-create Tie records from PriorTieRecord items (lane cove
        data_loader). Multiple records for the same pair sum their
        encounter_count contributions.

        Used at sim-start to give the graph a non-empty day-0 state
        (without this, every agent pair = stranger). Idempotent across
        repeated calls — second call no-ops because seen_in_tick logic.

        Args:
            prior_records: iterable of PriorTieRecord
            day_index: stamped on Tie.first_seen_day (default -1 = pre-sim)

        Returns:
            number of ties created (not the number of input records)
        """
        # Aggregate encounter_count per canonical pair
        agg: dict[tuple[str, str], int] = {}
        for rec in prior_records:
            key = canonical_pair(rec.agent_a, rec.agent_b)
            agg[key] = agg.get(key, 0) + int(rec.encounter_count)

        created = 0
        for key, count in agg.items():
            if key in self._ties:
                # already preloaded; skip
                continue
            tie = Tie(
                agent_a=key[0], agent_b=key[1],
                encounter_count=count,
                strength=self._strength(count),
                first_seen_tick=-1,
                last_seen_tick=-1,
                first_seen_day=day_index,
            )
            self._ties[key] = tie
            self._agent_to_pairs.setdefault(key[0], set()).add(key)
            self._agent_to_pairs.setdefault(key[1], set()).add(key)
            created += 1
        return created

    # ---- 查询 ----

    def get_tie(self, agent_a: str, agent_b: str) -> Tie | None:
        if agent_a == agent_b:
            return None
        key = canonical_pair(agent_a, agent_b)
        return self._ties.get(key)

    def ties_for(self, agent_id: str) -> list[Tie]:
        """All ties involving `agent_id` (either side)."""
        keys = self._agent_to_pairs.get(agent_id, set())
        return [self._ties[k] for k in keys]

    def familiar_with(
        self, agent_id: str, threshold: float = WEAK_TIE_THRESHOLD,
    ) -> set[str]:
        """Other agent ids whose tie with `agent_id` has strength > threshold."""
        out: set[str] = set()
        for tie in self.ties_for(agent_id):
            if tie.strength > threshold:
                other = tie.agent_b if tie.agent_a == agent_id else tie.agent_a
                out.add(other)
        return out

    def weak_ties(self, agent_id: str) -> list[Tie]:
        """Ties with strength ∈ [WEAK_TIE_THRESHOLD, STRONG_TIE_THRESHOLD)."""
        return [
            t for t in self.ties_for(agent_id)
            if WEAK_TIE_THRESHOLD <= t.strength < STRONG_TIE_THRESHOLD
        ]

    def strong_ties(self, agent_id: str) -> list[Tie]:
        """Ties with strength ≥ STRONG_TIE_THRESHOLD."""
        return [
            t for t in self.ties_for(agent_id)
            if t.strength >= STRONG_TIE_THRESHOLD
        ]

    def all_ties(self) -> list[Tie]:
        return list(self._ties.values())

    # ---- 集合级 metric helpers ----

    def total_count(self) -> int:
        return len(self._ties)

    def weak_count(self) -> int:
        return sum(
            1 for t in self._ties.values()
            if WEAK_TIE_THRESHOLD <= t.strength < STRONG_TIE_THRESHOLD
        )

    def strong_count(self) -> int:
        return sum(
            1 for t in self._ties.values() if t.strength >= STRONG_TIE_THRESHOLD
        )

    def new_ties_on_day(self, day_index: int) -> int:
        return sum(1 for t in self._ties.values() if t.first_seen_day == day_index)
