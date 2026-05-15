"""Tests for synthetic_socio_wind_tunnel.run_resilience.hotfix.

不在子进程跑——只测试 in-process signal handler 的注册/触发/idempotent。
对真正的 SIGUSR1 → partial 写盘 → exit 0 端到端流程，见
tests/test_hotfix_integration.py（Phase E）。
"""

from __future__ import annotations

import os
import signal
import time

import pytest

from synthetic_socio_wind_tunnel.run_resilience.hotfix import HotfixSignalHandler


class _DummyRunner:
    """最小 mock：仅承载 _graceful_stop_requested 标志。"""

    def __init__(self) -> None:
        self._graceful_stop_requested: bool = False


@pytest.fixture(autouse=True)
def _restore_handler() -> None:
    """每个 test 之后恢复 SIGUSR1 默认 handler，避免污染其它 test。"""
    prev = signal.signal(signal.SIGUSR1, signal.SIG_DFL)
    yield
    signal.signal(signal.SIGUSR1, prev)


def test_install_registers_sigusr1() -> None:
    runner = _DummyRunner()
    handler = HotfixSignalHandler()
    handler.install(runner)
    assert handler._installed is True
    current = signal.getsignal(signal.SIGUSR1)
    # handler._handle 是 bound method；getsignal 返回 callable，比较 callable 身份
    assert callable(current)
    handler.uninstall()


def test_sigusr1_sets_flag_only() -> None:
    runner = _DummyRunner()
    assert runner._graceful_stop_requested is False
    handler = HotfixSignalHandler()
    handler.install(runner)
    os.kill(os.getpid(), signal.SIGUSR1)
    # 给 OS 一点时间投递（in-process 信号通常立即）
    for _ in range(20):
        if runner._graceful_stop_requested:
            break
        time.sleep(0.05)
    assert runner._graceful_stop_requested is True


def test_double_sigusr1_idempotent() -> None:
    runner = _DummyRunner()
    handler = HotfixSignalHandler()
    handler.install(runner)
    os.kill(os.getpid(), signal.SIGUSR1)
    for _ in range(20):
        if runner._graceful_stop_requested:
            break
        time.sleep(0.05)
    assert runner._graceful_stop_requested is True
    # 第二次：flag 已 True，handler 应早退、不抛
    os.kill(os.getpid(), signal.SIGUSR1)
    time.sleep(0.1)
    assert runner._graceful_stop_requested is True


def test_sigterm_not_intercepted() -> None:
    """SIGTERM 行为 SHALL 不被 HotfixSignalHandler 改写。"""
    prev_term = signal.getsignal(signal.SIGTERM)
    handler = HotfixSignalHandler()
    runner = _DummyRunner()
    handler.install(runner)
    # SIGTERM handler 应当还是 install 之前的（多半是 SIG_DFL 或 pytest 的 wrapper）
    assert signal.getsignal(signal.SIGTERM) is prev_term


def test_uninstall_restores_previous_handler() -> None:
    runner = _DummyRunner()
    # 设一个非默认 handler 作为 'previous'
    def _sentinel(signum, frame):  # noqa: ARG001
        pass
    signal.signal(signal.SIGUSR1, _sentinel)

    handler = HotfixSignalHandler()
    handler.install(runner)
    assert signal.getsignal(signal.SIGUSR1) is not _sentinel
    handler.uninstall()
    # 恢复 sentinel
    assert signal.getsignal(signal.SIGUSR1) is _sentinel


def test_install_without_target_safe() -> None:
    handler = HotfixSignalHandler()
    # 没 target 就发信号，应该不抛
    handler._handle(signal.SIGUSR1, None)
