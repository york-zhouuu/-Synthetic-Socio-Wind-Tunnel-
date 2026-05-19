#!/usr/bin/env python3
"""dump_runtime_observability — RSS time-series sampler for dev smoke runs.

Spec: openspec/specs/runtime-observability/spec.md, Requirement
"RSS time-series harness".

Spawns `tools/smoke_experiment_demo.py` as a subprocess and samples
`psutil.Process(child_pid).memory_info()` every N tick-equivalent wall
intervals. Output is a JSON time series suitable for plotting + diff.

Sampling cadence:
- Smoke runs 288 ticks per simulated day.
- We don't directly observe tick boundaries from outside the child;
  instead we approximate by sampling every (wall_dev_smoke_seconds /
  288 * sample_every_n_ticks) seconds. Default sample_every_n_ticks=12
  → ~24 samples/day, matching DayRunSummary observability cadence.

Usage:
    python tools/dump_runtime_observability.py \\
        --output tests/fixtures/rss_timeseries_dev_100agent_1day.json \\
        [--seed 42 --agents 100 --sample-every-n-ticks 12]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SMOKE_SCRIPT = REPO_ROOT / "tools" / "smoke_experiment_demo.py"


def _sample_loop(
    *, child_pid: int, sample_interval_s: float, ticks_per_day: int,
    sample_every_n_ticks: int,
) -> list[dict]:
    """Poll psutil while child runs; one sample per interval."""
    import psutil
    proc = psutil.Process(child_pid)
    samples: list[dict] = []
    start = time.perf_counter()
    next_tick_global = 0
    while True:
        try:
            mem = proc.memory_info()
            elapsed = time.perf_counter() - start
            samples.append({
                "tick_global": next_tick_global,
                "rss_mb": round(mem.rss / 1024 / 1024, 2),
                "vms_mb": round(mem.vms / 1024 / 1024, 2),
                "elapsed_seconds": round(elapsed, 3),
            })
            next_tick_global += sample_every_n_ticks
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # Child exited; one final-state sample isn't reliable
            break
        time.sleep(sample_interval_s)
        # Check if child is still alive
        if not proc.is_running():
            break
    return samples


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--agents", type=int, default=100)
    parser.add_argument("--num-days", type=int, default=1)
    parser.add_argument("--sample-every-n-ticks", type=int, default=12,
                        help="Sample interval in tick units (default 12)")
    parser.add_argument("--ticks-per-day", type=int, default=288,
                        help="Smoke's ticks-per-day (default 288)")
    args = parser.parse_args(argv)

    # Estimate sample interval in seconds: assume dev smoke takes
    # ~3-10s for 1 day. To get sample_every_n_ticks-equivalent cadence,
    # we estimate ~30ms per tick and sample every N×30ms.
    estimated_tick_seconds = 0.02  # 20 ms (empirical at 100-agent dev scale)
    sample_interval_s = args.sample_every_n_ticks * estimated_tick_seconds

    print(
        f"[obs-harness] launching smoke (agents={args.agents}, seed={args.seed}); "
        f"sampling every ~{sample_interval_s*1000:.0f}ms",
        file=sys.stderr,
    )

    t0 = time.perf_counter()
    child = subprocess.Popen(
        [sys.executable, str(SMOKE_SCRIPT),
         "--agents", str(args.agents),
         "--seed", str(args.seed)],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )

    try:
        samples = _sample_loop(
            child_pid=child.pid,
            sample_interval_s=sample_interval_s,
            ticks_per_day=args.ticks_per_day,
            sample_every_n_ticks=args.sample_every_n_ticks,
        )
        # Wait for child to finish
        rc = child.wait(timeout=300)
        if rc != 0:
            stderr = child.stderr.read().decode()[-500:]
            sys.stderr.write(
                f"[obs-harness] smoke exited rc={rc}\nstderr tail:\n{stderr}\n"
            )
            return rc
    finally:
        if child.poll() is None:
            child.kill()

    total_wall = time.perf_counter() - t0
    print(
        f"[obs-harness] captured {len(samples)} samples in {total_wall:.1f}s",
        file=sys.stderr,
    )

    if len(samples) == 0:
        sys.stderr.write(
            "[obs-harness] ERROR: 0 samples captured — smoke finished too "
            "fast or psutil failed; widen sample interval or increase agents\n"
        )
        return 1

    doc = {
        "metadata": {
            "scale": "dev",
            "agents": args.agents,
            "num_days": args.num_days,
            "seed": args.seed,
            "sample_every_n_ticks": args.sample_every_n_ticks,
            "ticks_per_day": args.ticks_per_day,
            "captured_at": datetime.utcnow().isoformat(timespec="seconds"),
            "total_wall_seconds": round(total_wall, 2),
        },
        "samples": samples,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(doc, ensure_ascii=False, indent=2))
    print(
        f"[obs-harness] wrote {args.output} ({args.output.stat().st_size} bytes)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
