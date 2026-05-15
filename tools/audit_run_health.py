#!/usr/bin/env python3
"""audit_run_health — single-shot health check on an in-progress publishable run.

D1' (2026-05-15) showed that 3/4 Gemini workers silently deadlocked for 7+
hours before anyone noticed. This CLI scans a run directory's worker pids
and reports on:

- process state (`U` / `D` = uninterruptible sleep = death by deadlock)
- log silence (no new line for > 30 min = warning, > 60 min = deadlock)
- CLOSE_WAIT TCP socket accumulation (> 60% of `ulimit -n` = warning,
  > 90% = deadlock)

Exit codes:
    0 → all workers healthy
    1 → at least one warning, no suspected deadlock
    2 → at least one worker is in suspected_deadlock state

Usage:
    python tools/audit_run_health.py data/experiments/20260514_d1_gemini_1seed/
    python tools/audit_run_health.py <run_dir> --json
    python tools/audit_run_health.py <run_dir> --watch 60   # loop every 60s
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from synthetic_socio_wind_tunnel.run_resilience import (
    HealthAudit,
    HealthAuditReport,
)


_STATUS_TO_EXIT = {
    "healthy": 0,
    "warning": 1,
    "suspected_deadlock": 2,
}


def _format_human(report: HealthAuditReport) -> str:
    lines: list[str] = []
    overall = report.overall_status.upper()
    badge = {
        "HEALTHY": "✓",
        "WARNING": "⚠",
        "SUSPECTED_DEADLOCK": "💀",
    }.get(overall, "?")
    lines.append(f"{badge} OVERALL: {overall}  ({report.run_dir})")
    lines.append(f"  audited_at: {report.audited_at.isoformat()}")
    if not report.workers:
        lines.append("  (no workers discovered)")
    for w in report.workers:
        marker = {
            "healthy": "·",
            "warning": "!",
            "suspected_deadlock": "X",
        }[w.status]
        log_name = w.log_path.name if w.log_path else "<no log>"
        silent = (
            f"{w.last_log_mtime_seconds_ago / 60:.1f}min"
            if w.last_log_mtime_seconds_ago is not None
            else "n/a"
        )
        cw = w.close_wait_count if w.close_wait_count is not None else "n/a"
        rss_mb = (
            f"{w.rss_bytes / 1024 / 1024:.0f}MB"
            if w.rss_bytes is not None
            else "n/a"
        )
        reasons = ",".join(w.reasons) if w.reasons else "-"
        lines.append(
            f"  [{marker}] pid={w.pid} state={w.process_state or 'n/a'} "
            f"log={log_name} silent={silent} close_wait={cw} rss={rss_mb} "
            f"reasons={reasons} → {w.status.upper()}",
        )
    for note in report.notes:
        lines.append(f"  note: {note}")
    if report.overall_status == "suspected_deadlock":
        lines.append("")
        lines.append("  SUSPECTED DEADLOCK detected.")
        lines.append("  Recommended action:")
        lines.append("    1. Send SIGUSR1 to graceful-stop + write checkpoint:")
        for w in report.workers:
            if w.status == "suspected_deadlock":
                lines.append(f"         kill -USR1 {w.pid}")
        lines.append("    2. If SIGUSR1 not acknowledged in 5 min, SIGKILL:")
        for w in report.workers:
            if w.status == "suspected_deadlock":
                lines.append(f"         kill -9 {w.pid}")
        lines.append("    3. Resume from last partial: run_variant_suite.py --resume")
    return "\n".join(lines)


def _format_json(report: HealthAuditReport) -> str:
    payload = {
        "run_dir": str(report.run_dir),
        "overall_status": report.overall_status,
        "audited_at": report.audited_at.isoformat(),
        "notes": list(report.notes),
        "workers": [
            {
                "pid": w.pid,
                "process_state": w.process_state,
                "log_path": str(w.log_path) if w.log_path else None,
                "last_log_mtime_seconds_ago": w.last_log_mtime_seconds_ago,
                "close_wait_count": w.close_wait_count,
                "rss_bytes": w.rss_bytes,
                "reasons": list(w.reasons),
                "status": w.status,
            }
            for w in report.workers
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="audit_run_health",
        description="Single-shot health check for an in-progress run.",
    )
    p.add_argument("run_dir", type=Path, help="Run directory (contains worker_*.log files)")
    p.add_argument("--json", action="store_true", help="Output JSON instead of human-readable")
    p.add_argument(
        "--watch", type=int, default=0, metavar="SECONDS",
        help="Loop forever, re-checking every N seconds (Ctrl-C to stop)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.run_dir.exists():
        print(f"error: run_dir {args.run_dir} does not exist", file=sys.stderr)
        return 2

    audit = HealthAudit()
    if args.watch > 0:
        try:
            while True:
                report = audit.audit(args.run_dir)
                if args.json:
                    print(_format_json(report))
                else:
                    print(_format_human(report))
                    print()  # blank line between iterations
                time.sleep(args.watch)
        except KeyboardInterrupt:
            return 0
    else:
        report = audit.audit(args.run_dir)
        if args.json:
            print(_format_json(report))
        else:
            print(_format_human(report))
        return _STATUS_TO_EXIT[report.overall_status]


if __name__ == "__main__":
    sys.exit(main())
