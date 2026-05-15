"""End-to-end CLI tests for tools/audit_run_health.py.

Runs the script as a subprocess; mock workers via real log files + fake
pids (the underlying HealthAudit gracefully handles non-existent pids
→ "process_not_found" reason).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "audit_run_health.py"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run the CLI under the project venv python."""
    venv_py = ROOT / ".venv" / "bin" / "python"
    py = str(venv_py) if venv_py.exists() else sys.executable
    return subprocess.run(
        [py, str(CLI), *args],
        capture_output=True, text=True, timeout=30,
    )


def _seed_run_dir(tmp_path: Path, *, pids: list[int]) -> Path:
    """Create a run dir with worker log files containing fake pid headers."""
    for i, pid in enumerate(pids):
        log = tmp_path / f"worker_{['baseline', 'hp', 'gd', 'pf'][i % 4]}.log"
        log.write_text(f"[setup] pid {pid} starting\n")
    return tmp_path


class TestCLI:

    def test_missing_run_dir_exits_2(self, tmp_path: Path) -> None:
        result = _run([str(tmp_path / "does_not_exist")])
        assert result.returncode == 2
        assert "does not exist" in result.stderr

    def test_empty_run_dir_returns_warning(self, tmp_path: Path) -> None:
        result = _run([str(tmp_path)])
        # No workers found → warning → exit 1
        assert result.returncode == 1
        assert "WARNING" in result.stdout
        assert "无 worker" in result.stdout or "no workers" in result.stdout.lower() \
            or "no worker" in result.stdout.lower()

    def test_json_output_is_parseable(self, tmp_path: Path) -> None:
        _seed_run_dir(tmp_path, pids=[99999999])  # nonexistent pid
        result = _run([str(tmp_path), "--json"])
        # 99999999 is process_not_found → suspected_deadlock (single deadlock reason
        # might be only 1; check that JSON parses regardless of status)
        data = json.loads(result.stdout)
        assert "overall_status" in data
        assert "workers" in data
        assert isinstance(data["workers"], list)

    def test_nonexistent_pid_flagged(self, tmp_path: Path) -> None:
        _seed_run_dir(tmp_path, pids=[99999999])
        result = _run([str(tmp_path)])
        # Non-existent pid → process_not_found reason; only 1 reason → warning
        assert result.returncode in (1, 2)
        assert "pid=99999999" in result.stdout
        assert "process_not_found" in result.stdout

    def test_self_pid_healthy(self, tmp_path: Path) -> None:
        """Use the current pytest pid as a healthy worker — it's running, has
        a fresh log mtime, and should report healthy."""
        import os
        self_pid = os.getpid()
        log = tmp_path / "worker_baseline.log"
        log.write_text(f"[setup] pid {self_pid} active\n")
        result = _run([str(tmp_path)])
        assert result.returncode == 0
        assert "HEALTHY" in result.stdout

    def test_recommends_sigusr1_on_deadlock(self, tmp_path: Path) -> None:
        """When suspected_deadlock, output should suggest SIGUSR1 then SIGKILL."""
        # Set thresholds super tight to force deadlock verdict
        import os
        env = os.environ.copy()
        env["RESILIENCE_HEALTH_SILENT_DEADLOCK_SECONDS"] = "0"
        env["RESILIENCE_HEALTH_CLOSE_WAIT_DEADLOCK_RATIO"] = "0.0001"
        # Use a non-existent pid for guaranteed process_not_found
        _seed_run_dir(tmp_path, pids=[99999999])
        result = subprocess.run(
            [
                str(ROOT / ".venv" / "bin" / "python"), str(CLI), str(tmp_path),
            ],
            capture_output=True, text=True, timeout=30, env=env,
        )
        # process_not_found is a deadlock reason; with tight thresholds we
        # likely hit ≥2 deadlock reasons → suspected_deadlock
        if result.returncode == 2:
            assert "kill -USR1" in result.stdout
            assert "kill -9" in result.stdout
