"""Layer 1 — spawn-stagger guard helpers (Phase G1 of stagger-worker-spawn).

Spec: openspec/specs/worker-spawn-coordination/spec.md
Requirement: "最小 spawn 间隔强制 (in-code)" + "spawn timestamp 持久化协议"

TDD red phase: helpers don't exist yet → ImportError expected.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest


def _get_helpers():
    """Import the guard helpers (added by G5 of stagger-worker-spawn)."""
    from tools.resume_publishable import (
        _read_last_spawn_timestamp,
        _spawn_allowed_now,
        _write_last_spawn_timestamp,
    )
    return _read_last_spawn_timestamp, _write_last_spawn_timestamp, _spawn_allowed_now


@pytest.fixture
def tmp_timestamp_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the guard at a per-test timestamp file."""
    path = tmp_path / "spawn-ts.json"
    # Helpers read TIMESTAMP_PATH module-level; we patch via env so tests
    # are hermetic. G5 SHALL respect this env override.
    monkeypatch.setenv("SPAWN_STAGGER_TIMESTAMP_FILE", str(path))
    return path


def test_first_spawn_allowed_when_no_timestamp_file(tmp_timestamp_file: Path) -> None:
    """spec scenario: timestamp 文件不存在第一次 spawn 允许."""
    _, _, spawn_allowed_now = _get_helpers()
    assert not tmp_timestamp_file.exists()
    allowed, wait_secs, reason = spawn_allowed_now(min_spacing_secs=300)
    assert allowed is True
    assert wait_secs == 0.0
    assert "no_previous_spawn" in reason or "first" in reason.lower()


def test_second_spawn_within_window_deferred(tmp_timestamp_file: Path) -> None:
    """spec scenario: 5 分钟内连续 2 次 spawn 第 2 次被拒."""
    read_ts, write_ts, spawn_allowed_now = _get_helpers()
    write_ts({"seed": 42, "variant": "baseline"})
    # Immediately after: must defer
    allowed, wait_secs, reason = spawn_allowed_now(min_spacing_secs=300)
    assert allowed is False
    assert wait_secs > 0
    assert wait_secs <= 300
    assert "stagger" in reason.lower() or "spacing" in reason.lower()


def test_second_spawn_after_window_allowed(
    tmp_timestamp_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """spec scenario: 满 5 分钟后第 2 次 spawn 允许."""
    _, write_ts, spawn_allowed_now = _get_helpers()
    # Write timestamp 400 seconds in the past
    past_epoch = time.time() - 400
    tmp_timestamp_file.write_text(json.dumps({
        "last_spawn_epoch": past_epoch,
        "last_spawn_iso": "2026-05-19T12:00:00+00:00",
        "last_spawn_cell": {"seed": 42, "variant": "baseline"},
        "version": 1,
    }))
    allowed, wait_secs, reason = spawn_allowed_now(min_spacing_secs=300)
    assert allowed is True
    assert wait_secs == 0.0


def test_corrupted_timestamp_file_falls_back_to_allow(
    tmp_timestamp_file: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """spec scenario: timestamp 文件损坏 fallback 允许 spawn (conservative)."""
    _, _, spawn_allowed_now = _get_helpers()
    tmp_timestamp_file.write_text("not valid json {{")
    import logging
    with caplog.at_level(logging.WARNING):
        allowed, _, reason = spawn_allowed_now(min_spacing_secs=300)
    assert allowed is True
    assert "corrupt" in reason.lower() or "invalid" in reason.lower()


def test_clock_backward_resets_timestamp(
    tmp_timestamp_file: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """spec scenario: 系统时钟回拨保守处理 — last_spawn_epoch > now → reset."""
    _, _, spawn_allowed_now = _get_helpers()
    future_epoch = time.time() + 10000  # pretend last spawn was in the future
    tmp_timestamp_file.write_text(json.dumps({
        "last_spawn_epoch": future_epoch,
        "last_spawn_iso": "2099-01-01T00:00:00+00:00",
        "last_spawn_cell": {"seed": 42, "variant": "baseline"},
        "version": 1,
    }))
    import logging
    with caplog.at_level(logging.WARNING):
        allowed, _, reason = spawn_allowed_now(min_spacing_secs=300)
    assert allowed is True
    assert "clock" in reason.lower() or "backward" in reason.lower()


def test_env_zero_disables_guard(tmp_timestamp_file: Path) -> None:
    """spec scenario: env override 关闭 spacing — even immediately after spawn."""
    _, write_ts, spawn_allowed_now = _get_helpers()
    write_ts({"seed": 42, "variant": "baseline"})
    # Immediately after; min_spacing=0 SHALL skip comparison
    allowed, wait_secs, _ = spawn_allowed_now(min_spacing_secs=0)
    assert allowed is True
    assert wait_secs == 0.0


def test_write_then_read_round_trip(tmp_timestamp_file: Path) -> None:
    """spec: timestamp file contains 4 documented fields + version=1."""
    read_ts, write_ts, _ = _get_helpers()
    write_ts({"seed": 43, "variant": "phone_friction"})
    data = read_ts()
    assert data is not None
    assert isinstance(data["last_spawn_epoch"], float)
    assert isinstance(data["last_spawn_iso"], str)
    assert data["last_spawn_cell"] == {"seed": 43, "variant": "phone_friction"}
    assert data["version"] == 1


def test_atomic_write_via_tempfile(tmp_timestamp_file: Path) -> None:
    """spec: atomic write via tempfile+rename (defensive against partial reads).

    We verify the helper uses tempfile mechanism by checking no `.tmp` files
    are left behind after a successful write."""
    _, write_ts, _ = _get_helpers()
    write_ts({"seed": 42, "variant": "baseline"})
    # No stray temp files in the parent directory
    leftovers = [p for p in tmp_timestamp_file.parent.iterdir()
                 if p.name != tmp_timestamp_file.name
                 and (p.suffix == ".tmp" or ".tmp" in p.name)]
    assert leftovers == [], f"stray temp files: {leftovers}"
