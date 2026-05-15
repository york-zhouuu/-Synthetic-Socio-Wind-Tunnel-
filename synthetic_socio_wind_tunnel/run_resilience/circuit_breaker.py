"""
PerKeyCircuitBreaker — 多 key tier client 的 per-key 熔断器。

D1' 事故里 Gemini 单 key 被 4 worker 抢 quota，毒化叠加 4× 速。即便有
multi-key 轮询，单个 key 持续失败也会拖慢其他 key 的轮转。

状态机：

    closed ──(连续 N 次失败)──> open
       ↑                          │
       │ (探测成功)                │ (cooldown 到期)
       │                          ↓
    closed <──(探测失败 + 双倍 cooldown)── half_open

调用方约定：
    breaker = PerKeyCircuitBreaker()
    if not breaker.should_allow():
        skip this key
    try:
        result = await call(...)
        breaker.record_success()
    except Exception:
        breaker.record_failure()
        raise
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)


State = Literal["closed", "open", "half_open"]


_MAX_COOLDOWN_SECONDS: float = 1800.0  # 30 min cap


class AllKeysOpenError(RuntimeError):
    """所有 key 都处于 open 状态、暂时无 key 可用。"""

    def __init__(
        self, *, n_keys: int, next_available_at: float | None = None,
    ) -> None:
        msg = f"all {n_keys} keys open"
        if next_available_at is not None:
            msg += f"; next available at unix={next_available_at:.1f}"
        super().__init__(msg)
        self.n_keys = n_keys
        self.next_available_at = next_available_at


@dataclass
class PerKeyCircuitBreaker:
    """单个 key 的熔断状态。线程不安全（每 key 一个实例，在同一 event loop 内
    被单 worker 顺序访问，无并发）。"""

    failure_threshold: int = 5
    cooldown_seconds: float = 300.0
    _state: State = field(default="closed", init=False)
    _consecutive_failures: int = field(default=0, init=False)
    _open_until: float = field(default=0.0, init=False)
    _current_cooldown: float = field(default=0.0, init=False)
    _now_fn: object = field(default=time.monotonic, init=False, repr=False)

    def __post_init__(self) -> None:
        if self._current_cooldown == 0.0:
            self._current_cooldown = self.cooldown_seconds

    def _now(self) -> float:
        return self._now_fn()  # type: ignore[operator]

    @property
    def state(self) -> State:
        """读 state 时如果 cooldown 已到期，自动从 open 转 half_open。"""
        if self._state == "open" and self._now() >= self._open_until:
            self._state = "half_open"
        return self._state

    def should_allow(self) -> bool:
        """是否允许下一次调用（half_open 状态下放行一次探测）。"""
        return self.state != "open"

    def record_success(self) -> None:
        """成功调用后调用——重置失败计数 + cooldown，状态归 closed。"""
        self._state = "closed"
        self._consecutive_failures = 0
        self._current_cooldown = self.cooldown_seconds
        self._open_until = 0.0

    def record_failure(self) -> None:
        """失败调用后调用——失败计数累加，达阈值则 open。"""
        # half_open 探测失败 → 立即 open + 双倍 cooldown（capped）
        if self._state == "half_open":
            self._current_cooldown = min(
                self._current_cooldown * 2.0, _MAX_COOLDOWN_SECONDS,
            )
            self._state = "open"
            self._open_until = self._now() + self._current_cooldown
            return
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.failure_threshold:
            self._state = "open"
            self._open_until = self._now() + self._current_cooldown

    @property
    def next_available_at(self) -> float | None:
        """open 状态下下一次可探测的 monotonic 时间；其它状态返 None。"""
        if self._state == "open":
            return self._open_until
        return None

    @classmethod
    def from_env(cls) -> PerKeyCircuitBreaker:
        """读 RESILIENCE_CIRCUIT_* 环境变量构造。"""
        kwargs: dict[str, float | int] = {}
        ft = os.environ.get("RESILIENCE_CIRCUIT_FAILURE_THRESHOLD")
        if ft:
            try:
                kwargs["failure_threshold"] = int(ft)
            except ValueError:
                logger.warning(
                    "RESILIENCE_CIRCUIT_FAILURE_THRESHOLD=%r 无法解析", ft,
                )
        cd = os.environ.get("RESILIENCE_CIRCUIT_COOLDOWN")
        if cd:
            try:
                kwargs["cooldown_seconds"] = float(cd)
            except ValueError:
                logger.warning(
                    "RESILIENCE_CIRCUIT_COOLDOWN=%r 无法解析", cd,
                )
        return cls(**kwargs)  # type: ignore[arg-type]
