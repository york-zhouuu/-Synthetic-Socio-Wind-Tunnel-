#!/usr/bin/env python3
"""tail_memstat — live tail of comprehensive-runtime-instrumentation memstat.jsonl.

Spec: openspec/specs/runtime-instrumentation/spec.md

Reads `seed_<N>.memstat.jsonl` + `seed_<N>.events.jsonl` (+ optional
`seed_<N>.llm.jsonl`) from a worker's output dir; prints rolling stats
on stdout. Refreshes every N seconds.

Designed for `tail -F`-style observation during a publishable run.
Simple `print` (no rich/textual dependency).

Usage:
    python tools/tail_memstat.py <suite_dir> <variant> <seed> [--every 30]

Example:
    python tools/tail_memstat.py \\
        data/experiments/20260518_..._seed42_... phone_friction 42 \\
        --every 30
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


def _tail_jsonl(path: Path, max_lines: int = 1000) -> list[dict]:
    """Read last N lines of JSONL file (best-effort; OK if file truncated)."""
    if not path.is_file():
        return []
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            # Read up to last 1MB
            chunk_size = min(size, 1024 * 1024)
            f.seek(size - chunk_size)
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = [l for l in text.splitlines() if l.strip()]
    out: list[dict] = []
    for l in lines[-max_lines:]:
        try:
            out.append(json.loads(l))
        except json.JSONDecodeError:
            continue
    return out


def _format_summary(
    memstat: list[dict], events: list[dict], llm: list[dict],
) -> str:
    lines = []
    lines.append(f"=== {time.strftime('%H:%M:%S')} ===")

    # Memstat rolling stats
    if memstat:
        last = memstat[-1]
        rss = last.get("memory", {}).get("rss_mb")
        rss_peak = last.get("memory", {}).get("rss_peak_mb")
        vms = last.get("memory", {}).get("vms_mb")
        cpu = last.get("cpu", {}).get("percent_recent")
        threads = last.get("memory", {}).get("threads")
        tick = last.get("tick_global")
        day = last.get("day_index")
        events_total = last.get("memory_store", {}).get("total_events", 0)
        lines.append(
            f"  tick={tick}  day={day}  RSS={rss}MB (peak={rss_peak}MB) "
            f"VMS={vms}MB  CPU={cpu:.0f}%  threads={threads}",
        )
        lines.append(
            f"  memory_store: agents={last.get('memory_store',{}).get('agents')} "
            f"total_events={events_total}",
        )
        # RSS trend last 5 samples
        recent = memstat[-5:]
        rss_trend = " → ".join(
            str(s.get("memory", {}).get("rss_mb", "?")) for s in recent
        )
        lines.append(f"  RSS trend: {rss_trend}")
    else:
        lines.append("  no memstat samples yet")

    # Recent events
    if events:
        lines.append(f"  events: {len(events)} total")
        # Phase summary
        phases = [e for e in events if e.get("kind") == "PHASE"]
        if phases:
            last_phase = phases[-1]
            lines.append(
                f"  last phase: {last_phase.get('phase')} "
                f"({last_phase.get('ts_iso','')[:19]})",
            )
        # Counts of each kind
        kinds: dict[str, int] = {}
        for e in events:
            k = e.get("kind", "?")
            kinds[k] = kinds.get(k, 0) + 1
        lines.append(
            f"  event kinds: " + ", ".join(
                f"{k}={v}" for k, v in sorted(kinds.items())
            ),
        )

    # LLM stats
    if llm:
        success = sum(1 for r in llm if r.get("status") == "success")
        fallback = sum(1 for r in llm if r.get("status") == "fallback")
        exhausted = sum(1 for r in llm if r.get("status") == "exhausted")
        rates_s = [r.get("latency_ms", 0) for r in llm[-100:]
                   if r.get("status") == "success"]
        median_lat = (sorted(rates_s)[len(rates_s) // 2] if rates_s
                      else "?")
        lines.append(
            f"  LLM: success={success} fallback={fallback} "
            f"exhausted={exhausted}  recent-p50-latency-ms={median_lat}",
        )

    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("suite_dir", type=Path)
    p.add_argument("variant", type=str)
    p.add_argument("seed", type=int)
    p.add_argument("--every", type=int, default=30,
                   help="Refresh interval seconds (default 30)")
    p.add_argument("--once", action="store_true",
                   help="Print once and exit")
    args = p.parse_args()

    vdir = args.suite_dir / f"variant_{args.variant}"
    if not vdir.is_dir():
        print(f"ERROR: {vdir} not a directory", file=sys.stderr)
        return 2

    memstat_path = vdir / f"seed_{args.seed}.memstat.jsonl"
    events_path = vdir / f"seed_{args.seed}.events.jsonl"
    llm_path = vdir / f"seed_{args.seed}.llm.jsonl"

    print(f"watching {memstat_path}", file=sys.stderr)

    while True:
        memstat = _tail_jsonl(memstat_path, max_lines=100)
        events = _tail_jsonl(events_path, max_lines=200)
        llm = _tail_jsonl(llm_path, max_lines=500)
        print(_format_summary(memstat, events, llm))
        print()  # blank line separator
        if args.once:
            break
        try:
            time.sleep(args.every)
        except KeyboardInterrupt:
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
