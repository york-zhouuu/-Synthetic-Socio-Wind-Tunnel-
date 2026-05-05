"""
social_graph — pairwise tie 累积层（基于 Granovetter 弱关系框架）

把 orchestrator 派生的瞬时 encounter 流（`tick_result.encounter_candidates`）
转化为 persistent pairwise ties。Tie strength 用 N/(N+K) 公式（K=10），
1 次 encounter ≈ 0.09，10 次 ≈ 0.50（weak tie 阈值），30 次 ≈ 0.75。

不做：tie decay（V2）/ 多方对话（conversation-capability）/ 数字社交 /
历史回填。
"""

from synthetic_socio_wind_tunnel.social_graph.models import Tie
from synthetic_socio_wind_tunnel.social_graph.service import (
    SocialGraphService,
    WEAK_TIE_THRESHOLD,
    STRONG_TIE_THRESHOLD,
)

__all__ = [
    "STRONG_TIE_THRESHOLD",
    "SocialGraphService",
    "Tie",
    "WEAK_TIE_THRESHOLD",
]
