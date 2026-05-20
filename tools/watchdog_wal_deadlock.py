#!/usr/bin/env python3
"""watchdog_wal_deadlock — auto-remediate stuck publishable workers.

D2 attempt 5 (2026-05-19) caught seed42_phone_friction hanging at
day-11 end. The audit_llm_health monitor fired a WAL-stale warning,
but the user had to manually diagnose + kill + relaunch. This script
removes the human from that loop.

Detection:
- Scan suite_dir(s) for variant_*/seed_*.wal.jsonl
- For each WAL, mtime older than --stale-secs (default 420s = 7 min)
  is a candidate for remediation. 420s is calibrated so a legitimate
  slow day-end (with 60s wait_for guards on every LLM call) cannot
  produce false positives — the worst-case batch of reflections is
  bounded by OperationPool's 120s wrap + per-handler 60s wait_for.

Confirmation:
- Re-check after --confirm-secs (default 60s) — if WAL still stale,
  we're committed to remediating.

Remediation:
- Find PID via `lsof` (PID holding the WAL file open for write)
- SIGUSR1 (30s grace) → SIGTERM (5s) → SIGKILL
- Spawn replacement via run_variant_suite.py with --resume

Safety:
- Single-shot per invocation: detect one stuck worker, remediate it,
  exit. The orchestrator (Monitor) should call us periodically.
- Dry-run mode (--dry-run) for testing.
- Will not act if no snapshot exists for that variant.

Exit codes:
    0 — no action needed (all WALs fresh) OR remediation successful
    1 — detected hang but couldn't remediate
    2 — invalid arguments / unrecoverable error

Usage:
    python tools/watchdog_wal_deadlock.py <suite_dir1> [<suite_dir2> ...]
    python tools/watchdog_wal_deadlock.py <suite_dir> --stale-secs 420 \\
        --confirm-secs 60 --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger("watchdog")


def _setup_log(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_path)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
    ))
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter(
        "[watchdog] %(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    ))
    logger.addHandler(fh)
    logger.addHandler(sh)
    logger.setLevel(logging.INFO)


def _find_pid_holding(path: Path) -> int | None:
    """Use lsof to find the PID writing this file."""
    try:
        out = subprocess.run(
            ["lsof", "-Fp", "--", str(path)],
            capture_output=True, text=True, timeout=10,
        )
    except Exception as exc:
        logger.error("lsof failed: %s", exc)
        return None
    for line in out.stdout.splitlines():
        if line.startswith("p"):
            try:
                return int(line[1:])
            except ValueError:
                continue
    return None


def _latest_snapshot(variant_dir: Path, seed: int) -> Path | None:
    """Find the most recent seed_<N>_tick<X>.snapshot.json."""
    candidates = sorted(
        variant_dir.glob(f"seed_{seed}_tick*.snapshot.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _send_signal_with_wait(pid: int, sig: int, wait_secs: int) -> bool:
    """Send signal, wait up to wait_secs for process to die. Return True if dead."""
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        return True
    except PermissionError:
        logger.error("PermissionError sending %s to pid %d", sig, pid)
        return False
    for _ in range(wait_secs):
        time.sleep(1)
        try:
            os.kill(pid, 0)  # signal 0 = check existence
        except ProcessLookupError:
            return True
    return False


def _kill_worker(pid: int) -> bool:
    """SIGUSR1 → SIGTERM → SIGKILL escalation."""
    logger.info("kill_worker: pid=%d (SIGUSR1 first)", pid)
    if _send_signal_with_wait(pid, signal.SIGUSR1, 30):
        logger.info("  ✓ exited via SIGUSR1 (graceful)")
        return True
    logger.warning("  SIGUSR1 ignored; escalating to SIGTERM")
    if _send_signal_with_wait(pid, signal.SIGTERM, 5):
        logger.info("  ✓ exited via SIGTERM")
        return True
    logger.warning("  SIGTERM ignored; escalating to SIGKILL")
    if _send_signal_with_wait(pid, signal.SIGKILL, 5):
        logger.info("  ✓ exited via SIGKILL")
        return True
    logger.error("  ✗ pid %d survived all signals", pid)
    return False


def _spawn_replacement(
    *,
    suite_dir: Path,
    variant: str,
    seed: int,
    workers: int = 1,
    log_path: Path | None = None,
) -> int | None:
    """Launch a new sub-suite for the dead variant; return PID."""
    if log_path is None:
        log_path = Path(f"/tmp/watchdog_restart_{suite_dir.name}_{variant}.log")
    cmd = [
        ".venv/bin/python3", "tools/run_variant_suite.py",
        "--variants", variant,
        "--seeds", "1",
        "--seed-start", str(seed),
        "--num-days", "14",
        "--agents", "1000",
        "--num-protagonists", "500",
        "--mode", "publishable",
        "--use-aitown",
        "--aitown-provider", "deepseek",
        "--workers", str(workers),
        "--suite-dir", str(suite_dir),
        "--resume",
        "--resume-strategy", "auto",
    ]
    env = os.environ.copy()
    env["RESILIENCE_TRUST_LAST_PREFLIGHT"] = "1"

    # 2026-05-21 NEW-A (watchdog-respawn-env-passthrough): read
    # spawn_env_<variant>.json if present and merge over os.environ.
    # Without this, watchdog respawn silently reverts to defaults for
    # all Plan B settings.
    spawn_env_file = suite_dir / f"spawn_env_{variant}.json"
    if spawn_env_file.exists():
        try:
            with spawn_env_file.open(encoding="utf-8") as fh:
                spawn_env = json.load(fh)
            if isinstance(spawn_env, dict):
                for k, v in spawn_env.items():
                    env[str(k)] = str(v)
                logger.info(
                    "  merged %d env vars from %s",
                    len(spawn_env), spawn_env_file.name,
                )
            else:
                logger.warning(
                    "  spawn_env file %s not a dict; ignoring",
                    spawn_env_file,
                )
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "  spawn_env file %s corrupt or unparseable (%s); "
                "watchdog respawn will use bare os.environ — Plan B "
                "settings may revert to defaults",
                spawn_env_file, exc,
            )
    else:
        logger.warning(
            "  spawn_env file %s missing; watchdog respawn will use bare "
            "os.environ — Plan B env vars may revert to defaults",
            spawn_env_file,
        )

    logger.info("spawn: variant=%s log=%s", variant, log_path)
    try:
        with open(log_path, "w") as logfile:
            proc = subprocess.Popen(
                cmd, stdout=logfile, stderr=subprocess.STDOUT,
                start_new_session=True, env=env,
            )
        time.sleep(3)
        if proc.poll() is not None:
            logger.error("  spawned process exited immediately rc=%d",
                         proc.returncode)
            return None
        logger.info("  ✓ spawned pid=%d", proc.pid)
        return proc.pid
    except Exception as exc:
        logger.error("  spawn failed: %s", exc)
        return None


def _check_suite(
    suite_dir: Path, *, stale_secs: float, confirm_secs: float, dry_run: bool,
) -> int:
    """Return 0 (no action) / 1 (action attempted, failed) / 0 (success)."""
    wals = list(suite_dir.glob("variant_*/seed_*.wal.jsonl"))
    now = time.time()
    stuck: list[tuple[Path, float]] = []
    for w in wals:
        # Skip baselines/gd that already finished (variant_X/seed_X.json exists)
        variant_dir = w.parent
        seed = int(w.name.split("_")[1].split(".")[0])
        finished = (variant_dir / f"seed_{seed}.json").exists()
        if finished:
            continue
        age = now - w.stat().st_mtime
        if age > stale_secs:
            stuck.append((w, age))
            logger.info("STALE candidate: %s age=%.0fs", w, age)

    if not stuck:
        return 0

    # Confirm: wait confirm_secs and re-check
    logger.info(
        "Waiting %.0fs to confirm hang (transient slowdowns shouldn't last)...",
        confirm_secs,
    )
    time.sleep(confirm_secs)

    rc = 0
    for w, _initial_age in stuck:
        new_age = time.time() - w.stat().st_mtime
        if new_age < stale_secs:
            logger.info("RECOVERED on its own: %s now age=%.0fs", w, new_age)
            continue
        logger.warning("CONFIRMED HANG: %s age=%.0fs", w, new_age)

        # Resolve variant + seed + suite
        variant_dir = w.parent
        variant = variant_dir.name.replace("variant_", "")
        seed = int(w.name.split("_")[1].split(".")[0])

        # Find PID
        pid = _find_pid_holding(w)
        if pid is None:
            logger.error("  cannot find PID for %s", w)
            rc = 1
            continue

        # Check snapshot exists
        snap = _latest_snapshot(variant_dir, seed)
        if snap is None:
            logger.error("  no snapshot for variant %s seed %d — refusing kill",
                         variant, seed)
            rc = 1
            continue
        logger.info("  latest snapshot: %s", snap.name)

        if dry_run:
            logger.info("  [dry-run] would SIGTERM pid=%d + relaunch", pid)
            continue

        # Kill
        if not _kill_worker(pid):
            rc = 1
            continue

        # Spawn
        new_pid = _spawn_replacement(
            suite_dir=suite_dir, variant=variant, seed=seed,
        )
        if new_pid is None:
            rc = 1

    return rc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "suite_dirs", nargs="+", type=Path,
        help="Suite directories to watch (data/experiments/<run>/)",
    )
    parser.add_argument("--stale-secs", type=float, default=420.0)
    parser.add_argument("--confirm-secs", type=float, default=60.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-file", type=Path,
                        default=Path("/tmp/watchdog_wal_deadlock.log"))
    args = parser.parse_args(argv)

    _setup_log(args.log_file)
    logger.info("=== watchdog tick === suites=%s stale=%.0fs confirm=%.0fs dry=%s",
                [s.name for s in args.suite_dirs],
                args.stale_secs, args.confirm_secs, args.dry_run)

    rc = 0
    for suite in args.suite_dirs:
        if not suite.exists():
            logger.error("suite not found: %s", suite)
            rc = max(rc, 2)
            continue
        suite_rc = _check_suite(
            suite,
            stale_secs=args.stale_secs,
            confirm_secs=args.confirm_secs,
            dry_run=args.dry_run,
        )
        rc = max(rc, suite_rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
