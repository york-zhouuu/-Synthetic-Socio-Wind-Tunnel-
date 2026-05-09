"""
MemoryRetriever — 检索打分。

支持两种模式：
1. **legacy** (默认): 加权和——struct 0.40 / keyword 0.15 / recency 0.35 / embed 0.10
   全 SSWT 现有 caller 走这个；行为不变。
2. **aitown** (mode="aitown"): 1:1 port of ai-town's `rankAndTouchMemories`
   (memory.ts:187-228)——normalize-then-sum，3 维度 (relevance/embedding +
   importance + recency)，每维 batch 内 min-max 归一化到 [0,1] 再相加。
   recency 用 `0.99 ^ floor(hours)`（ai-town verbatim），不是 exp。

ai-town 模式下 keyword 维度被禁用（embedding 路径覆盖）；importance 维度
真正参与（不再像 legacy 模式可能 default 0.5 而无效）。
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Literal

from synthetic_socio_wind_tunnel.memory.embedding import cosine_similarity

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.memory.models import MemoryEvent, MemoryQuery
    from synthetic_socio_wind_tunnel.memory.store import MemoryStore


RetrievalMode = Literal["legacy", "aitown"]


_DEFAULT_WEIGHTS = {
    "struct": 0.40,
    "keyword": 0.15,
    "recency": 0.35,
    "embed": 0.10,
}
_FALLBACK_POOL_SIZE = 200


class MemoryRetriever:
    """检索打分器（legacy weighted-sum 或 aitown normalize-then-sum）。"""

    __slots__ = ("_weights", "_mode")

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        *,
        mode: RetrievalMode = "legacy",
    ) -> None:
        w = dict(_DEFAULT_WEIGHTS)
        if weights:
            w.update(weights)
        self._weights = w
        self._mode = mode

    def retrieve(
        self,
        store: "MemoryStore",
        query: "MemoryQuery",
        top_k: int = 10,
    ) -> list["MemoryEvent"]:
        # 1. 候选池
        struct_indices = store._indices_for_query(
            actor_id=query.actor_id,
            location_id=query.location_id,
            kind=query.kind,
            tags=query.tags,
        )
        if struct_indices:
            candidates = [store._event_at(i) for i in struct_indices]
        else:
            candidates = list(store.recent(_FALLBACK_POOL_SIZE))

        # 2. 预过滤 importance
        candidates = [
            e for e in candidates if e.importance >= query.min_importance
        ]
        if not candidates:
            return []

        # 3. reference_time 默认取 candidates 中最新的 simulated_time
        ref_time = query.reference_time
        if ref_time is None and candidates:
            ref_time = max(e.simulated_time for e in candidates)

        if self._mode == "aitown":
            return self._rank_aitown(candidates, query, ref_time, top_k)
        return self._rank_legacy(candidates, query, ref_time, top_k)

    # -- legacy weighted-sum (existing SSWT behavior) ---------------------

    def _rank_legacy(
        self,
        candidates: list["MemoryEvent"],
        query: "MemoryQuery",
        ref_time,
        top_k: int,
    ) -> list["MemoryEvent"]:
        query_fields_present = _count_query_structural_fields(query)

        scored: list[tuple[float, int, "MemoryEvent"]] = []
        for event in candidates:
            struct_score = _structural_score(event, query, query_fields_present)
            kw_score = _keyword_score(event, query)
            rec_score = _recency_score(event, query, ref_time)
            emb_score = _embedding_score(event, query)

            total = (
                self._weights["struct"] * struct_score
                + self._weights["keyword"] * kw_score
                + self._weights["recency"] * rec_score
                + self._weights["embed"] * emb_score
            )
            scored.append((total, event.tick, event))
        scored.sort(key=lambda t: (-t[0], -t[1]))
        return [event for _score, _tick, event in scored[:top_k]]

    # -- aitown normalize-then-sum (1:1 port of memory.ts:187-228) ---------

    def _rank_aitown(
        self,
        candidates: list["MemoryEvent"],
        query: "MemoryQuery",
        ref_time,
        top_k: int,
    ) -> list["MemoryEvent"]:
        """Port of ai-town `rankAndTouchMemories`: normalize each component
        across the candidate batch (min-max), then sum. Recency uses
        0.99^floor(hours) per ai-town verbatim."""
        if not candidates:
            return []
        # raw component scores
        rel_scores: list[float] = []   # relevance (cosine similarity if embed available; else structural)
        imp_scores: list[float] = []
        rec_scores: list[float] = []
        for event in candidates:
            # relevance: prefer embedding if present, fallback to structural
            if query.embedding_query is not None and event.embedding is not None:
                rel_scores.append(_embedding_score(event, query))
            else:
                rel_scores.append(_structural_score(
                    event, query, _count_query_structural_fields(query),
                ))
            imp_scores.append(event.importance)
            rec_scores.append(_recency_aitown(event, ref_time))

        # min-max normalize each component independently across the batch
        rel_n = _normalize_minmax(rel_scores)
        imp_n = _normalize_minmax(imp_scores)
        rec_n = _normalize_minmax(rec_scores)

        scored: list[tuple[float, int, "MemoryEvent"]] = []
        for i, event in enumerate(candidates):
            total = rel_n[i] + imp_n[i] + rec_n[i]
            scored.append((total, event.tick, event))
        scored.sort(key=lambda t: (-t[0], -t[1]))
        return [event for _score, _tick, event in scored[:top_k]]


# ---- 子分计算 ----

def _count_query_structural_fields(query: "MemoryQuery") -> int:
    """统计 query 中非空的结构化字段数，作为 structural 归一分母。"""
    count = 0
    if query.actor_id is not None:
        count += 1
    if query.location_id is not None:
        count += 1
    if query.kind is not None:
        count += 1
    if query.tags:
        count += 1
    return count


def _structural_score(
    event: "MemoryEvent",
    query: "MemoryQuery",
    denominator: int,
) -> float:
    """命中 query 非空结构化字段的比例。"""
    if denominator == 0:
        return 0.0
    hits = 0
    if query.actor_id and event.actor_id == query.actor_id:
        hits += 1
    if query.location_id and event.location_id == query.location_id:
        hits += 1
    if query.kind and event.kind == query.kind:
        hits += 1
    if query.tags and any(tag in event.tags for tag in query.tags):
        hits += 1
    return hits / denominator


def _keyword_score(event: "MemoryEvent", query: "MemoryQuery") -> float:
    if not query.keyword:
        return 0.0
    return 1.0 if query.keyword.lower() in event.content.lower() else 0.0


def _recency_score(
    event: "MemoryEvent",
    query: "MemoryQuery",
    ref_time,
) -> float:
    if ref_time is None:
        return 0.0
    delta_minutes = (ref_time - event.simulated_time).total_seconds() / 60.0
    # event 在 ref 之后的话，clamp 到 0（未来事件不应存在但防御一下）
    if delta_minutes < 0:
        delta_minutes = 0.0
    half_life = max(0.001, query.recency_half_life_minutes)
    return math.exp(-delta_minutes / half_life)


def _embedding_score(event: "MemoryEvent", query: "MemoryQuery") -> float:
    if query.embedding_query is None or event.embedding is None:
        return 0.0
    return cosine_similarity(event.embedding, query.embedding_query)


def _recency_aitown(event: "MemoryEvent", ref_time) -> float:
    """1:1 port of ai-town's recency formula (memory.ts:206):
        recencyScore = 0.99 ^ floor(hoursSinceAccess)

    Uses event.last_access if set (touched on retrieval), else simulated_time
    as fallback. ai-town stores lastAccess as wallclock ts; we use simulated_time.
    """
    if ref_time is None:
        return 1.0  # if no reference, treat as fully recent
    anchor = event.last_access or event.simulated_time
    delta_seconds = (ref_time - anchor).total_seconds()
    if delta_seconds < 0:
        delta_seconds = 0.0
    hours = int(delta_seconds // 3600)
    return 0.99 ** hours


def _normalize_minmax(values: list[float]) -> list[float]:
    """Min-max normalize a list to [0, 1]. If all values equal → all 1.0
    (ai-town's normalize() returns NaN for that case but we treat as "all
    equally relevant" since their `(x - min) / (max - min)` is undefined).
    """
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi == lo:
        return [1.0] * len(values)
    span = hi - lo
    return [(v - lo) / span for v in values]
