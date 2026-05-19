#!/usr/bin/env python3
"""analyze_memstat — offline post-mortem analyzer for a cell's instrumentation.

Spec: openspec/specs/runtime-instrumentation/spec.md

Reads `seed_<N>.memstat.jsonl` + `seed_<N>.events.jsonl` + `seed_<N>.llm.jsonl`
from a cell directory; emits Markdown report:

- Phase timeline (chronological PROCESS_START → ... → EXIT with durations)
- RSS curve (ASCII sparkline + peak / mean / final)
- Eviction effectiveness (total events freed + cumulative RSS deltas)
- LLM failure rate over time
- Handler timing breakdown (top-N by wall_sum)
- Health flags (peaked too high, fallback rate too high, etc.)

Usage:
    python tools/analyze_memstat.py <suite_dir> <variant> <seed>
    python tools/analyze_memstat.py <suite_dir> <variant> <seed> --json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _sparkline(values: list[float], width: int = 40) -> str:
    """ASCII sparkline from a list of numeric values."""
    if not values:
        return ""
    bars = "▁▂▃▄▅▆▇█"
    lo, hi = min(values), max(values)
    if hi == lo:
        return bars[0] * min(len(values), width)
    # Downsample to width
    step = max(1, len(values) // width)
    sampled = values[::step][:width]
    out = []
    for v in sampled:
        idx = int((v - lo) / (hi - lo) * (len(bars) - 1))
        idx = max(0, min(len(bars) - 1, idx))
        out.append(bars[idx])
    return "".join(out)


def _analyze(
    memstat: list[dict], events: list[dict], llm: list[dict],
) -> dict[str, Any]:
    report: dict[str, Any] = {}

    # Phase timeline
    phases = [
        e for e in events
        if e.get("kind") == "PHASE"
    ]
    timeline = []
    for i, p in enumerate(phases):
        entry: dict[str, Any] = {
            "phase": p.get("phase"),
            "ts_iso": p.get("ts_iso"),
            "rss_mb": p.get("rss_mb"),
        }
        if i + 1 < len(phases):
            try:
                t0 = datetime.fromisoformat(p["ts_iso"])
                t1 = datetime.fromisoformat(phases[i + 1]["ts_iso"])
                entry["duration_sec"] = round(
                    (t1 - t0).total_seconds(), 2,
                )
            except (KeyError, ValueError):
                pass
        timeline.append(entry)
    report["phase_timeline"] = timeline

    # RSS trajectory
    rss_series = [
        s.get("memory", {}).get("rss_mb")
        for s in memstat
        if isinstance(s.get("memory", {}).get("rss_mb"), (int, float))
    ]
    if rss_series:
        report["rss"] = {
            "samples": len(rss_series),
            "min_mb": min(rss_series),
            "max_mb": max(rss_series),
            "final_mb": rss_series[-1],
            "mean_mb": round(sum(rss_series) / len(rss_series), 1),
            "sparkline": _sparkline(rss_series, width=60),
        }
    else:
        report["rss"] = None

    # Eviction effectiveness
    evict_events = [e for e in events if e.get("kind") == "EVICT"]
    if evict_events:
        total_evicted = sum(
            e.get("events_evicted", 0) for e in evict_events
        )
        total_rss_delta = sum(
            (e.get("rss_before_mb", 0) - e.get("rss_after_mb", 0))
            for e in evict_events
        )
        report["eviction"] = {
            "events_fired": len(evict_events),
            "total_events_evicted": total_evicted,
            "total_rss_freed_mb_approx": total_rss_delta,
        }
    else:
        report["eviction"] = {"events_fired": 0}

    # LLM
    if llm:
        success = sum(1 for r in llm if r.get("status") == "success")
        fallback = sum(1 for r in llm if r.get("status") == "fallback")
        exhausted = sum(1 for r in llm if r.get("status") == "exhausted")
        latencies = sorted(
            r.get("latency_ms", 0) for r in llm
            if r.get("status") == "success"
        )
        n = len(latencies)
        report["llm"] = {
            "total_records": len(llm),
            "success": success, "fallback": fallback,
            "exhausted": exhausted,
            "fallback_rate": round(fallback / max(len(llm), 1), 3),
            "latency_p50_ms": latencies[n // 2] if n else None,
            "latency_p95_ms": (latencies[int(n * 0.95)]
                               if n > 20 else None),
        }
    else:
        report["llm"] = {"total_records": 0}

    # Retry events
    retry_events = [e for e in events if e.get("kind") == "RETRY"]
    if retry_events:
        by_exc: dict[str, int] = {}
        for r in retry_events:
            ec = r.get("exc_class", "?")
            by_exc[ec] = by_exc.get(ec, 0) + 1
        report["retries"] = {
            "total": len(retry_events),
            "by_exc_class": by_exc,
        }
    else:
        report["retries"] = {"total": 0}

    # Snapshot writes
    snap_events = [e for e in events if e.get("kind") == "SNAPSHOT_WRITE"]
    if snap_events:
        total_dur = sum(
            e.get("duration_sec", 0) for e in snap_events
        )
        max_size = max(e.get("size_bytes", 0) for e in snap_events)
        report["snapshots"] = {
            "writes": len(snap_events),
            "total_duration_sec": round(total_dur, 1),
            "max_size_mb": max_size // (1024 * 1024) if max_size else 0,
        }

    # Health flags
    flags = []
    if report["rss"] and report["rss"]["max_mb"] >= 9000:
        flags.append(
            f"⚠️ RSS approached cap (max {report['rss']['max_mb']}MB)",
        )
    if (report.get("llm", {}).get("fallback_rate", 0) > 0.10):
        flags.append(
            f"🚨 LLM fallback rate "
            f"{report['llm']['fallback_rate']:.1%} > 10%",
        )
    if any(p["phase"] == "EXIT" and p.get("reason") not in
           ("done", "normal", "graceful_stop")
           for p in timeline if isinstance(p, dict)):
        flags.append("⚠️ Abnormal exit reason recorded")
    report["health_flags"] = flags

    return report


def _render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(
        f"# Cell observability post-mortem — "
        f"generated {datetime.now().isoformat(timespec='seconds')}\n",
    )

    # Phase timeline
    lines.append("## Phase timeline\n")
    lines.append("| phase | ts (ISO) | RSS MB | duration sec |")
    lines.append("|---|---|--:|--:|")
    for p in report.get("phase_timeline", []):
        lines.append(
            f"| {p['phase']} | {p.get('ts_iso','')[:19]} | "
            f"{p.get('rss_mb','—')} | "
            f"{p.get('duration_sec','—')} |",
        )

    # RSS
    if report.get("rss"):
        rss = report["rss"]
        lines.append("\n## RSS trajectory\n")
        lines.append(
            f"- samples: {rss['samples']}",
        )
        lines.append(f"- min/mean/max/final: "
                     f"{rss['min_mb']} / {rss['mean_mb']} / "
                     f"{rss['max_mb']} / {rss['final_mb']} MB")
        lines.append(f"- sparkline: `{rss['sparkline']}`\n")

    # Eviction
    if report.get("eviction"):
        ev = report["eviction"]
        lines.append("## Eviction\n")
        lines.append(f"- fires: {ev['events_fired']}")
        if ev["events_fired"]:
            lines.append(
                f"- total events evicted: "
                f"{ev['total_events_evicted']:,}",
            )
            lines.append(
                f"- total RSS freed (approx): "
                f"{ev['total_rss_freed_mb_approx']} MB\n",
            )

    # LLM
    if report.get("llm") and report["llm"]["total_records"]:
        m = report["llm"]
        lines.append("## LLM\n")
        lines.append(f"- records: {m['total_records']}")
        lines.append(
            f"- success / fallback / exhausted: "
            f"{m['success']} / {m['fallback']} / {m['exhausted']}",
        )
        lines.append(f"- fallback rate: {m['fallback_rate']:.1%}")
        if m.get("latency_p50_ms") is not None:
            lines.append(
                f"- latency p50/p95 (ms): "
                f"{m['latency_p50_ms']} / "
                f"{m.get('latency_p95_ms','—')}\n",
            )

    # Retries
    if report.get("retries", {}).get("total"):
        lines.append("## Retries\n")
        r = report["retries"]
        lines.append(f"- total retry attempts: {r['total']}")
        for exc, count in sorted(
            r["by_exc_class"].items(), key=lambda kv: -kv[1],
        ):
            lines.append(f"  - {exc}: {count}")
        lines.append("")

    # Snapshots
    if report.get("snapshots"):
        s = report["snapshots"]
        lines.append("## Snapshot writes\n")
        lines.append(f"- count: {s['writes']}")
        lines.append(f"- total write time: {s['total_duration_sec']}s")
        lines.append(f"- max size: {s['max_size_mb']} MB\n")

    # Health flags
    flags = report.get("health_flags", [])
    lines.append("## Health flags\n")
    if flags:
        for f in flags:
            lines.append(f"- {f}")
    else:
        lines.append("(no flags)")
    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("suite_dir", type=Path)
    p.add_argument("variant", type=str)
    p.add_argument("seed", type=int)
    p.add_argument("--json", action="store_true",
                   help="Emit JSON instead of Markdown")
    args = p.parse_args()

    vdir = args.suite_dir / f"variant_{args.variant}"
    if not vdir.is_dir():
        print(f"ERROR: {vdir} not a directory", file=sys.stderr)
        return 2

    memstat = _read_jsonl(vdir / f"seed_{args.seed}.memstat.jsonl")
    events = _read_jsonl(vdir / f"seed_{args.seed}.events.jsonl")
    llm = _read_jsonl(vdir / f"seed_{args.seed}.llm.jsonl")

    if not (memstat or events or llm):
        print(f"ERROR: no instrumentation files found in {vdir}",
              file=sys.stderr)
        return 1

    report = _analyze(memstat, events, llm)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(_render_markdown(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
