"""
Memory 数据模型 — frozen dataclasses。

已吸收 typed-personality 的教训：urgency 作为显式字段（原设计 D10），
不藏在 tags 里；tags 仅承载描述性标签（可选）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


MemoryKind = Literal[
    "action",           # agent 自己的动作（CommitRecord 派生）
    "encounter",        # 路径相遇（EncounterCandidate 派生）
    "notification",     # 数字推送（AttentionService 派生）
    "observation",      # 主观感知中的显著项（未来扩展）
    "speech",           # 对话事件（conversation change 派生）
    "daily_summary",    # 每日概要（MemoryService.run_daily_summary 产）
    "task_received",    # 任务接收（category=task 的 FeedItem 派生）
]


@dataclass(frozen=True)
class MemoryEvent:
    """单条 memory 事件。append-only；不可变。"""

    event_id: str                          # 唯一标识（uuid 或 seq）
    agent_id: str                          # 归属 agent
    tick: int                              # orchestrator tick_index
    simulated_time: datetime               # 事件发生的世界时间戳
    kind: MemoryKind
    content: str                           # 人类可读 / LLM prompt 直读

    # 对方 / 目标 / 地点
    actor_id: str | None = None            # 对方 agent / 推送源 / 互动对象
    location_id: str | None = None

    # 多日 run 偏移（multi-day-simulation 引入；单日路径默认 0）
    day_index: int = 0

    # 显式 behavior-driving 字段（替代"藏在 tag 里的数值"反模式）
    urgency: float = 0.0                   # [0, 1]：事件紧迫度（应 replan 的信号）
    importance: float = 0.5                # [0, 1]：用户感知重要性（检索打分用）
    participants: tuple[str, ...] = ()     # 参与者 id（自己之外的 agent）

    # 描述性标签（tag 只承载 label，不承载数值）
    tags: tuple[str, ...] = ()

    # 可选的 embedding（NullEmbedding 下为 None）
    embedding: tuple[float, ...] | None = None


@dataclass(frozen=True)
class MemoryQuery:
    """MemoryRetriever 的查询描述。"""

    # 结构化字段（任一非空 → 参与 structural 子分）
    actor_id: str | None = None
    location_id: str | None = None
    kind: MemoryKind | None = None
    tags: tuple[str, ...] = ()             # 任一 tag 匹配即命中

    # 关键词（substring，case-insensitive）
    keyword: str | None = None

    # embedding 查询（可选）
    embedding_query: tuple[float, ...] | None = None

    # 时新度：从 reference_time 算 Δt
    recency_half_life_minutes: float = 60.0
    reference_time: datetime | None = None

    # 预过滤
    min_importance: float = 0.0


@dataclass(frozen=True)
class DailySummary:
    """单 agent 的日终摘要产物。"""

    agent_id: str
    date: str
    summary_text: str
    event_tags: dict[str, tuple[str, ...]] = field(default_factory=dict)
    """event_id → new tags，回填到原 MemoryEvent。"""
    event_importance: dict[str, float] = field(default_factory=dict)
    """event_id → new importance。"""
