"""
Intent — orchestrator 与 agent 之间的"想做什么"契约

每 tick 每 agent 一个 Intent。Orchestrator 收集 Intent 后：
- 非独占类（Move/Wait/Examine）：直接提交到 SimulationService
- 独占类（Pickup/OpenDoor/Unlock/Lock）：按 target_id 分组 + agent_id
  字典序裁决，赢家提交，失败者收 PRECONDITION_FAILED

所有 Intent frozen + 可哈希（便于 orchestrator 内部 dict/set 使用）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Intent:
    """Intent 基类。子类不应直接构造此基类。"""

    @property
    def exclusive(self) -> bool:
        """是否需要进入冲突裁决器。"""
        raise NotImplementedError

    @property
    def target_id(self) -> str | None:
        """独占 Intent 的裁决 key；非独占返回 None。"""
        return None


# ==================== 非独占 ====================

@dataclass(frozen=True)
class MoveIntent(Intent):
    """移动到目标 location。orchestrator 按 NavigationResult.steps 逐步执行。"""

    to_location: str

    @property
    def exclusive(self) -> bool:
        return False


@dataclass(frozen=True)
class WaitIntent(Intent):
    """原地等待。不产生 WorldEvent。"""

    reason: str = ""

    @property
    def exclusive(self) -> bool:
        return False


@dataclass(frozen=True)
class ExamineIntent(Intent):
    """检查某物（item / container / clue）。映射到 mark_item_examined。"""

    target: str

    @property
    def exclusive(self) -> bool:
        return False


# ==================== 独占 ====================

@dataclass(frozen=True)
class PickupIntent(Intent):
    """拾取物品。多 agent 抢同一 item 时走裁决。"""

    item_id: str

    @property
    def exclusive(self) -> bool:
        return True

    @property
    def target_id(self) -> str:
        return self.item_id


@dataclass(frozen=True)
class OpenDoorIntent(Intent):
    """开门。"""

    door_id: str

    @property
    def exclusive(self) -> bool:
        return True

    @property
    def target_id(self) -> str:
        return self.door_id


@dataclass(frozen=True)
class UnlockIntent(Intent):
    """解锁门（可选 key）。"""

    door_id: str
    key_id: str | None = None

    @property
    def exclusive(self) -> bool:
        return True

    @property
    def target_id(self) -> str:
        return self.door_id


@dataclass(frozen=True)
class LockIntent(Intent):
    """锁门（可选 key）。"""

    door_id: str
    key_id: str | None = None

    @property
    def exclusive(self) -> bool:
        return True

    @property
    def target_id(self) -> str:
        return self.door_id
