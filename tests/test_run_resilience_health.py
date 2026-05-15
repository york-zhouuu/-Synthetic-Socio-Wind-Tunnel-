"""Tests for synthetic_socio_wind_tunnel.run_resilience.health.

probe 抽象层让所有 ps/lsof/log_mtime 调用都可注入 fake，无需真启动子进程。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from synthetic_socio_wind_tunnel.run_resilience.health import (
    HealthAudit,
    HealthAuditReport,
)


class _FakeProbe:
    """全字段可控的 probe stub。"""

    def __init__(
        self,
        *,
        states: dict[int, str | None] | None = None,
        rss: dict[int, int | None] | None = None,
        close_wait: dict[int, int | None] | None = None,
        log_mtimes: dict[Path, float | None] | None = None,
        now: datetime | None = None,
        nofile_limit: int = 4096,
    ) -> None:
        self._states = states or {}
        self._rss = rss or {}
        self._close_wait = close_wait or {}
        self._log_mtimes = log_mtimes or {}
        self._now = now or datetime(2026, 5, 15, 17, 0, 0, tzinfo=timezone.utc)
        self._nofile_limit = nofile_limit

    def process_state(self, pid: int) -> str | None:
        return self._states.get(pid)

    def rss_bytes(self, pid: int) -> int | None:
        return self._rss.get(pid)

    def close_wait_count(self, pid: int) -> int | None:
        return self._close_wait.get(pid)

    def log_mtime(self, log_path: Path) -> float | None:
        return self._log_mtimes.get(log_path)

    def now(self) -> datetime:
        return self._now

    def nofile_limit(self) -> int:
        return self._nofile_limit


def _make_run_dir(tmp_path: Path, workers: dict[str, int]) -> Path:
    """tmp_path 下创建 worker_<name>.log 文件，内容含 'pid <N>'。"""
    for name, pid in workers.items():
        (tmp_path / f"worker_{name}.log").write_text(
            f"[setup] pid {pid} starting\nfoo\n",
        )
    return tmp_path


def test_audit_healthy_returns_healthy(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path, {"baseline": 100})
    log = tmp_path / "worker_baseline.log"
    now = datetime(2026, 5, 15, 17, 0, 0, tzinfo=timezone.utc)
    probe = _FakeProbe(
        states={100: "R"},
        rss={100: 200 * 1024 * 1024},
        close_wait={100: 30},
        log_mtimes={log: now.timestamp() - 300},  # 5 min ago
        now=now,
    )
    audit = HealthAudit(probe=probe)
    report = audit.audit(run_dir)
    assert report.overall_status == "healthy"
    assert len(report.workers) == 1
    assert report.workers[0].status == "healthy"
    assert report.workers[0].reasons == ()


def test_audit_silent_30min_returns_warning(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path, {"hp": 200})
    log = tmp_path / "worker_hp.log"
    now = datetime(2026, 5, 15, 17, 0, 0, tzinfo=timezone.utc)
    probe = _FakeProbe(
        states={200: "S"},
        rss={200: 100 * 1024 * 1024},
        close_wait={200: 10},
        log_mtimes={log: now.timestamp() - 1900},  # 31+ min ago
        now=now,
    )
    audit = HealthAudit(probe=probe)
    report = audit.audit(run_dir)
    assert report.overall_status == "warning"
    assert "silent_30min" in report.workers[0].reasons


def test_audit_silent_60min_plus_close_wait_deadlock(tmp_path: Path) -> None:
    """spec scenario: 静默 7h + 高 CLOSE_WAIT → suspected_deadlock。"""
    run_dir = _make_run_dir(tmp_path, {"baseline": 42814})
    log = tmp_path / "worker_baseline.log"
    now = datetime(2026, 5, 15, 18, 0, 0, tzinfo=timezone.utc)
    probe = _FakeProbe(
        states={42814: "U"},  # uninterruptible
        rss={42814: 240 * 1024 * 1024},
        close_wait={42814: 2200},  # 撞 ulimit 90%+
        log_mtimes={log: now.timestamp() - 7 * 3600},
        now=now,
        nofile_limit=2400,
    )
    audit = HealthAudit(probe=probe)
    report = audit.audit(run_dir)
    assert report.overall_status == "suspected_deadlock"
    reasons = report.workers[0].reasons
    assert "silent_60min" in reasons
    assert "high_close_wait" in reasons
    assert "uninterruptible_state" in reasons


def test_audit_uninterruptible_state_alone_is_warning(tmp_path: Path) -> None:
    """单一维度告警 = warning，不直接 deadlock。"""
    run_dir = _make_run_dir(tmp_path, {"hp": 300})
    log = tmp_path / "worker_hp.log"
    now = datetime(2026, 5, 15, 17, 0, 0, tzinfo=timezone.utc)
    probe = _FakeProbe(
        states={300: "U"},
        rss={300: 100 * 1024 * 1024},
        close_wait={300: 5},
        log_mtimes={log: now.timestamp() - 60},  # 1 min ago
        now=now,
    )
    audit = HealthAudit(probe=probe)
    report = audit.audit(run_dir)
    assert report.overall_status == "warning"
    assert "uninterruptible_state" in report.workers[0].reasons


def test_audit_high_close_wait_alone_is_warning(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path, {"pf": 400})
    log = tmp_path / "worker_pf.log"
    now = datetime(2026, 5, 15, 17, 0, 0, tzinfo=timezone.utc)
    probe = _FakeProbe(
        states={400: "R"},
        rss={400: 80 * 1024 * 1024},
        close_wait={400: 2300},
        log_mtimes={log: now.timestamp() - 60},
        now=now,
        nofile_limit=2400,
    )
    audit = HealthAudit(probe=probe)
    report = audit.audit(run_dir)
    assert report.overall_status == "warning"
    assert "high_close_wait" in report.workers[0].reasons


def test_audit_multiple_workers_aggregates_overall_status(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path, {"a": 1, "b": 2, "c": 3})
    now = datetime(2026, 5, 15, 17, 0, 0, tzinfo=timezone.utc)
    probe = _FakeProbe(
        states={1: "R", 2: "U", 3: "U"},
        rss={1: 100, 2: 100, 3: 100},
        close_wait={1: 5, 2: 5, 3: 2200},  # 3 命中 deadlock
        log_mtimes={
            tmp_path / "worker_a.log": now.timestamp() - 60,
            tmp_path / "worker_b.log": now.timestamp() - 1900,  # warning
            tmp_path / "worker_c.log": now.timestamp() - 7 * 3600,  # deadlock
        },
        now=now,
        nofile_limit=2400,
    )
    audit = HealthAudit(probe=probe)
    report = audit.audit(run_dir)
    # c worker 触发多维度 → deadlock；整体 deadlock
    assert report.overall_status == "suspected_deadlock"


def test_audit_no_workers_returns_warning(tmp_path: Path) -> None:
    audit = HealthAudit(probe=_FakeProbe())
    report = audit.audit(tmp_path)
    assert report.overall_status == "warning"
    assert report.workers == ()
    assert any("无 worker" in n for n in report.notes)


def test_audit_pids_json_fallback(tmp_path: Path) -> None:
    """log 内无 pid 时，pids.json 应被读出来。"""
    (tmp_path / "pids.json").write_text(json.dumps({"workers": [777]}))
    # 无 worker_*.log 也行
    now = datetime(2026, 5, 15, 17, 0, 0, tzinfo=timezone.utc)
    probe = _FakeProbe(
        states={777: "R"},
        rss={777: 100},
        close_wait={777: 1},
        log_mtimes={},
        now=now,
    )
    audit = HealthAudit(probe=probe)
    report = audit.audit(tmp_path)
    pids = [w.pid for w in report.workers]
    assert 777 in pids


def test_env_override_silent_thresholds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("RESILIENCE_HEALTH_SILENT_WARN_SECONDS", "10")
    monkeypatch.setenv("RESILIENCE_HEALTH_SILENT_DEADLOCK_SECONDS", "20")
    audit = HealthAudit(probe=_FakeProbe())
    assert audit.silent_warn_seconds == 10
    assert audit.silent_deadlock_seconds == 20


def test_report_is_frozen() -> None:
    r = HealthAuditReport(
        run_dir=Path("/tmp"),
        workers=(),
        overall_status="healthy",
        audited_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
    )
    with pytest.raises(Exception):
        r.overall_status = "warning"  # type: ignore[misc]
