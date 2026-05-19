#!/usr/bin/env python3
"""summarize_run_observability — post-mortem report for an in-flight run.

Pulls together everything we instrument across changes:

- `DayRunSummary.rss_mb` / `vms_mb` — per-day worker memory footprint
  (establish-observability-baselines)
- `DayRunSummary.memory_store_event_count` — event accumulation
  (enforce-worker-rss-cap)
- `DayRunSummary.evicted_encounter_count` — cold-prune effectiveness
  (enforce-worker-rss-cap)
- `DayRunSummary.tick_latency_ms_*` — tick-end latency p50/p95/max
  (establish-observability-baselines)
- `DayRunSummary.gc_collections` — GC pressure
  (establish-observability-baselines)
- worker_<variant>.log — grep counts for:
    - `do_something LLM failed.*APIConnectionError` (transient errors)
    - `all 8 keys open` (circuit breaker tripping)
    - `[gc] tick_global=` (gc.collect + malloc relief fires)
    - `[memory] RSS .* > threshold` (RSS cap trigger — enforce-worker-rss-cap)
    - `[suite] worker-pool stagger` (stagger-worker-spawn engaged)
    - `[retry] attempt` (retry-network-blip-tolerance engaged — future)
    - `deferred_due_to_stagger` (multi-cell stagger deferral)

Reads from:

- `<suite_dir>/variant_<v>/seed_<N>_day*.partial.json` (most-recent per cell)
- `<suite_dir>/variant_<v>/seed_<N>.json` (if DONE)
- `<suite_dir>/worker_<v>.log` (cell worker log)
- `~/Library/Logs/swt-resume-watchdog.log` (LaunchAgent log)
- `~/Library/Logs/swt-resume-watchdog-last-spawn.json` (stagger timestamp)

Emits a Markdown summary suitable for posting / archiving as forensics
record. JSON output (--json) for piping into other tools.

Usage:
    python tools/summarize_run_observability.py \\
        data/experiments/20260518_..._seed42_... 42

    python tools/summarize_run_observability.py <suite_dir> <seed> --json
    python tools/summarize_run_observability.py <suite_dir> <seed> \\
        --watch 300  # refresh every 5 min
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


VARIANTS = (
    "baseline", "global_distraction", "hyperlocal_push", "phone_friction",
)

# Regex patterns to count in worker logs
_LOG_PATTERNS = {
    "apiconnection_errors": re.compile(
        r"do_something LLM failed.*APIConnectionError",
    ),
    "all_keys_open_events": re.compile(r"all 8 keys open"),
    "gc_collect_fires": re.compile(r"\[gc\] tick_global="),
    "rss_cap_triggers": re.compile(r"\[memory\] RSS .* > threshold"),
    "stagger_engaged": re.compile(r"worker-pool stagger:"),
    "retry_attempts": re.compile(r"\[retry\] attempt"),
    "fallback_budget_exceeded": re.compile(r"FallbackBudgetExceeded"),
    "graceful_stop_setup_aborted": re.compile(
        r"aborted_in_setup",
    ),
}

# Captures tick_global + rss MB from `[gc] tick_global=NNN freed=N rss=MMMMB`
# log lines. For in-flight cells (no seed_N.json), this is the only RSS
# trajectory source.
_GC_RSS_PATTERN = re.compile(
    r"\[gc\] tick_global=(\d+) freed=\d+ rss=(\d+)MB",
)


def _read_latest_partial(vdir: Path, seed: int) -> dict[str, Any] | None:
    """Return the most-recent day partial JSON content for a cell."""
    partials = sorted(vdir.glob(f"seed_{seed}_day*.partial.json"))
    if not partials:
        return None
    try:
        with open(partials[-1]) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _read_seed_done(vdir: Path, seed: int) -> dict[str, Any] | None:
    """Return seed_N.json content if cell is DONE."""
    seed_json = vdir / f"seed_{seed}.json"
    if not seed_json.is_file():
        return None
    try:
        with open(seed_json) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _scan_log(log_path: Path) -> dict[str, Any]:
    """Scan a worker log: counts + RSS trajectory from `[gc]` lines."""
    counts: dict[str, Any] = {k: 0 for k in _LOG_PATTERNS}
    counts["log_lines"] = 0
    counts["log_size_bytes"] = 0
    counts["rss_samples"] = []  # list[(tick_global, rss_mb)]
    if not log_path.is_file():
        return counts
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return counts
    counts["log_size_bytes"] = len(text.encode("utf-8"))
    counts["log_lines"] = text.count("\n")
    for name, pat in _LOG_PATTERNS.items():
        counts[name] = len(pat.findall(text))
    # RSS trajectory from gc log lines (best-effort for in-flight cells)
    samples = []
    for m in _GC_RSS_PATTERN.finditer(text):
        try:
            samples.append((int(m.group(1)), int(m.group(2))))
        except ValueError:
            pass
    counts["rss_samples"] = samples
    return counts


def _extract_observability_series(
    cell_data: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """From either a partial or a DONE seed_N.json, pull per-day series."""
    if cell_data is None:
        return []
    # DONE format: {"multi_day_result": {"per_day_summaries": [...]}}
    if "multi_day_result" in cell_data:
        days = cell_data["multi_day_result"].get("per_day_summaries", [])
    else:
        # Partial format: top-level may already be a DayRunSummary or
        # wrap a list. Defensive: look for per_day_summaries key.
        days = cell_data.get("per_day_summaries", [])
        if not days and isinstance(cell_data, dict):
            # Partial is likely a single DayRunSummary dict
            if "rss_mb" in cell_data:
                days = [cell_data]
    return list(days)


def _summarize_cell(
    suite_dir: Path, seed: int, variant: str,
) -> dict[str, Any]:
    vdir = suite_dir / f"variant_{variant}"
    log_path = suite_dir / f"worker_{variant}.log"

    done_data = _read_seed_done(vdir, seed)
    partial_data = _read_latest_partial(vdir, seed)
    series = _extract_observability_series(done_data or partial_data)

    # Aggregate stats
    days_observed = len(series)
    if series:
        rss_mbs = [
            d.get("rss_mb") for d in series
            if isinstance(d.get("rss_mb"), (int, float))
        ]
        event_counts = [
            d.get("memory_store_event_count") for d in series
            if isinstance(d.get("memory_store_event_count"), (int, float))
        ]
        evicted = sum(
            d.get("evicted_encounter_count", 0) or 0 for d in series
        )
        tick_p50s = [
            d.get("tick_latency_ms_p50") for d in series
            if isinstance(d.get("tick_latency_ms_p50"), (int, float))
        ]
        rss_max = max(rss_mbs) if rss_mbs else None
        rss_last = rss_mbs[-1] if rss_mbs else None
        events_last = event_counts[-1] if event_counts else None
        p50_max = max(tick_p50s) if tick_p50s else None
    else:
        rss_max = rss_last = events_last = p50_max = None
        evicted = 0

    log_counts = _scan_log(log_path)
    rss_samples = log_counts.pop("rss_samples", [])

    # Use log-derived RSS for in-flight cells (no DayRunSummary available)
    if rss_max is None and rss_samples:
        rss_max = max(s[1] for s in rss_samples)
        rss_last = rss_samples[-1][1] if rss_samples else None
    rss_sample_count = len(rss_samples)

    # Count partials as a state signal (cell was interrupted but progressed)
    partial_count = len(list(vdir.glob(f"seed_{seed}_day*.partial.json")))

    if done_data:
        state = "DONE"
    elif partial_count > 0 or rss_samples:
        state = f"INTERRUPTED (day{partial_count - 1} reached)" if partial_count > 0 else "INTERRUPTED"
    else:
        state = "UNKNOWN"

    return {
        "suite": suite_dir.name,
        "seed": seed,
        "variant": variant,
        "state": state,
        "days_observed": days_observed,
        "partial_count": partial_count,
        "rss_mb_max": rss_max,
        "rss_mb_last_day": rss_last,
        "rss_sample_count_from_log": rss_sample_count,
        "memory_store_event_count_last_day": events_last,
        "evicted_encounter_total": evicted,
        "tick_latency_ms_p50_max_across_days": p50_max,
        "log_counts": log_counts,
    }


def _render_markdown(rows: list[dict[str, Any]]) -> str:
    """Render per-cell observability summary as Markdown."""
    lines = []
    lines.append(
        f"# Observability summary — generated "
        f"{datetime.now().isoformat(timespec='seconds')}\n",
    )

    lines.append("## Memory & latency (from DayRunSummary)\n")
    lines.append(
        "| cell | state | days | RSS max | RSS last | events last | "
        "evicted Σ | p50 max ms |",
    )
    lines.append("|---|---|--:|--:|--:|--:|--:|--:|")
    for r in rows:
        cell = f"s{r['seed']}/{r['variant']}"
        lines.append(
            f"| {cell} | {r['state']} | {r['days_observed']} | "
            f"{r['rss_mb_max'] or '—'} | "
            f"{r['rss_mb_last_day'] or '—'} | "
            f"{r['memory_store_event_count_last_day'] or '—'} | "
            f"{r['evicted_encounter_total']} | "
            f"{r['tick_latency_ms_p50_max_across_days'] or '—'} |",
        )

    lines.append("\n## Log signal counts\n")
    lines.append(
        "| cell | log MB | lines | APIConnErr | 8keys open | gc fires | "
        "RSS trips | stagger | budget exceeded |",
    )
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for r in rows:
        cell = f"s{r['seed']}/{r['variant']}"
        lc = r["log_counts"]
        size_mb = round(lc["log_size_bytes"] / 1024 / 1024, 1)
        lines.append(
            f"| {cell} | {size_mb} | {lc['log_lines']} | "
            f"{lc['apiconnection_errors']} | "
            f"{lc['all_keys_open_events']} | "
            f"{lc['gc_collect_fires']} | "
            f"{lc['rss_cap_triggers']} | "
            f"{lc['stagger_engaged']} | "
            f"{lc['fallback_budget_exceeded']} |",
        )

    lines.append("\n## Health flags\n")
    for r in rows:
        cell = f"s{r['seed']}/{r['variant']}"
        flags = []
        lc = r["log_counts"]
        if r["rss_mb_max"] and r["rss_mb_max"] > 9000:
            flags.append(
                f"⚠️ RSS approaching 10GB cap "
                f"(max {r['rss_mb_max']:.0f}MB)",
            )
        if lc["fallback_budget_exceeded"] > 0:
            flags.append(
                f"🚨 FallbackBudgetExceeded fired "
                f"{lc['fallback_budget_exceeded']}× — worker self-killed",
            )
        if lc["all_keys_open_events"] > 0:
            flags.append(
                f"⚠️ all 8 keys cooldown {lc['all_keys_open_events']}× — "
                f"check API connectivity",
            )
        if lc["rss_cap_triggers"] > 0:
            flags.append(
                f"ℹ️ RSS cap auto-restart fired {lc['rss_cap_triggers']}× "
                f"— enforce-worker-rss-cap working as designed",
            )
        if (lc["apiconnection_errors"] > 50
                and lc["retry_attempts"] == 0):
            flags.append(
                f"⚠️ {lc['apiconnection_errors']} APIConnErr but 0 retry "
                f"log lines — retry-network-blip-tolerance may not be "
                f"engaged (check if worker started before 1df2175)",
            )
        if flags:
            lines.append(f"\n### {cell}")
            for f in flags:
                lines.append(f"- {f}")
    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "args", nargs="+",
        help="Alternating <suite_dir> <seed> pairs",
    )
    p.add_argument("--json", action="store_true",
                   help="Emit JSON instead of Markdown")
    p.add_argument("--variants", default=",".join(VARIANTS))
    p.add_argument("--watch", type=int, default=0,
                   help="Refresh every N seconds (0 = one-shot)")
    args = p.parse_args()

    if len(args.args) % 2 != 0:
        print("ERROR: args must come in (suite_dir, seed) pairs",
              file=sys.stderr)
        return 2

    variants = [v.strip() for v in args.variants.split(",") if v.strip()]

    def _run_once() -> list[dict[str, Any]]:
        rows = []
        for i in range(0, len(args.args), 2):
            suite_dir = Path(args.args[i])
            seed = int(args.args[i + 1])
            for v in variants:
                rows.append(_summarize_cell(suite_dir, seed, v))
        return rows

    while True:
        rows = _run_once()
        if args.json:
            print(json.dumps({"cells": rows}, indent=2, ensure_ascii=False))
        else:
            print(_render_markdown(rows))
        if args.watch <= 0:
            break
        time.sleep(args.watch)
    return 0


if __name__ == "__main__":
    sys.exit(main())
