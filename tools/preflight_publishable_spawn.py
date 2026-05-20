#!/usr/bin/env python3
"""preflight_publishable_spawn — automated gate before publishable spawn.

backlog 1.15 (2026-05-20): every publishable spawn is real-LLM cost +
~1 night of machine time. Missing one check (env var unset, disk
nearly full, instrumentation phase event not firing, stale worker
holding a lock) → spawn dies partway → wasted night.

This script runs the "before-spawn checklist" automatically and
exits non-zero on any blocker, so spawning becomes:

    ./tools/preflight_publishable_spawn.py <suite_dir> [--seed N] \\
        [--variant baseline] [--skip-smoke] && nohup ... &

Each check is independent and reports its result on stdout. Exit codes:
- 0 — all checks pass; safe to spawn
- 1 — at least one blocker (spawn SHALL NOT proceed)
- 2 — non-blocker warnings only (spawn at user discretion)

Checks (numbered to match docs/backlog.md 1.15):

1. STATIC: required env vars + python interp + psutil import
2. CELL STATE: no stale worker process; if resuming, recommend
   --resume-strategy via audit_resume_strategies
3. RESOURCE CAPACITY: disk free, swap pressure
4. INSTRUMENTATION SMOKE: 5-second dev smoke run + verify all 9
   PHASE events fire in events.jsonl
5. SPAWN COMMAND: print the canonical spawn command for copy-paste

Env to suppress checks (use sparingly):
- PREFLIGHT_SKIP_SMOKE=1 — skip the 5-sec smoke (CI / quick iterate)
- PREFLIGHT_SKIP_NETWORK=1 — skip DeepSeek/Gemini ping
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent

_RECOMMENDED_ENV = {
    # 2026-05-20 Plan B: post-hang investigation tightening.
    # RSS_RESTART_MB 10000 → 6000: proactive process recycle every ~2-3hr.
    # Three new tighter LLM timeout settings cap hang impact to 60-90s.
    "RSS_RESTART_MB": "6000",
    "MEMORY_EVENT_EVICT_GRACE_DAYS": "2",
    "SNAPSHOT_PRUNE_BEFORE_WRITE": "1",
    "GC_EVERY_N_TICKS": "200",
    "RSS_CHECK_EVERY_N_TICKS": "50",
    "RESILIENCE_SNAPSHOT_EVERY_TICKS": "12",
    "RESILIENCE_WAL_ENABLED": "true",
    "OPERATION_POOL_HANDLER_TIMEOUT_SEC": "90",
    "OPERATION_POOL_MAX_CONCURRENT_OPS": "200",
    "RESILIENCE_POOL_READ_TIMEOUT": "60",
    "RESILIENCE_RETRY_MAX_ATTEMPTS": "2",
}

_REQUIRED_PHASE_EVENTS = (
    "PROCESS_START",
    "SETUP_START",
    "SETUP_DONE",
    "TICK_LOOP_START",
    "DAY_START",
    "DAY_END",
    "EXIT",
)
# Note: SNAPSHOT_LOAD_START/DONE only fire on resume; not required on fresh
# smoke. Listed in 8-class spec but conditional.


@dataclass
class CheckResult:
    name: str
    ok: bool
    severity: str  # "blocker" / "warning" / "info"
    message: str


def _check_python_and_imports() -> CheckResult:
    """Static: venv python + psutil + key deps importable."""
    venv_py = REPO_ROOT / ".venv/bin/python"
    if not venv_py.exists():
        return CheckResult(
            "python_venv", False, "blocker",
            f".venv/bin/python missing at {venv_py}",
        )
    code = (
        "import psutil, pydantic, scipy, "
        "synthetic_socio_wind_tunnel as s; "
        "print('imports OK', s.__name__)"
    )
    try:
        proc = subprocess.run(
            [str(venv_py), "-c", code],
            capture_output=True, text=True, timeout=15, cwd=REPO_ROOT,
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            "python_venv", False, "blocker",
            "import probe timed out (>15s) — venv may be broken",
        )
    if proc.returncode != 0:
        return CheckResult(
            "python_venv", False, "blocker",
            f"import probe failed: {proc.stderr.strip()[:300]}",
        )
    return CheckResult("python_venv", True, "info", "venv + key imports OK")


def _check_env_vars() -> CheckResult:
    """Required env vars for safe publishable spawn."""
    missing = []
    for k, recommended in _RECOMMENDED_ENV.items():
        if k not in os.environ:
            missing.append(f"{k} (recommend {recommended})")
    if missing:
        return CheckResult(
            "env_vars", False, "warning",
            "missing/unset: " + "; ".join(missing),
        )
    return CheckResult(
        "env_vars", True, "info",
        f"all {len(_RECOMMENDED_ENV)} recommended env vars set",
    )


def _check_watchdog_available() -> CheckResult:
    """Plan B.3 (2026-05-20): watchdog is 5th observer channel, required.

    `tools/watchdog_wal_deadlock.py` auto-detects WAL stale > 300s and
    SIGUSR1→SIGTERM→SIGKILL hung worker + resume from snapshot. Without
    it, every recurring asyncio/httpx hang (backlog 1.9) loses 25-30 min
    of human attention. Verify the binary exists + imports cleanly."""
    wd = REPO_ROOT / "tools" / "watchdog_wal_deadlock.py"
    if not wd.exists():
        return CheckResult(
            "watchdog", False, "blocker",
            f"watchdog binary missing at {wd} — spawn cannot auto-recover hangs",
        )
    # Import-test
    venv_py = REPO_ROOT / ".venv/bin/python"
    try:
        proc = subprocess.run(
            [str(venv_py), str(wd), "--help"],
            capture_output=True, text=True, timeout=10, cwd=REPO_ROOT,
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            "watchdog", False, "warning",
            "watchdog --help timed out — script may be broken",
        )
    if proc.returncode != 0:
        return CheckResult(
            "watchdog", False, "warning",
            f"watchdog --help failed: {proc.stderr[-200:]}",
        )
    return CheckResult(
        "watchdog", True, "info",
        "watchdog_wal_deadlock.py available — remember to start it as obs channel #6",
    )


def _check_disk_free(min_gb: int = 30) -> CheckResult:
    """Resource: disk free > 30 GB."""
    usage = shutil.disk_usage(str(REPO_ROOT))
    free_gb = usage.free / (1024 ** 3)
    if free_gb < min_gb:
        return CheckResult(
            "disk_free", False, "blocker",
            f"only {free_gb:.1f} GB free (need ≥ {min_gb} GB)",
        )
    return CheckResult(
        "disk_free", True, "info",
        f"{free_gb:.1f} GB free (≥ {min_gb} GB required)",
    )


def _check_no_stale_worker() -> CheckResult:
    """No stray run_variant_suite.py worker (would race for resources)."""
    try:
        proc = subprocess.run(
            ["pgrep", "-fl", "run_variant_suite.py"],
            capture_output=True, text=True, timeout=5,
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            "stale_worker", False, "warning",
            "pgrep timed out — couldn't check for stale workers",
        )
    # pgrep returns 1 when no matches — that's the happy path
    if proc.returncode == 1:
        return CheckResult(
            "stale_worker", True, "info", "no stale run_variant_suite worker",
        )
    if proc.returncode == 0:
        lines = [l for l in proc.stdout.splitlines() if l.strip()]
        return CheckResult(
            "stale_worker", False, "blocker",
            f"{len(lines)} stale worker(s):\n    "
            + "\n    ".join(lines[:5]),
        )
    return CheckResult(
        "stale_worker", False, "warning",
        f"pgrep exit={proc.returncode}: {proc.stderr.strip()}",
    )


def _check_swap_pressure() -> CheckResult:
    """macOS: memory_pressure ≠ critical."""
    if sys.platform != "darwin":
        return CheckResult(
            "swap_pressure", True, "info",
            "skipping (non-macOS platform)",
        )
    try:
        proc = subprocess.run(
            ["memory_pressure"], capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return CheckResult(
            "swap_pressure", True, "info",
            "memory_pressure unavailable — skipping",
        )
    text = proc.stdout
    if "critical" in text.lower() or "warn" in text.lower():
        # extract the relevant line
        relevant = next(
            (l for l in text.splitlines() if "pressure" in l.lower()),
            text[:200],
        )
        return CheckResult(
            "swap_pressure", False, "warning",
            f"non-normal memory pressure: {relevant.strip()}",
        )
    return CheckResult(
        "swap_pressure", True, "info", "memory_pressure normal",
    )


_SMOKE_TIMEOUT_SEC = 180


def _check_instrumentation_smoke() -> CheckResult:
    """Run a 10-agent × 1-day dev smoke with the stub provider, then
    verify that events.jsonl contains every required PHASE event.

    This catches the failure mode where a phase emit was added to the
    spec but not actually wired to the source. 2026-05-20 lesson: the
    9-phase event spec existed long before all 9 emits were wired."""
    if os.environ.get("PREFLIGHT_SKIP_SMOKE") == "1":
        return CheckResult(
            "instrumentation_smoke", True, "info",
            "skipped via PREFLIGHT_SKIP_SMOKE=1",
        )

    venv_py = REPO_ROOT / ".venv/bin/python"
    with tempfile.TemporaryDirectory(prefix="swt-preflight-") as td:
        out = Path(td)
        env = dict(os.environ)
        env["INSTRUMENTATION_OUTPUT_DIR"] = str(out)
        env["INSTRUMENTATION_SEED"] = "999"
        # smoke needs a real run dir — let run_variant_suite create it
        # under output-dir, then we point INSTRUMENTATION at out for
        # the events.jsonl
        cmd = [
            str(venv_py), "tools/run_variant_suite.py",
            "--variants", "baseline",
            "--seeds", "1", "--seed-start", "999",
            "--num-days", "1", "--agents", "10",
            "--mode", "dev", "--phase-days", "1,0,0",
            "--output-dir", str(out / "suite"),
            "--suite-name", "preflight_smoke",
            "--skip-preflight",  # avoid recursion if 1000-agent preflight wraps us
            "--use-aitown", "--aitown-provider", "stub",
        ]
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, env=env,
                cwd=REPO_ROOT, timeout=_SMOKE_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired:
            return CheckResult(
                "instrumentation_smoke", False, "blocker",
                f"smoke exceeded {_SMOKE_TIMEOUT_SEC}s timeout — "
                f"setup phase may be hanging",
            )
        elapsed = time.monotonic() - t0

        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout)[-400:]
            return CheckResult(
                "instrumentation_smoke", False, "blocker",
                f"smoke exit={proc.returncode} after {elapsed:.1f}s; "
                f"stderr tail: {tail}",
            )

        # Find seed_999.events.jsonl
        events_files = list(out.rglob("seed_999.events.jsonl"))
        if not events_files:
            return CheckResult(
                "instrumentation_smoke", False, "blocker",
                f"smoke succeeded but seed_999.events.jsonl not found under {out}",
            )

        phases_seen: set[str] = set()
        with events_files[0].open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("kind") == "PHASE":
                    p = rec.get("phase")
                    if isinstance(p, str):
                        phases_seen.add(p)

        missing = [p for p in _REQUIRED_PHASE_EVENTS if p not in phases_seen]
        if missing:
            return CheckResult(
                "instrumentation_smoke", False, "blocker",
                f"missing PHASE events: {missing}; "
                f"seen={sorted(phases_seen)} — instrumentation broken",
            )
        return CheckResult(
            "instrumentation_smoke", True, "info",
            f"smoke OK ({elapsed:.1f}s); all {len(_REQUIRED_PHASE_EVENTS)} "
            f"required PHASE events present",
        )


def _check_resume_strategy(
    suite_dir: Path | None, seed: int | None,
) -> CheckResult:
    """If suite_dir + seed supplied, recommend --resume-strategy."""
    if suite_dir is None or seed is None:
        return CheckResult(
            "resume_strategy", True, "info",
            "skipped (no suite_dir/seed — fresh spawn)",
        )
    venv_py = REPO_ROOT / ".venv/bin/python"
    audit = REPO_ROOT / "tools/audit_resume_strategies.py"
    if not audit.exists():
        return CheckResult(
            "resume_strategy", False, "warning",
            f"audit_resume_strategies.py missing at {audit}",
        )
    try:
        proc = subprocess.run(
            [str(venv_py), str(audit), str(suite_dir), str(seed), "--json"],
            capture_output=True, text=True, cwd=REPO_ROOT, timeout=30,
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            "resume_strategy", False, "warning",
            "audit_resume_strategies timed out",
        )
    if proc.returncode != 0:
        return CheckResult(
            "resume_strategy", False, "warning",
            f"audit_resume_strategies exit={proc.returncode}: "
            f"{proc.stderr.strip()[:200]}",
        )
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return CheckResult(
            "resume_strategy", False, "warning",
            f"could not parse audit JSON: {proc.stdout[:200]}",
        )
    # `out` shape varies — surface as-is for human read
    return CheckResult(
        "resume_strategy", True, "info",
        f"audit recommends: {json.dumps(out, ensure_ascii=False)[:300]}",
    )


_CHECK_REGISTRY: list[tuple[str, Callable[[], CheckResult]]] = [
    ("python_venv", _check_python_and_imports),
    ("env_vars", _check_env_vars),
    ("disk_free", _check_disk_free),
    ("stale_worker", _check_no_stale_worker),
    ("swap_pressure", _check_swap_pressure),
    ("watchdog", _check_watchdog_available),
    ("instrumentation_smoke", _check_instrumentation_smoke),
]


_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_RESET = "\033[0m"


def _emit_result(r: CheckResult) -> None:
    if r.ok:
        icon = f"{_GREEN}✓{_RESET}"
    elif r.severity == "blocker":
        icon = f"{_RED}✗{_RESET}"
    else:
        icon = f"{_YELLOW}!{_RESET}"
    print(f"  {icon} {r.name}: {r.message}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="preflight_publishable_spawn",
        description="Run preflight checklist before publishable spawn.",
    )
    parser.add_argument("suite_dir", nargs="?", type=Path, default=None,
                        help="optional: existing suite to resume from")
    parser.add_argument("--seed", type=int, default=None,
                        help="seed N when resuming (with suite_dir)")
    parser.add_argument("--variant", type=str, default=None,
                        help="variant name (informational; surfaced in summary)")
    parser.add_argument("--skip-smoke", action="store_true",
                        help="skip the 5-sec instrumentation smoke")
    args = parser.parse_args(argv)

    if args.skip_smoke:
        os.environ["PREFLIGHT_SKIP_SMOKE"] = "1"

    print(f"\n=== preflight_publishable_spawn — repo {REPO_ROOT} ===\n")
    if args.suite_dir or args.seed or args.variant:
        print(
            f"  suite={args.suite_dir} seed={args.seed} "
            f"variant={args.variant}\n"
        )

    results: list[CheckResult] = []
    for _, fn in _CHECK_REGISTRY:
        try:
            r = fn()
        except Exception as exc:  # noqa: BLE001
            r = CheckResult(
                fn.__name__, False, "warning",
                f"check raised {type(exc).__name__}: {exc}",
            )
        results.append(r)
        _emit_result(r)

    # resume_strategy (parameterized — separately)
    rs = _check_resume_strategy(args.suite_dir, args.seed)
    results.append(rs)
    _emit_result(rs)

    blockers = [r for r in results if not r.ok and r.severity == "blocker"]
    warnings_ = [r for r in results if not r.ok and r.severity == "warning"]

    print()
    if blockers:
        print(
            f"{_RED}✗ {len(blockers)} blocker(s) — DO NOT spawn{_RESET}\n"
        )
        return 1
    if warnings_:
        print(
            f"{_YELLOW}! {len(warnings_)} warning(s) — review before "
            f"spawning{_RESET}\n"
        )
        return 2
    print(f"{_GREEN}✓ all preflight checks passed — safe to spawn{_RESET}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
