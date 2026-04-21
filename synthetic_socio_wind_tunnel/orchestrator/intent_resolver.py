"""
IntentResolver — 独占 Intent 的冲突裁决。

规则（spec 的 "Intent 冲突裁决" Requirement）：
- 非独占 Intent（Move/Wait/Examine）：直接进入提交队列
- 独占 Intent（Pickup/OpenDoor/Unlock/Lock）：按 target_id 分组，同组内
  按 agent_id 字典序取赢家；失败者记 reason="lost_to:<winner>"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from synthetic_socio_wind_tunnel.agent.intent import Intent


CommitStatus = Literal["commit", "rejected"]


@dataclass(frozen=True)
class CommitDecision:
    """IntentResolver 的每条产出：某 agent 的 Intent 应走 commit 还是 reject。"""

    agent_id: str
    intent: Intent
    status: CommitStatus
    reason: str = ""


class IntentResolver:
    """
    无状态纯函数服务。seed 目前不影响裁决（字典序稳定），预留。
    """

    __slots__ = ("_seed",)

    def __init__(self, seed: int = 0) -> None:
        self._seed = seed

    def resolve(
        self,
        intent_pool: Mapping[str, Intent],
    ) -> list[CommitDecision]:
        """
        输入 agent_id → Intent 的 mapping，输出 CommitDecision 列表。

        输出列表顺序：按 agent_id 字典序稳定。
        """
        decisions: list[CommitDecision] = []
        # 1. 独占类分组：target_id → list[(agent_id, intent)]
        exclusive_groups: dict[str, list[tuple[str, Intent]]] = {}
        for agent_id in sorted(intent_pool.keys()):
            intent = intent_pool[agent_id]
            if intent.exclusive:
                target = intent.target_id or ""
                exclusive_groups.setdefault(target, []).append((agent_id, intent))

        # 2. 每组按字典序取第一个为赢家；其它人 rejected
        winners: set[str] = set()
        losers: dict[str, str] = {}  # agent_id → winner_id
        for target, entries in exclusive_groups.items():
            entries.sort(key=lambda p: p[0])  # by agent_id
            winner_id = entries[0][0]
            winners.add(winner_id)
            for agent_id, _intent in entries[1:]:
                losers[agent_id] = winner_id

        # 3. 输出：按 agent_id 字典序
        for agent_id in sorted(intent_pool.keys()):
            intent = intent_pool[agent_id]
            if intent.exclusive and agent_id in losers:
                decisions.append(CommitDecision(
                    agent_id=agent_id,
                    intent=intent,
                    status="rejected",
                    reason=f"lost_to:{losers[agent_id]}",
                ))
            else:
                decisions.append(CommitDecision(
                    agent_id=agent_id,
                    intent=intent,
                    status="commit",
                    reason="",
                ))
        return decisions
