"""
CarryoverContext — 次日 planner 的历史上下文载荷。

由 `MemoryService.get_carryover_context(agent_id, current_day_index)` 聚合
per-agent 的昨日摘要 / 近日反思 / 未完成任务锚点，planner 在构 prompt 时
拼入（1500 字符 upper bound + 超长则 summary_text 300 字符截断，见
agent/planner.py 的处理）。

设计原则（见 multi-day-simulation design D3）：
- pure-data Pydantic frozen model，不含行为
- planner 决定如何把它拼进 prompt（memory 侧不承担 prompt 模板职责）
- memory 不持久化该 context；每次 get_carryover_context 重新聚合
"""

from pydantic import BaseModel, ConfigDict, Field

from synthetic_socio_wind_tunnel.memory.models import DailySummary, MemoryEvent


class CarryoverContext(BaseModel):
    """次日 planner 所需的历史上下文。"""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    yesterday_summary: DailySummary | None = Field(
        default=None,
        description="day_index - 1 的 DailySummary；current=0 或缺失时为 None。",
    )
    recent_reflections: tuple[DailySummary, ...] = Field(
        default_factory=tuple,
        description=(
            "最近 3 天摘要（不含 yesterday_summary；按 day_index 升序）。"
            "Day 0 时为空 tuple。"
        ),
    )
    pending_task_anchors: tuple[MemoryEvent, ...] = Field(
        default_factory=tuple,
        description=(
            "kind='task_received' 且无对应 'action' 指示 completed 的 events，"
            "按 importance 降序、限 5 条。"
        ),
    )


__all__ = ["CarryoverContext"]
