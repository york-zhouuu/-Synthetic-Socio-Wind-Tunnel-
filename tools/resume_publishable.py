#!/usr/bin/env python3
"""resume_publishable — set-and-forget guardian for in-progress publishable runs.

2026-05-19: the publishable seed42 + seed43 run lost ~12h of compute when
macOS auto-installed an update and rebooted at 06:09. All worker terminals
went with it. Existing `watchdog_wal_deadlock.py` couldn't recover because
it bails when `lsof` can't find a PID — exactly the case after a host
reboot. This script handles the post-reboot path.

Related CLAUDE.md invariants (read before modifying this file):
- `monitor-as-control-plane`: this script SHALL NOT terminate workers; only
  observe + report + spawn-on-missing. SIGUSR1 / SIGTERM / SIGKILL belong to
  human via monitor.
- `sigusr1-graceful-stop-corruption`: do NOT SIGUSR1 a worker that is still
  in resume/setup (no day partial yet); the handler writes a fake
  `seed_N.json` with total_ticks=0 + runs `cleanup_partials`.
- `snapshot-resume-ram-peak` + `spawn-burst-self-DDoS`: spawning N workers
  simultaneously from mid-run snapshots triggers TWO failure modes:
  (1) RAM peak ~50–100 GB on 48 GB Mac (snapshot deserialize 5-10× bloat),
  (2) LLM API burst self-DDoS (4 worker × 500 protag agents × 1 LLM/tick
  = ~2000 concurrent HTTP POST → DeepSeek server-side TCP drop). Both
  fixed by **stagger guard enforced in code** (stagger-worker-spawn change,
  2026-05-19). Default 5-min spacing; env `RESILIENCE_MIN_SPAWN_SPACING_SECS`
  (0 = disable for ad-hoc tests). Multiple INTERRUPTED cells in one
  LaunchAgent fire process 1 per cycle; remaining cells get
  `action="deferred_due_to_stagger"` in the JSON report.

Invoked single-shot by `~/Library/LaunchAgents/com.user.swt-resume-watchdog.plist`
every 5 minutes. Detects every (seed, variant) cell's state and acts:

    DONE              variant_<v>/seed_<N>.json exists → skip
    INTERRUPTED       snapshot exists, no live worker → spawn resume worker
    NEVER_STARTED     no snapshot, no live worker → skip (conservative; we
                      never auto-start a fresh cell — only resume what was
                      already underway)
    RUNNING_FRESH     live worker + WAL mtime < stale_secs → leave alone
    RUNNING_STALE     live worker + WAL mtime > stale_secs → SIGUSR1 to
                      graceful-stop; next tick will spawn replacement once
                      the worker has exited cleanly

Usage:
    python tools/resume_publishable.py \
        --suite data/experiments/20260518_..._seed42_...=42 \
        --suite data/experiments/20260518_..._seed43_...=43 \
        --variants hyperlocal_push,phone_friction \
        [--dry-run] [--stale-secs 420]

Exit codes:
    0 — all targeted cells DONE
    1 — at least one cell still incomplete (re-run later)
    2 — invalid arguments / unrecoverable error
"""

from __future__ import annotations

import argparse
import enum
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON = REPO_ROOT / ".venv" / "bin" / "python3"
DEFAULT_LOG = Path.home() / "Library" / "Logs" / "swt-resume-watchdog.log"
DEFAULT_SPAWN_TIMESTAMP_FILE = (
    Path.home() / "Library" / "Logs" / "swt-resume-watchdog-last-spawn.json"
)
DEFAULT_MIN_SPAWN_SPACING_SECS = 300  # 5 min, matches snapshot-resume-ram-peak

logger = logging.getLogger("resume_publishable")


