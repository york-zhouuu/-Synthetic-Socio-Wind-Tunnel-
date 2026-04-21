"""
Digital Attention Filter - 数字注意力滤镜

行为（realign-to-social-thesis spec）：

1. **未启用**：若 ObserverContext.digital_state is None，透传。
2. **注意力分配**：若 digital_state.attention_target == "phone_feed"，
   物理观察（VISUAL/AUDITORY/OLFACTORY）中 is_notable=True 的比例按
   (1 - attention_leakage) 下降；默认 leakage=0.3（刷手机时仍注意到 ~30% 物理事件）。
3. **推送注入**：每个 pending_notifications 的 feed_item_id 被注入为
   Observation(sense=DIGITAL)。注入逻辑由 PerceptionPipeline 在 gather 阶段完成
   （见 pipeline.py），filter 只负责对已注入的 DIGITAL observation 按
   notification_responsiveness 与 attention_target 调整 confidence / missed tag。
4. filter MUST NOT 写入 Ledger；MUST NOT 修改 AttentionService 的 pending 队列。

设计细节：
- Filter 的 apply() 是 per-observation 的。为保证 leakage 的统计学行为
  （"10 notable 降为 3 notable 的期望值"），使用注入的 rng 做每条观察的
  独立 Bernoulli(1-leakage) 试验。传同一 observation 两次调用 apply 可能
  得到不同结果——这是 intended，因为 perception 一次 render 调用只会对
  同一 observation 做一次 filter 应用。
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from synthetic_socio_wind_tunnel.perception.filters.base import Filter
from synthetic_socio_wind_tunnel.perception.models import Observation, SenseType

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.perception.models import ObserverContext


_PHYSICAL_SENSES = {SenseType.VISUAL, SenseType.AUDITORY, SenseType.OLFACTORY}


class DigitalAttentionFilter(Filter):
    """
    注意力漏损 + DIGITAL observation 打 missed tag。

    启用方式：PerceptionPipeline(..., include_digital_filter=True)
    """

    def __init__(
        self,
        *,
        attention_leakage: float = 0.3,
        rng: random.Random | None = None,
    ) -> None:
        """
        Args:
            attention_leakage: 刷手机时仍注意到物理事件的比例（0.3 = 30%）。
            rng: 注入的随机源（便于测试确定性）；None 时使用默认全局随机。
        """
        if not 0.0 <= attention_leakage <= 1.0:
            raise ValueError(
                f"attention_leakage must be in [0, 1], got {attention_leakage}"
            )
        self._attention_leakage = attention_leakage
        self._rng = rng or random.Random()

    def apply(
        self,
        observation: Observation,
        context: "ObserverContext",
    ) -> Observation | None:
        digital_state = context.digital_state

        # Branch 1: 未启用（digital_state is None）→ 透传
        if digital_state is None:
            return observation

        sense = observation.sense

        # Branch 2: 物理观察 + attention_target==phone_feed → 按 leakage 削减 notable
        if sense in _PHYSICAL_SENSES and digital_state.attention_target == "phone_feed":
            if observation.is_notable:
                # Bernoulli(attention_leakage)：通过率 = leakage
                # 例：leakage=0.3 时，10 条 notable 期望保留 3 条
                if self._rng.random() >= self._attention_leakage:
                    # 降级：is_notable → False（被忽略但不丢弃 observation）
                    return observation.model_copy(update={"is_notable": False})
            return observation

        # Branch 3: DIGITAL observation → 根据 responsiveness + attention_target 处理
        if sense == SenseType.DIGITAL:
            # responsiveness 作为初始 confidence（若未被上游设置）
            # profile-driven: 用 screen_time_hours 的值不好直接转；
            # 走从 digital_state 读不到 responsiveness 的话，confidence 保留不动。
            updates: dict = {}
            # 若 attention_target 不是 phone_feed 且推测用户正在忽略通知
            # （通过 attention_target != phone_feed 且 confidence < 0.5 的启发）
            if digital_state.attention_target != "phone_feed":
                # 仅当 confidence 低（意味着 responsiveness 低）时标 missed
                if observation.confidence < 0.5 and "missed" not in observation.tags:
                    updates["tags"] = observation.tags + ["missed"]
            if updates:
                return observation.model_copy(update=updates)
            return observation

        return observation
