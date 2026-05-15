"""Tests for synthetic_socio_wind_tunnel.run_resilience.circuit_breaker."""

from __future__ import annotations

import pytest

from synthetic_socio_wind_tunnel.run_resilience.circuit_breaker import (
    AllKeysOpenError,
    PerKeyCircuitBreaker,
)


class _Clock:
    """可控的 monotonic clock 用于测试。"""

    def __init__(self, start: float = 1000.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, dt: float) -> None:
        self._now += dt


def _make_breaker(
    *, failure_threshold: int = 5, cooldown_seconds: float = 300.0,
) -> tuple[PerKeyCircuitBreaker, _Clock]:
    clock = _Clock()
    b = PerKeyCircuitBreaker(
        failure_threshold=failure_threshold,
        cooldown_seconds=cooldown_seconds,
    )
    b._now_fn = clock  # type: ignore[assignment]
    return b, clock


def test_initial_state_closed() -> None:
    b, _ = _make_breaker()
    assert b.state == "closed"
    assert b.should_allow() is True


def test_n_failures_open() -> None:
    b, _ = _make_breaker(failure_threshold=5)
    for _ in range(4):
        b.record_failure()
    assert b.state == "closed"
    b.record_failure()  # 第 5 次
    assert b.state == "open"
    assert b.should_allow() is False


def test_open_blocks_calls() -> None:
    b, _ = _make_breaker(failure_threshold=3)
    for _ in range(3):
        b.record_failure()
    assert b.should_allow() is False


def test_cooldown_expires_half_open() -> None:
    b, clock = _make_breaker(failure_threshold=2, cooldown_seconds=60.0)
    b.record_failure()
    b.record_failure()
    assert b.state == "open"
    clock.advance(30)
    assert b.state == "open"  # 还没到
    clock.advance(31)         # 总共 61s > 60s
    assert b.state == "half_open"
    assert b.should_allow() is True


def test_half_open_success_back_to_closed() -> None:
    b, clock = _make_breaker(failure_threshold=2, cooldown_seconds=60.0)
    b.record_failure()
    b.record_failure()
    clock.advance(61)
    assert b.state == "half_open"
    b.record_success()
    assert b.state == "closed"
    assert b._consecutive_failures == 0  # type: ignore[attr-defined]


def test_half_open_failure_back_to_open_with_doubled_cooldown() -> None:
    b, clock = _make_breaker(failure_threshold=2, cooldown_seconds=60.0)
    b.record_failure()
    b.record_failure()
    # 初次 cooldown=60
    clock.advance(61)
    assert b.state == "half_open"
    b.record_failure()  # half_open 探测失败 → cooldown 翻倍 = 120
    assert b.state == "open"
    clock.advance(61)
    assert b.state == "open"  # 还在 cooldown 中
    clock.advance(61)         # 122s 后才 half_open
    assert b.state == "half_open"


def test_cooldown_capped_at_30_min() -> None:
    b, clock = _make_breaker(failure_threshold=1, cooldown_seconds=900.0)  # 15 min
    b.record_failure()
    # 反复 half_open 失败：900 → 1800 → 1800 (capped)
    for _ in range(5):
        # 让它进入 half_open
        clock.advance(b._current_cooldown + 1)  # type: ignore[attr-defined]
        assert b.state == "half_open"
        b.record_failure()
    assert b._current_cooldown == pytest.approx(1800.0)  # type: ignore[attr-defined]


def test_record_success_resets_failure_count() -> None:
    b, _ = _make_breaker(failure_threshold=5)
    b.record_failure()
    b.record_failure()
    b.record_success()
    assert b._consecutive_failures == 0  # type: ignore[attr-defined]
    # 再失败 4 次仍不 open
    for _ in range(4):
        b.record_failure()
    assert b.state == "closed"


def test_all_keys_open_error_attaches_info() -> None:
    err = AllKeysOpenError(n_keys=3, next_available_at=1234.5)
    assert err.n_keys == 3
    assert err.next_available_at == 1234.5
    assert "3 keys open" in str(err)


def test_from_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESILIENCE_CIRCUIT_FAILURE_THRESHOLD", "10")
    monkeypatch.setenv("RESILIENCE_CIRCUIT_COOLDOWN", "120.0")
    b = PerKeyCircuitBreaker.from_env()
    assert b.failure_threshold == 10
    assert b.cooldown_seconds == 120.0


def test_from_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESILIENCE_CIRCUIT_FAILURE_THRESHOLD", raising=False)
    monkeypatch.delenv("RESILIENCE_CIRCUIT_COOLDOWN", raising=False)
    b = PerKeyCircuitBreaker.from_env()
    assert b.failure_threshold == 5
    assert b.cooldown_seconds == 300.0
