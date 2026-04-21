"""
MemoryRetriever — 4-way 打分检索。

子分：
- structural: query 结构化字段命中的比例
- keyword: substring 匹配（case-insensitive）
- recency: exp(-Δt / half_life)
- embedding: cosine similarity（若两侧都有 embedding）

默认权重：struct=0.4, keyword=0.15, recency=0.35, embed=0.10
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from synthetic_socio_wind_tunnel.memory.embedding import cosine_similarity

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.memory.models import MemoryEvent, MemoryQuery
    from synthetic_socio_wind_tunnel.memory.store import MemoryStore


_DEFAULT_WEIGHTS = {
    "struct": 0.40,
    "keyword": 0.15,
    "recency": 0.35,
    "embed": 0.10,
}
_FALLBACK_POOL_SIZE = 200


class MemoryRetriever:
    """无状态打分器（权重配置注入）。"""

    __slots__ = ("_weights",)

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        w = dict(_DEFAULT_WEIGHTS)
        if weights:
            w.update(weights)
        self._weights = w

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

        # 4. 打分
        query_fields_present = _count_query_structural_fields(query)

        scored: list[tuple[float, int, "MemoryEvent"]] = []
        # 第二项 tick（降序）作 tie-break
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

        # 5. 排序：score 降序，tick 降序（tie-break：新事件优先）
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
