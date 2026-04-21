"""
MemoryStore — per-agent 事件存储 + 4 路倒排索引。

append O(1)；查询 O(匹配数)。不持久化；重启即清。
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.memory.models import MemoryEvent, MemoryKind


class MemoryStore:
    """per-agent memory store。"""

    __slots__ = ("_events", "_by_actor", "_by_location", "_by_tag", "_by_kind")

    def __init__(self) -> None:
        self._events: list["MemoryEvent"] = []
        self._by_actor: dict[str, list[int]] = defaultdict(list)
        self._by_location: dict[str, list[int]] = defaultdict(list)
        self._by_tag: dict[str, list[int]] = defaultdict(list)
        self._by_kind: dict[str, list[int]] = defaultdict(list)

    def __len__(self) -> int:
        return len(self._events)

    def append(self, event: "MemoryEvent") -> None:
        """写入 + 更新 4 路索引。"""
        idx = len(self._events)
        self._events.append(event)
        if event.actor_id:
            self._by_actor[event.actor_id].append(idx)
        if event.location_id:
            self._by_location[event.location_id].append(idx)
        for tag in event.tags:
            self._by_tag[tag].append(idx)
        self._by_kind[event.kind].append(idx)

    # ---- 查询入口 ----

    def all(self) -> tuple["MemoryEvent", ...]:
        return tuple(self._events)

    def recent(self, n: int) -> tuple["MemoryEvent", ...]:
        """最近 n 条（按 append 顺序倒数）。"""
        if n <= 0 or not self._events:
            return ()
        return tuple(self._events[-n:])

    def by_actor(self, actor_id: str) -> tuple["MemoryEvent", ...]:
        return tuple(self._events[i] for i in self._by_actor.get(actor_id, ()))

    def by_location(self, location_id: str) -> tuple["MemoryEvent", ...]:
        return tuple(self._events[i] for i in self._by_location.get(location_id, ()))

    def by_tag(self, tag: str) -> tuple["MemoryEvent", ...]:
        return tuple(self._events[i] for i in self._by_tag.get(tag, ()))

    def by_kind(self, kind: "MemoryKind") -> tuple["MemoryEvent", ...]:
        return tuple(self._events[i] for i in self._by_kind.get(kind, ()))

    def _indices_for_query(
        self,
        *,
        actor_id: str | None,
        location_id: str | None,
        kind: "MemoryKind | None",
        tags: tuple[str, ...],
    ) -> set[int]:
        """返回结构化条件的候选索引并集（供 MemoryRetriever 使用）。"""
        hits: list[set[int]] = []
        if actor_id:
            hits.append(set(self._by_actor.get(actor_id, ())))
        if location_id:
            hits.append(set(self._by_location.get(location_id, ())))
        if kind:
            hits.append(set(self._by_kind.get(kind, ())))
        for tag in tags:
            hits.append(set(self._by_tag.get(tag, ())))
        if not hits:
            return set()
        # 并集（OR 语义）：事件只要命中一个维度就成为候选
        result: set[int] = set()
        for s in hits:
            result |= s
        return result

    def _event_at(self, idx: int) -> "MemoryEvent":
        return self._events[idx]

    def replace(self, event_id: str, new_event: "MemoryEvent") -> bool:
        """
        替换 event（同 event_id）。用于 daily summary 回填 tags / importance。
        返回是否替换成功。

        注意：替换不重建全部索引，只在必要时（tags 变了）增量更新。
        大多数情况 daily summary 只改 tags / importance，原 event 的
        actor/location/kind 不变——只需增量 tag 索引。
        """
        for i, ev in enumerate(self._events):
            if ev.event_id == event_id:
                # 移除旧 event 的 tag 索引
                for tag in ev.tags:
                    if i in self._by_tag.get(tag, []):
                        self._by_tag[tag].remove(i)
                # 写入新 event
                self._events[i] = new_event
                # 重建新 event 的 tag 索引
                for tag in new_event.tags:
                    self._by_tag[tag].append(i)
                return True
        return False