# ---------------------------------------------------------------------------
# stagger-worker-spawn (2026-05-19): cross-spawn timing coordination.
#
# Root cause (D2 attempt 6, 2026-05-19 12:08:22 via 23:00+ log forensics):
# 4 workers spawned within 2 seconds → 4 × 500 protag agents × 1 LLM/tick
# = ~2000 concurrent HTTP POST to api.deepseek.com → server-side burst
# protection (silent TCP drop) → openai.APIConnectionError → 8 keys
# cooldown → FallbackBudgetExceeded → 4-way suicide → LaunchAgent
# respawns → loop.
#
# Fix: persistent last-spawn timestamp in JSON file; each spawn check
# enforces `min_spacing_secs` floor. Multi-cell loop processes 1 cell
# per LaunchAgent fire (5-min cycle), staggering naturally across cycles.
# ---------------------------------------------------------------------------


def _spawn_timestamp_path() -> Path:
    """Resolve the timestamp file path (env override > default)."""
    env = os.environ.get("SPAWN_STAGGER_TIMESTAMP_FILE")
    if env:
        return Path(env)
    return DEFAULT_SPAWN_TIMESTAMP_FILE


def _read_last_spawn_timestamp() -> dict | None:
    """Read last spawn timestamp from disk.

    Returns None if file doesn't exist (first run). On corruption /
    missing fields / unparseable JSON: log warning and return None
    (conservative: prefer allowing spawn over locking up).
    """
    path = _spawn_timestamp_path()
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "spawn timestamp file %s is corrupt or unreadable: %s — "
            "treating as no previous spawn",
            path, exc,
        )
        return None
    # Required fields
    if not isinstance(data, dict) or "last_spawn_epoch" not in data:
        logger.warning(
            "spawn timestamp file %s missing required field "
            "'last_spawn_epoch' — treating as no previous spawn",
            path,
        )
        return None
    return data


def _write_last_spawn_timestamp(cell: dict) -> None:
    """Atomically write last-spawn timestamp. Failures log + continue.

    Uses tempfile.NamedTemporaryFile in the same directory then
    os.rename for POSIX atomic move. Caller SHOULD NOT propagate
    failures — spawning the worker is more important than recording
    the timestamp.
    """
    path = _spawn_timestamp_path()
    now_epoch = time.time()
    payload = {
        "last_spawn_epoch": now_epoch,
        "last_spawn_iso": datetime.now(timezone.utc).isoformat(
            timespec="seconds",
        ),
        "last_spawn_cell": cell,
        "version": 1,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # tempfile in same directory to ensure os.rename is atomic
        # (cross-device rename would be non-atomic).
        with tempfile.NamedTemporaryFile(
            mode="w", dir=str(path.parent), delete=False,
            prefix=".swt-spawn-ts-", suffix=".tmp", encoding="utf-8",
        ) as tf:
            json.dump(payload, tf)
            tf.flush()
            os.fsync(tf.fileno())
            tmp_name = tf.name
        os.rename(tmp_name, path)
    except OSError as exc:
        logger.warning(
            "failed to write spawn timestamp %s: %s — spawn proceeds, "
            "but spacing guard may misfire on next call",
            path, exc,
        )


def _spawn_allowed_now(min_spacing_secs: int) -> tuple[bool, float, str]:
    """Check if a spawn is allowed right now under spacing rule.

    Returns (allowed, wait_secs_until_next_eligible, reason).
    - (True, 0.0, reason) when spawn is allowed
    - (False, secs > 0, reason) when caller SHOULD defer to next cycle

    `min_spacing_secs == 0` SHALL bypass the guard entirely.
    """
    if min_spacing_secs <= 0:
        return (True, 0.0, "stagger_disabled (min_spacing_secs<=0)")

    data = _read_last_spawn_timestamp()
    if data is None:
        # Distinguish "file truly absent" (first run) vs "file exists but
        # unreadable" (corrupt). Tests + ops monitoring use this reason
        # to triage why guard didn't fire.
        if _spawn_timestamp_path().exists():
            return (True, 0.0,
                    "allowed_after_corrupt_or_invalid_timestamp_file")
        return (True, 0.0, "no_previous_spawn (first spawn or stale state)")

    last_epoch = data.get("last_spawn_epoch", 0.0)
    now = time.time()
    elapsed = now - last_epoch

    if elapsed < 0:
        # Clock went backward (NTP / manual change). Conservative: reset.
        logger.warning(
            "system clock went backward (last_spawn_epoch=%.2f > now=%.2f) "
            "— resetting spacing timer, allowing spawn",
            last_epoch, now,
        )
        return (True, 0.0, "clock_backward_reset")

    if elapsed >= min_spacing_secs:
        return (True, 0.0,
                f"spacing_met (elapsed={elapsed:.0f}s >= "
                f"min={min_spacing_secs}s)")

    wait = min_spacing_secs - elapsed
    return (False, wait,
            f"deferred_due_to_stagger (need {wait:.0f}s more; "
            f"min_spacing={min_spacing_secs}s)")


class CellState(str, enum.Enum):
    DONE = "DONE"
    INTERRUPTED = "INTERRUPTED"
    NEVER_STARTED = "NEVER_STARTED"
    RUNNING_FRESH = "RUNNING_FRESH"
    RUNNING_STALE = "RUNNING_STALE"


def _setup_log(log_path: Path, verbose: bool) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_path)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
    ))
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter(
        "[resume] %(asctime)s %(message)s", datefmt="%H:%M:%S",
    ))
    logger.addHandler(fh)
    logger.addHandler(sh)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)


