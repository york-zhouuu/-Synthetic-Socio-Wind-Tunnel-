"""
_MinimalTickDriver - 审计专用的最小驱动

在 Phase 2 orchestrator 建造之前，让 fitness-audit 能真刀真枪跑一组 agent 几个
tick，验证基建调用链通畅。

职责（刻意非常有限）：
- 推进 Ledger.current_time
- 对一组 agent 逐个按给定的目标 location 调 SimulationService.move_entity
- 对一组 agent 逐个调 PerceptionPipeline.render，返回 SubjectiveView 列表

**非**职责：并发调度、冲突裁决、路径相遇检测、Replan 触发——这些是 orchestrator
的工作，由后续 change 实现。驱动刻意不和 orchestrator spec 重叠。
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Mapping

from synthetic_socio_wind_tunnel.engine.simulation import SimulationService

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.atlas import Atlas
    from synthetic_socio_wind_tunnel.attention import AttentionService
    from synthetic_socio_wind_tunnel.ledger import Ledger
    from synthetic_socio_wind_tunnel.perception import PerceptionPipeline, SubjectiveView
    from synthetic_socio_wind_tunnel.perception.models import ObserverContext


class _MinimalTickDriver:
    """
    最小审计驱动。只做三件事：tick 时间推进 + 按命令移动 entity + 逐 agent 渲染感知。
    """

    def __init__(
        self,
        atlas: "Atlas",
        ledger: "Ledger",
        pipeline: "PerceptionPipeline",
        *,
        tick_minutes: int = 5,
        simulation: SimulationService | None = None,
    ) -> None:
        self._atlas = atlas
        self._ledger = ledger
        self._pipeline = pipeline
        self._tick_minutes = tick_minutes
        self._simulation = simulation or SimulationService(atlas, ledger)
        self._tick_index = 0

    @property
    def tick_index(self) -> int:
        return self._tick_index

    @property
    def simulation(self) -> SimulationService:
        return self._simulation

    def advance(self) -> None:
        """Advance one tick: bump Ledger.current_time by tick_minutes."""
        self._ledger.current_time = self._ledger.current_time + timedelta(
            minutes=self._tick_minutes
        )
        self._tick_index += 1

    def move_all(
        self,
        moves: Mapping[str, str],
    ) -> dict[str, bool]:
        """
        Apply a batch of moves `{agent_id: target_location_id}`.

        Returns `{agent_id: success_bool}`. Failures are swallowed (audits
        decide whether to flag them); caller can inspect SimulationService
        output by calling move_entity directly if needed.
        """
        results: dict[str, bool] = {}
        for agent_id, to_location in moves.items():
            r = self._simulation.move_entity(agent_id, to_location)
            results[agent_id] = r.success
        return results

    def render_all(
        self,
        contexts: Mapping[str, "ObserverContext"],
    ) -> dict[str, "SubjectiveView"]:
        """
        Render SubjectiveView for each agent. Read-only pass through pipeline.

        Returns `{agent_id: SubjectiveView}`.
        """
        out: dict[str, "SubjectiveView"] = {}
        for agent_id, ctx in contexts.items():
            out[agent_id] = self._pipeline.render(ctx)
        return out
