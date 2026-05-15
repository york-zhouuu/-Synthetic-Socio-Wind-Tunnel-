"""Tests for HealthAudit's new WAL-based suspected_stuck dimension."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from synthetic_socio_wind_tunnel.run_resilience import HealthAudit


class _FakeProbe:
    """Lets us inject log/WAL mtimes deterministically."""

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
        self._now = now or datetime(2026, 5, 16, 17, 0, 0, tzinfo=timezone.utc)
        self._nofile_limit = nofile_limit

    def process_state(self, pid):
        return self._states.get(pid)

    def rss_bytes(self, pid):
        return self._rss.get(pid)

    def close_wait_count(self, pid):
        return self._close_wait.get(pid)

    def log_mtime(self, log_path: Path):
        return self._log_mtimes.get(log_path)

    def now(self):
        return self._now

    def nofile_limit(self):
        return self._nofile_limit


def _make_run_dir_with_wal(
    tmp_path: Path, *, wal_mtime_ago_sec: float,
    worker_pid: int = 100,
) -> tuple[Path, dict[Path, float]]:
    """Create run_dir with a worker_*.log + a variant_baseline/seed_42.wal.jsonl.
    Returns (run_dir, mtimes_dict for FakeProbe).
    """
    worker_log = tmp_path / "worker_baseline.log"
    worker_log.write_text(f"[setup] pid {worker_pid} starting\n")
    variant_dir = tmp_path / "variant_baseline"
    variant_dir.mkdir()
    wal = variant_dir / "seed_42.wal.jsonl"
    wal.write_text('{"tick_index": 100, "day_index": 0}\n')

    now = datetime(2026, 5, 16, 17, 0, 0, tzinfo=timezone.utc).timestamp()
    return tmp_path, {
        worker_log: now - 60,  # log fresh
        wal: now - wal_mtime_ago_sec,
    }


class TestWALSilenceDetection:

    def test_wal_fresh_no_stuck(self, tmp_path: Path) -> None:
        run_dir, mtimes = _make_run_dir_with_wal(tmp_path, wal_mtime_ago_sec=3.0)
        probe = _FakeProbe(
            states={100: "R"}, rss={100: 100}, close_wait={100: 5},
            log_mtimes=mtimes,
        )
        audit = HealthAudit(probe=probe, tick_seconds_expected=5.0)
        report = audit.audit(run_dir)
        # 3s < 5s expected × 10 = 50s warn → healthy
        assert report.overall_status == "healthy"
        for w in report.workers:
            assert "suspected_stuck" not in w.reasons
            assert "rising_wal_silence" not in w.reasons

    def test_wal_silent_warn_factor_10(self, tmp_path: Path) -> None:
        # 5s × 10 = 50s warn threshold; 60s > 50s but < 150s
        run_dir, mtimes = _make_run_dir_with_wal(
            tmp_path, wal_mtime_ago_sec=60.0,
        )
        probe = _FakeProbe(
            states={100: "R"}, rss={100: 100}, close_wait={100: 5},
            log_mtimes=mtimes,
        )
        audit = HealthAudit(
            probe=probe, tick_seconds_expected=5.0,
            stuck_warn_factor=10.0, stuck_deadlock_factor=30.0,
        )
        report = audit.audit(run_dir)
        # Should be warning, not deadlock
        reasons = [r for w in report.workers for r in w.reasons]
        assert "rising_wal_silence" in reasons
        assert "suspected_stuck" not in reasons

    def test_wal_silent_deadlock_factor_30(self, tmp_path: Path) -> None:
        # 5s × 30 = 150s; 200s > 150s → suspected_stuck
        run_dir, mtimes = _make_run_dir_with_wal(
            tmp_path, wal_mtime_ago_sec=200.0,
        )
        probe = _FakeProbe(
            states={100: "R"}, rss={100: 100}, close_wait={100: 5},
            log_mtimes=mtimes,
        )
        audit = HealthAudit(
            probe=probe, tick_seconds_expected=5.0,
            stuck_warn_factor=10.0, stuck_deadlock_factor=30.0,
        )
        report = audit.audit(run_dir)
        # suspected_stuck is single deadlock reason → status=warning unless 2+ trigger
        # Wait: _verdict requires >=2 deadlock reasons for suspected_deadlock
        # Here we have only 1 deadlock reason (suspected_stuck) → warning
        # That's by design — the WAL silence alone isn't conclusive
        reasons = [r for w in report.workers for r in w.reasons]
        assert "suspected_stuck" in reasons

    def test_wal_silent_plus_close_wait_deadlock(self, tmp_path: Path) -> None:
        """WAL silent + high close_wait = 2 deadlock reasons → overall deadlock."""
        run_dir, mtimes = _make_run_dir_with_wal(
            tmp_path, wal_mtime_ago_sec=200.0,
        )
        probe = _FakeProbe(
            states={100: "R"}, rss={100: 100},
            close_wait={100: 3800},  # high (vs nofile_limit 4096, ratio = 0.93)
            log_mtimes=mtimes,
            nofile_limit=4096,
        )
        audit = HealthAudit(
            probe=probe, tick_seconds_expected=5.0,
            stuck_warn_factor=10.0, stuck_deadlock_factor=30.0,
        )
        report = audit.audit(run_dir)
        assert report.overall_status == "suspected_deadlock"

    def test_no_wal_files_no_stuck_check(self, tmp_path: Path) -> None:
        """If run_dir has no WAL files, suspected_stuck SHALL NOT fire."""
        worker_log = tmp_path / "worker_baseline.log"
        worker_log.write_text("[setup] pid 100 starting\n")
        now = datetime(2026, 5, 16, 17, 0, 0, tzinfo=timezone.utc).timestamp()
        probe = _FakeProbe(
            states={100: "R"}, rss={100: 100}, close_wait={100: 5},
            log_mtimes={worker_log: now - 30},
        )
        audit = HealthAudit(probe=probe)
        report = audit.audit(tmp_path)
        reasons = [r for w in report.workers for r in w.reasons]
        assert "suspected_stuck" not in reasons
        assert "rising_wal_silence" not in reasons

    def test_env_override_tick_seconds(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("RESILIENCE_HEALTH_TICK_SECONDS_EXPECTED", "10")
        monkeypatch.setenv("RESILIENCE_HEALTH_STUCK_WARN_FACTOR", "5")
        monkeypatch.setenv("RESILIENCE_HEALTH_STUCK_DEADLOCK_FACTOR", "20")
        audit = HealthAudit(probe=_FakeProbe())
        assert audit.tick_seconds_expected == 10.0
        assert audit.stuck_warn_factor == 5.0
        assert audit.stuck_deadlock_factor == 20.0
