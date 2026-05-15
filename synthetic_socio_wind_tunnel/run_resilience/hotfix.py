"""
HotfixSignalHandler — graceful-stop 协议。

D1' 事故后用户最强调的能力是"如果跑起来真卡死，要保证热修复"。本模块定义
worker 进程接 SIGUSR1 时的优雅退出语义：

1. 收到 SIGUSR1 → 设置 runner._graceful_stop_requested = True
2. MultiDayRunner 主循环在每 tick 后检查 flag
3. flag 为 True → 不再启动下一 tick → 写 partial → 返回截断 MultiDayResult
4. 调用方决定是否 sys.exit(0)

SIGUSR1 选择见 design.md D4：SIGTERM 已被 ThreadPoolExecutor coordinator 用于
强终止 child；SIGUSR2 留给未来 dump diagnostics。

signal handler **不**做 I/O（async-signal-safe 约束）；只置 flag。
"""

from __future__ import annotations

import logging
import signal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.orchestrator.multi_day import MultiDayRunner

logger = logging.getLogger(__name__)


_GRACEFUL_STOP_SIGNAL = signal.SIGUSR1


class HotfixSignalHandler:
    """注册 SIGUSR1 handler；安装在 worker 进程的 main 线程。

    使用：

        runner = MultiDayRunner(...)
        handler = HotfixSignalHandler()
        handler.install(runner)
        result = runner.run_multi_day(...)
        # 若期间收到 SIGUSR1：result.per_day_summaries 长度 < num_days
    """

    def __init__(self) -> None:
        self._installed: bool = False
        self._target: "MultiDayRunner | None" = None
        self._previous_handler: object = None

    def install(self, runner: "MultiDayRunner") -> None:
        """注册 SIGUSR1 handler 给 `runner`。

        重复 install 会覆盖前一个 target（同一进程只允许一个 runner 在跑）。
        """
        self._target = runner
        if not self._installed:
            self._previous_handler = signal.signal(
                _GRACEFUL_STOP_SIGNAL, self._handle,
            )
            self._installed = True
            logger.info(
                "HotfixSignalHandler installed: send SIGUSR1 (kill -USR1 <pid>) "
                "for graceful stop + checkpoint",
            )

    def uninstall(self) -> None:
        """恢复之前的 handler（一般用于测试 tear-down）。"""
        if not self._installed:
            return
        signal.signal(_GRACEFUL_STOP_SIGNAL, self._previous_handler)  # type: ignore[arg-type]
        self._installed = False
        self._target = None

    def _handle(self, signum: int, frame: object) -> None:  # noqa: ARG002
        """signal handler——只置 flag，不做 I/O / logging.warn 之类。

        Python 的 logging 不严格 async-signal-safe；用 stderr 直写时也只发
        一行最小消息，但保守起见这里不调任何 I/O。MultiDayRunner 主循环
        看到 flag 后会自己 log。
        """
        runner = self._target
        if runner is None:
            return
        if getattr(runner, "_graceful_stop_requested", False):
            # 幂等——双发不重置
            return
        runner._graceful_stop_requested = True  # type: ignore[attr-defined]