def _find_alive_worker(seed: int, variant: str, suite_dir: Path) -> int | None:
    """Return PID of a running worker for this (seed, variant), or None.

    Uses ps + cmdline matching rather than lsof on the WAL file — survives
    cases where the worker hasn't opened the WAL yet (early startup) but is
    still alive.
    """
    try:
        out = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("ps failed: %s", exc)
        return None
    needle_seed = f"--seed-start {seed}"
    needle_variant_simple = f"--variants {variant}"
    needle_variant_csv = f"--variants {variant},"
    suite_basename = suite_dir.name
    for line in out.stdout.splitlines():
        if "run_variant_suite.py" not in line:
            continue
        if suite_basename not in line:
            continue
        if needle_seed not in line:
            continue
        # variant arg may be alone or first in csv
        if needle_variant_simple not in line and needle_variant_csv not in line:
            continue
        parts = line.strip().split(None, 1)
        if not parts:
            continue
        try:
            return int(parts[0])
        except ValueError:
            continue
    return None


def _wal_age_seconds(variant_dir: Path, seed: int) -> float | None:
    wal = variant_dir / f"seed_{seed}.wal.jsonl"
    if not wal.exists():
        return None
    return time.time() - wal.stat().st_mtime


def _wal_mtime(variant_dir: Path, seed: int) -> float | None:
    wal = variant_dir / f"seed_{seed}.wal.jsonl"
    if not wal.exists():
        return None
    return wal.stat().st_mtime


def _process_start_epoch(pid: int) -> float | None:
    """UNIX epoch when this PID started; None on failure.

    macOS `ps -o lstart=` returns e.g. "Tue May 19 11:54:02 2026".
    """
    try:
        out = subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "lstart="],
            text=True, timeout=5,
        ).strip()
    except (subprocess.SubprocessError, OSError):
        return None
    if not out:
        return None
    try:
        return datetime.strptime(out, "%a %b %d %H:%M:%S %Y").timestamp()
    except ValueError:
        return None


