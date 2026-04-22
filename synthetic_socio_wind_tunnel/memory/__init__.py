"""
Memory — per-agent 事件流 / 检索 / replan 触发

三件事：
- 存：MemoryEvent + MemoryStore（per-agent in-memory）
- 查：MemoryRetriever（4-way 打分：结构化 / 关键词 / recency / embedding）
- 触发：MemoryService.process_tick 订阅 orchestrator.on_tick_end，写入
  tick 派生事件 + 对每 agent 调 should_replan；True 则调 planner.replan

不做：reflection、跨 session 持久化、每事件 LLM 打标（成本禁区）、
shared-task 状态机（policy-hack 职责）。
"""

from synthetic_socio_wind_tunnel.memory.carryover import CarryoverContext
from synthetic_socio_wind_tunnel.memory.models import (
    DailySummary,
    MemoryEvent,
    MemoryKind,
    MemoryQuery,
)
from synthetic_socio_wind_tunnel.memory.embedding import (
    EmbeddingProvider,
    NullEmbedding,
)
from synthetic_socio_wind_tunnel.memory.store import MemoryStore
from synthetic_socio_wind_tunnel.memory.retrieval import MemoryRetriever
from synthetic_socio_wind_tunnel.memory.service import MemoryService

__all__ = [
    "CarryoverContext",
    "DailySummary",
    "EmbeddingProvider",
    "MemoryEvent",
    "MemoryKind",
    "MemoryQuery",
    "MemoryRetriever",
    "MemoryService",
    "MemoryStore",
    "NullEmbedding",
]
