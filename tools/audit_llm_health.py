#!/usr/bin/env python3
"""audit_llm_health — scan worker logs for LLM fallback / circuit-breaker cascade.

D2 attempt 4 (2026-05-18) showed that workers can run for hours in
silent 100% fallback mode when the LLM provider's circuit breaker opens
(e.g., due to balance depletion / 402 / connection storm). The existing
audit_run_health.py catches process-level deadlocks but NOT this
category of failure — workers tick happily, commits succeed, encounters
log; only the LLM responses are templates.

This audit scans a run directory's worker_*.log + /tmp/d2_resume_*.log
files for:

- AllKeysOpenError / "all 8 keys open"  → circuit-breaker cascade
- "Insufficient Balance" / 402          → provider balance issue
- "using fallback"                      → per-call fallback rate proxy
- "LLM error" / "Connection error"      → transient errors

Rolling window: last `--window-secs` of log activity (default 300s = 5min).
A worker is "degraded" if its fallback rate exceeds `--max-fb-rate`
(default 20%) in the window, OR if 8-keys-open errors are present.

Exit codes:
    0 → all healthy
    1 → at least one worker degraded (fallback rate over threshold)
    2 → at least one worker has structural failure (all 8 keys open
        / Insufficient Balance) — restart needed

Usage:
    python tools/audit_llm_health.py data/experiments/<run>/
    python tools/audit_llm_health.py <run>/ /tmp/d2_resume_*.log
    python tools/audit_llm_health.py <run>/ --window-secs 60 --max-fb-rate 0.05
    python tools/audit_llm_health.py <run>/ --json
    python tools/audit_llm_health.py <run>/ --tail-lines 5000
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

# Pattern markers
_STRUCTURAL_PATTERNS = (
    "all 8 keys open",
    "AllKeysOpenError",
    "Insufficient Balance",
    "Error code: 402",
)
_FALLBACK_PATTERNS = (
    "— using fallback",
    "LLM failed",
    "LLM error",
    "reflect failed",
    "importance scoring failed",
)
# Lines that suggest healthy LLM work (used as denominator proxy when present)
_HEALTH_PATTERNS = (
    "reflect committed",
    "completed reflection",
    "[aitown] wired",
)


def _scan_log(
    path: Path,
    *,
    tail_lines: int,
    window_secs: float,
) -> dict:
    """Return summary dict for a single log file."""
    if not path.exists():
        return {"path": str(path), "exists": False}
    size = path.stat().st_size
    mtime = path.stat().st_mtime
    age_sec = time.time() - mtime
    try:
        with open(path, "rb") as fh:
            # Read last N KB; cheap approach: seek to end - 256KB.
            chunk = 256 * 1024
            if size > chunk:
                fh.seek(-chunk, os.SEEK_END)
                fh.readline()  # discard first partial line
            raw = fh.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return {"path": str(path), "exists": True, "error": f"read: {exc}"}
    lines = raw.splitlines()
    if tail_lines and len(lines) > tail_lines:
        lines = lines[-tail_lines:]
    n_struct = sum(
        1
        for ln in lines
        if any(p in ln for p in _STRUCTURAL_PATTERNS)
    )
    n_fb = sum(
        1
        for ln in lines
        if any(p in ln for p in _FALLBACK_PATTERNS)
    )
    n_health = sum(
        1
        for ln in lines
        if any(p in ln for p in _HEALTH_PATTERNS)
    )
    # Fallback rate proxy: fb / (fb + perceived healthy work)
    # When healthy lines aren't present, fall back to fb / total lines.
    if n_health:
        fb_rate = n_fb / (n_fb + n_health)
    elif lines:
        fb_rate = n_fb / max(len(lines), 1)
    else:
        fb_rate = 0.0
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": size,
        "log_age_sec": age_sec,
        "lines_scanned": len(lines),
        "structural_errors": n_struct,
        "fallback_lines": n_fb,
        "health_lines": n_health,
        "fb_rate": fb_rate,
    }


def _classify(rec: dict, *, max_fb_rate: float) -> str:
    """healthy | degraded | structural"""
    if not rec.get("exists"):
        return "missing"
    if rec.get("error"):
        return "unknown"
    if rec.get("structural_errors", 0) > 0:
        return "structural"
    if rec.get("fb_rate", 0.0) > max_fb_rate:
        return "degraded"
    return "healthy"


def _discover_logs(args: argparse.Namespace) -> list[Path]:
    """Collect log files from positional args.

    Each positional arg can be:
    - a directory: scan for worker_*.log inside (data/experiments/<run>/)
    - a glob pattern: expanded
    - a file path: used as-is
    """
    out: list[Path] = []
    for arg in args.targets:
        p = Path(arg)
        if p.is_dir():
            # scan for worker_*.log
            for f in sorted(p.glob("worker_*.log")):
                out.append(f)
            for f in sorted(p.glob("variant_*/seed_*.wal.jsonl")):
                # WAL files aren't text logs, skip
                pass
        elif "*" in arg or "?" in arg:
            for f in sorted(glob.glob(arg)):
                out.append(Path(f))
        else:
            out.append(p)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "targets",
        nargs="+",
        help="Log file paths, directories, or glob patterns to scan.",
    )
    parser.add_argument(
        "--window-secs",
        type=float,
        default=300.0,
        help=(
            "Reserved for future per-line timestamp parsing (currently "
            "approximated via --tail-lines). Default 300s."
        ),
    )
    parser.add_argument(
        "--tail-lines",
        type=int,
        default=2000,
        help="Scan only the last N lines per log (default 2000).",
    )
    parser.add_argument(
        "--max-fb-rate",
        type=float,
        default=0.20,
        help="Degraded threshold for fallback / (fallback + health) ratio.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of human-readable text.",
    )
    parser.add_argument(
        "--quiet-healthy",
        action="store_true",
        help="Suppress healthy entries (only show degraded / structural).",
    )
    args = parser.parse_args(argv)

    logs = _discover_logs(args)
    if not logs:
        print("[audit_llm_health] no logs discovered", file=sys.stderr)
        return 1

    records: list[dict] = []
    for log in logs:
        rec = _scan_log(
            log,
            tail_lines=args.tail_lines,
            window_secs=args.window_secs,
        )
        rec["status"] = _classify(rec, max_fb_rate=args.max_fb_rate)
        records.append(rec)

    # overall status
    statuses = {r["status"] for r in records}
    if "structural" in statuses:
        overall = "structural"
        exit_code = 2
    elif "degraded" in statuses:
        overall = "degraded"
        exit_code = 1
    elif "missing" in statuses or "unknown" in statuses:
        overall = "warning"
        exit_code = 1
    else:
        overall = "healthy"
        exit_code = 0

    if args.json:
        payload = {
            "overall": overall,
            "exit_code": exit_code,
            "max_fb_rate": args.max_fb_rate,
            "tail_lines": args.tail_lines,
            "records": records,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        badge = {
            "healthy": "✓",
            "degraded": "⚠",
            "structural": "💀",
            "warning": "?",
        }.get(overall, "?")
        print(f"{badge} OVERALL: {overall.upper()}  (max_fb_rate={args.max_fb_rate:.0%})")
        for r in records:
            if args.quiet_healthy and r["status"] == "healthy":
                continue
            marker = {
                "healthy": "·",
                "degraded": "!",
                "structural": "X",
                "missing": "?",
                "unknown": "?",
            }.get(r["status"], "?")
            short = r["path"]
            if len(short) > 60:
                short = "…" + short[-58:]
            if r.get("exists") and "error" not in r:
                print(
                    f"  {marker} [{r['status']:<10}] {short}"
                    f"  fb={r['fallback_lines']:<5} struct={r['structural_errors']:<3}"
                    f" health={r['health_lines']:<4} rate={r['fb_rate']:.0%}"
                    f" age={r['log_age_sec']:.0f}s"
                )
            else:
                err = r.get("error", "missing")
                print(f"  {marker} [{r['status']:<10}] {short}  ({err})")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