def _latest_snapshot(variant_dir: Path, seed: int) -> Path | None:
    candidates = sorted(
        variant_dir.glob(f"seed_{seed}_tick*.snapshot.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _latest_partial_day(variant_dir: Path, seed: int) -> int | None:
    candidates = list(variant_dir.glob(f"seed_{seed}_day*.partial.json"))
    if not candidates:
        return None
    days: list[int] = []
    for p in candidates:
        try:
            d = int(p.stem.split("_day")[-1].split(".")[0])
            days.append(d)
        except (ValueError, IndexError):
            continue
    return max(days) if days else None


def _cell_state(
    suite_dir: Path, seed: int, variant: str, stale_secs: float,
) -> tuple[CellState, dict]:
    variant_dir = suite_dir / f"variant_{variant}"
    info: dict = {}
    if not variant_dir.exists():
        return CellState.NEVER_STARTED, info

    final = variant_dir / f"seed_{seed}.json"
    if final.exists():
        info["final_mtime"] = datetime.fromtimestamp(
            final.stat().st_mtime,
        ).isoformat(timespec="seconds")
        return CellState.DONE, info

    pid = _find_alive_worker(seed, variant, suite_dir)
    wal_age = _wal_age_seconds(variant_dir, seed)
    wal_mt = _wal_mtime(variant_dir, seed)
    snap = _latest_snapshot(variant_dir, seed)
    last_day = _latest_partial_day(variant_dir, seed)
    proc_start = _process_start_epoch(pid) if pid is not None else None
    in_setup = (
        pid is not None and wal_mt is not None and proc_start is not None
        and wal_mt < proc_start
    )

    # harden-worker-resilience: setup-phase abort sentinel left by
    # MultiDayRunner when SIGUSR1 fired before any day completed.
    # If present + no live worker, that's a special INTERRUPTED variant
    # that DID NOT write any partial — but did write a snapshot.
    sentinel = variant_dir / f"seed_{seed}.aborted_in_setup.json"
    aborted_in_setup_marker = sentinel.exists()

    info.update({
        "pid": pid,
        "wal_age_seconds": int(wal_age) if wal_age is not None else None,
        "latest_snapshot": snap.name if snap else None,
        "last_partial_day": last_day,
        "proc_start_epoch": proc_start,
        "in_setup": in_setup,
        "aborted_in_setup": aborted_in_setup_marker,
    })

    if pid is not None:
        if in_setup:
            # WAL predates this worker — still in resume/setup phase,
            # hasn't written its first tick yet. Treat as fresh; monitor
            # gets `in_setup=True` in the report to disambiguate.
            return CellState.RUNNING_FRESH, info
        if wal_age is None or wal_age < stale_secs:
            return CellState.RUNNING_FRESH, info
        return CellState.RUNNING_STALE, info

    # No live PID
    if snap is not None or last_day is not None or aborted_in_setup_marker:
        return CellState.INTERRUPTED, info
    return CellState.NEVER_STARTED, info


def _spawn_resume_worker(
    suite_dir: Path, seed: int, variant: str, *,
    snapshot_every_ticks: int, dry_run: bool,
) -> int | None:
    """Launch a detached `run_variant_suite.py --resume` for this cell.

    Appends to the existing `worker_<variant>.log` (continuity with prior
    pre-reboot log lines).
    """
    cmd = [
        str(PYTHON), "tools/run_variant_suite.py",
        "--variants", variant,
        "--seeds", "1",
        "--seed-start", str(seed),
        "--num-days", "14",
        "--agents", "1000",
        "--num-protagonists", "500",
        "--mode", "publishable",
        "--use-aitown",
        "--aitown-provider", "deepseek",
        "--workers", "1",
        "--suite-dir", str(suite_dir),
        "--resume",
        "--resume-strategy", "auto",
    ]
    env = os.environ.copy()
    env["RESILIENCE_TRUST_LAST_PREFLIGHT"] = "1"
    env["RESILIENCE_SNAPSHOT_EVERY_TICKS"] = str(snapshot_every_ticks)
    env["RESILIENCE_WAL_ENABLED"] = "true"
    log_path = suite_dir / f"worker_{variant}.log"

    if dry_run:
        logger.info("  [dry-run] would spawn: %s", " ".join(cmd))
        logger.info("  [dry-run] log → %s  env override: %s",
                    log_path,
                    {k: env[k] for k in (
                        "RESILIENCE_SNAPSHOT_EVERY_TICKS",
                        "RESILIENCE_TRUST_LAST_PREFLIGHT",
                    )})
        return None

    # harden-worker-resilience: clear the setup-phase abort sentinel
    # before spawning a fresh resume worker — it served its purpose
    # (telling us this cell was interrupted in setup, not "DONE").
    variant_dir = suite_dir / f"variant_{variant}"
    sentinel = variant_dir / f"seed_{seed}.aborted_in_setup.json"
    if sentinel.exists():
        try:
            sentinel.unlink()
            logger.info("  cleared setup-abort sentinel %s", sentinel.name)
        except OSError as exc:
            logger.warning("  failed to unlink sentinel %s: %s", sentinel, exc)

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as logfile:
            stamp = datetime.now().isoformat(timespec="seconds")
            logfile.write(
                f"\n=== resume_publishable spawn @ {stamp} "
                f"(seed={seed} variant={variant}) ===\n",
            )
            logfile.flush()
            proc = subprocess.Popen(
                cmd,
                stdout=logfile, stderr=subprocess.STDOUT,
                start_new_session=True,
                env=env,
                cwd=str(REPO_ROOT),
            )
        # Give it a beat to crash on import / arg parsing
        time.sleep(2)
        if proc.poll() is not None:
            logger.error("  spawned process exited immediately rc=%d "
                         "(check %s)", proc.returncode, log_path)
            return None
        logger.info("  ✓ spawned pid=%d (seed=%d variant=%s)",
                    proc.pid, seed, variant)
        return proc.pid
    except (OSError, ValueError) as exc:
        logger.error("  spawn failed: %s", exc)
        return None


def _parse_suite(arg: str) -> tuple[Path, int]:
    if "=" not in arg:
        raise argparse.ArgumentTypeError(
            f"--suite must be `<path>=<seed>`, got: {arg}",
        )
    raw_path, raw_seed = arg.rsplit("=", 1)
    return Path(raw_path), int(raw_seed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--suite", action="append", type=_parse_suite, required=True,
        metavar="PATH=SEED",
        help="Repeatable: suite_dir + the single seed it owns "
             "(publishable runs are 1 seed per suite_dir). "
             "Example: --suite data/experiments/.../seed42_dir=42",
    )
    parser.add_argument(
        "--variants", default="hyperlocal_push,phone_friction",
        help="Comma-separated variants to watch (default: the two that "
             "typically run long enough to get caught by reboots). "
             "DONE cells are skipped regardless of this filter.",
    )
    parser.add_argument(
        "--stale-secs", type=float, default=420.0,
        help="WAL mtime older than this → RUNNING_STALE (default 420s)",
    )
    parser.add_argument(
        "--snapshot-every-ticks", type=int, default=12,
        help="Set RESILIENCE_SNAPSHOT_EVERY_TICKS for spawned workers "
             "(default 12 = hourly; lower than the legacy 24 because the "
             "post-reboot loss budget is now ~1h instead of ~2h)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--log-file", type=Path, default=DEFAULT_LOG,
        help=f"Log file path (default: {DEFAULT_LOG})",
    )
    parser.add_argument("--json", action="store_true",
                        help="Emit JSON report to stdout in addition to logs")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--min-spawn-spacing-secs", type=int, default=None,
        help=f"Minimum seconds between worker spawns (default "
             f"{DEFAULT_MIN_SPAWN_SPACING_SECS}; env "
             f"RESILIENCE_MIN_SPAWN_SPACING_SECS; 0=disable). Prevents "
             f"4-worker self-DDoS (2026-05-19 D2 attempt 6).",
    )
    args = parser.parse_args(argv)

    # Resolve effective spacing: CLI arg > env > default
    if args.min_spawn_spacing_secs is not None:
        effective_spacing = args.min_spawn_spacing_secs
    else:
        try:
            effective_spacing = int(os.environ.get(
                "RESILIENCE_MIN_SPAWN_SPACING_SECS",
                str(DEFAULT_MIN_SPAWN_SPACING_SECS),
            ))
        except ValueError:
            effective_spacing = DEFAULT_MIN_SPAWN_SPACING_SECS

    _setup_log(args.log_file, args.verbose)
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    logger.info(
        "=== resume tick === suites=%d variants=%s stale=%.0fs dry=%s",
        len(args.suite), variants, args.stale_secs, args.dry_run,
    )

    report: list[dict] = []
    incomplete = 0
    for suite_dir, seed in args.suite:
        if not suite_dir.exists():
            logger.error("suite not found: %s", suite_dir)
            continue
        for variant in variants:
            state, info = _cell_state(
                suite_dir, seed, variant, args.stale_secs,
            )
            entry = {
                "suite": suite_dir.name,
                "seed": seed,
                "variant": variant,
                "state": state.value,
                **info,
            }
            report.append(entry)
            logger.info(
                "  [%s] seed=%d variant=%s pid=%s wal_age=%s last_day=%s",
                state.value, seed, variant,
                info.get("pid"),
                info.get("wal_age_seconds"),
                info.get("last_partial_day"),
            )
            if state == CellState.DONE:
                continue
            incomplete += 1
            if state == CellState.NEVER_STARTED:
                logger.info(
                    "    NEVER_STARTED — skipping (no snapshot to resume from)",
                )
            elif state == CellState.INTERRUPTED:
                # stagger-worker-spawn (2026-05-19): check spacing guard
                # before spawning. Multiple INTERRUPTED cells in one
                # LaunchAgent fire SHALL serialize across LaunchAgent
                # cycles (5-min default), not burst-spawn simultaneously.
                allowed, wait_secs, reason = _spawn_allowed_now(
                    effective_spacing,
                )
                if not allowed:
                    next_eligible_iso = datetime.now(
                        timezone.utc,
                    ).fromtimestamp(
                        time.time() + wait_secs, tz=timezone.utc,
                    ).isoformat(timespec="seconds")
                    logger.info(
                        "    deferred_due_to_stagger seed=%d variant=%s "
                        "wait=%.0fs next_eligible_at=%s reason=%s",
                        seed, variant, wait_secs, next_eligible_iso, reason,
                    )
                    entry["action"] = "deferred_due_to_stagger"
                    entry["next_eligible_iso"] = next_eligible_iso
                    entry["spawn_wait_secs"] = round(wait_secs, 1)
                else:
                    new_pid = _spawn_resume_worker(
                        suite_dir, seed, variant,
                        snapshot_every_ticks=args.snapshot_every_ticks,
                        dry_run=args.dry_run,
                    )
                    # Record timestamp ONLY when actual spawn happens
                    # (dry_run also "logs" the spawn intent — record so
                    # the test's dry-run sequence behaves like real one).
                    _write_last_spawn_timestamp(
                        {"seed": seed, "variant": variant},
                    )
                    entry["action"] = "spawn_resume"
                    entry["new_pid"] = new_pid
                    entry["spawn_allowed_reason"] = reason
            elif state == CellState.RUNNING_STALE:
                # Per `monitor-as-control-plane` invariant (CLAUDE.md
                # 2026-05-19): this script does NOT terminate processes.
                # We report STALE; monitor / human decide whether to act.
                logger.warning(
                    "    RUNNING_STALE reported — NO auto-action "
                    "(termination decisions belong to monitor/human; "
                    "see CLAUDE.md monitor-as-control-plane)",
                )
                entry["action"] = "report_only"
            elif state == CellState.RUNNING_FRESH:
                logger.debug(
                    "    healthy%s — no action",
                    " (in_setup)" if info.get("in_setup") else "",
                )

    if args.json:
        print(json.dumps({
            "audited_at": datetime.now().isoformat(timespec="seconds"),
            "incomplete_cells": incomplete,
            "cells": report,
        }, indent=2))

    logger.info("=== tick done; incomplete_cells=%d ===", incomplete)
    return 0 if incomplete == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
