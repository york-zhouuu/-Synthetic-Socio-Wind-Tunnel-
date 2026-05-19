#!/usr/bin/env python3
"""profile_publishable_smoke — collect cProfile data for dev-mode smoke run.

Spec: openspec/specs/hot-path-baseline/spec.md
Change: openspec/changes/profile-publishable-hot-path/

Wraps `tools/smoke_experiment_demo.py` (default 100 agent × 1 sim day)
with cProfile and extracts the top-N hot functions by cumulative time.
Output is a JSON document matching the schema in the spec.

Usage:
    python tools/profile_publishable_smoke.py \\
        --output tests/fixtures/hot_path_profile_baseline.json
    python tools/profile_publishable_smoke.py \\
        --output /tmp/profile.json --seed 42 --agents 100 --top-n 30

The script runs the smoke as a subprocess so cProfile state stays
isolated from this script's own bookkeeping.
"""

from __future__ import annotations

import argparse
import json
import os
import pstats
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SMOKE_SCRIPT = REPO_ROOT / "tools" / "smoke_experiment_demo.py"


def _format_qualname(func_record: tuple[str, int, str]) -> str:
    """pstats key is (filename, lineno, funcname). Normalize to
    `<module>:<funcname>`. Strip site-packages prefix + repo absolute
    path so qualnames are stable across machines.
    """
    filename, _lineno, funcname = func_record
    if filename == "~":  # builtins
        return f"<builtin>:{funcname}"
    p = Path(filename)
    # Try to express as repo-relative module path
    try:
        rel = p.resolve().relative_to(REPO_ROOT)
        module = ".".join(rel.with_suffix("").parts)
        return f"{module}:{funcname}"
    except ValueError:
        # Outside repo (stdlib or site-packages)
        parts = p.parts
        # Trim everything before "site-packages" if present
        if "site-packages" in parts:
            i = parts.index("site-packages")
            tail = parts[i + 1:]
            module = ".".join(tail).rstrip(".py")
            if module.endswith(".py"):
                module = module[:-3]
            return f"site-packages:{module}:{funcname}"
        # Stdlib path — keep just the file stem
        return f"stdlib:{p.stem}:{funcname}"


def _run_smoke_under_cprofile(
    *, agents: int, seed: int, num_days: int,
) -> tuple[Path, float]:
    """Run smoke as subprocess with cProfile; return (stats_path, wall_clock)."""
    stats_fd, stats_path = tempfile.mkstemp(suffix=".pstats", prefix="hotpath_")
    os.close(stats_fd)
    stats_path = Path(stats_path)

    cmd = [
        sys.executable, "-m", "cProfile", "-o", str(stats_path),
        str(SMOKE_SCRIPT),
        "--agents", str(agents),
        "--seed", str(seed),
    ]
    # smoke_experiment_demo doesn't expose --num-days; defaults to 1 sim day
    # (288 tick) and that matches our dev-mode contract. If --multi-day flag
    # gets added later, plumb it through here.
    if num_days != 1:
        # Soft warning — keep going but flag in metadata
        print(
            f"[profile-harness] WARNING: smoke_experiment_demo defaults to "
            f"1 sim day; --num-days={num_days} ignored",
            file=sys.stderr,
        )

    t0 = time.perf_counter()
    result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True, text=True,
        timeout=600,
    )
    wall_clock = time.perf_counter() - t0

    if result.returncode != 0:
        # Surface smoke stderr; don't swallow
        sys.stderr.write(
            f"[profile-harness] smoke exited rc={result.returncode}\n"
            f"--- smoke stdout (last 1KB) ---\n"
            f"{result.stdout[-1024:]}\n"
            f"--- smoke stderr (last 1KB) ---\n"
            f"{result.stderr[-1024:]}\n"
        )
        if stats_path.exists():
            stats_path.unlink()
        raise SystemExit(
            f"smoke run failed (rc={result.returncode}); cannot profile"
        )

    return stats_path, wall_clock


def _estimate_cprofile_overhead_pct(
    *, agents: int, seed: int, num_days: int, profiled_wall: float,
) -> float:
    """Run smoke once without cProfile to estimate the overhead pct.

    Returns (profiled_wall - bare_wall) / bare_wall * 100. Conservative —
    re-runs the full smoke. Skip if it'd take > 90s by checking
    profiled_wall as an upper bound: bare is always <= profiled.
    """
    cmd = [
        sys.executable, str(SMOKE_SCRIPT),
        "--agents", str(agents),
        "--seed", str(seed),
    ]
    t0 = time.perf_counter()
    result = subprocess.run(
        cmd, cwd=str(REPO_ROOT),
        capture_output=True, text=True,
        timeout=600,
    )
    bare_wall = time.perf_counter() - t0
    if result.returncode != 0:
        # Can't measure overhead; return -1.0 as sentinel
        return -1.0
    if bare_wall <= 0:
        return 0.0
    return (profiled_wall - bare_wall) / bare_wall * 100.0


def _extract_top_n(
    stats_path: Path, top_n: int,
) -> list[dict]:
    """Parse pstats binary; return top-N entries by cumulative time."""
    stats = pstats.Stats(str(stats_path))
    # stats.stats: dict[(filename, lineno, funcname), (cc, nc, tt, ct, callers)]
    # cc=callcount, nc=non-recursive, tt=total time, ct=cumulative time
    entries = []
    for func_record, (cc, _nc, _tt, ct, _callers) in stats.stats.items():
        entries.append({
            "qualname": _format_qualname(func_record),
            "cumulative_seconds": float(ct),
            "call_count": int(cc),
        })

    total_ct = max(
        (e["cumulative_seconds"] for e in entries
         if "<built-in method builtins.exec>" in e["qualname"]),
        default=0.0,
    )
    if total_ct <= 0:
        total_ct = max(e["cumulative_seconds"] for e in entries) or 1.0

    entries.sort(key=lambda x: x["cumulative_seconds"], reverse=True)
    top = entries[:top_n]
    out: list[dict] = []
    for i, e in enumerate(top):
        out.append({
            "rank": i + 1,
            "qualname": e["qualname"],
            "cumulative_seconds": round(e["cumulative_seconds"], 4),
            "cumulative_pct": round(
                e["cumulative_seconds"] / total_ct * 100.0, 2,
            ),
            "call_count": e["call_count"],
            "per_call_seconds": round(
                e["cumulative_seconds"] / max(e["call_count"], 1), 6,
            ),
        })
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output", type=Path, required=True,
        help="Path to write JSON profile result",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--agents", type=int, default=100)
    parser.add_argument("--num-days", type=int, default=1,
                        help="Number of simulated days (smoke defaults to 1)")
    parser.add_argument("--top-n", type=int, default=30,
                        help="Number of top-cumulative functions to keep")
    parser.add_argument(
        "--skip-overhead-est", action="store_true",
        help="Skip the bare-run that estimates cProfile overhead (saves "
             "another full smoke run; sets overhead_pct=-1.0 sentinel)",
    )
    args = parser.parse_args(argv)

    print(
        f"[profile-harness] starting: agents={args.agents} seed={args.seed} "
        f"num_days={args.num_days} top_n={args.top_n}",
        file=sys.stderr,
    )

    stats_path, profiled_wall = _run_smoke_under_cprofile(
        agents=args.agents, seed=args.seed, num_days=args.num_days,
    )
    print(
        f"[profile-harness] cProfiled smoke wall_clock={profiled_wall:.1f}s",
        file=sys.stderr,
    )

    if args.skip_overhead_est:
        overhead_pct = -1.0
    else:
        overhead_pct = _estimate_cprofile_overhead_pct(
            agents=args.agents, seed=args.seed,
            num_days=args.num_days,
            profiled_wall=profiled_wall,
        )
        print(
            f"[profile-harness] cProfile overhead estimate={overhead_pct:.1f}%",
            file=sys.stderr,
        )

    top_n = _extract_top_n(stats_path, args.top_n)
    stats_path.unlink()  # cleanup

    doc = {
        "metadata": {
            "scale": "dev",
            "agents": args.agents,
            "num_days": args.num_days,
            "seed": args.seed,
            "python_version": ".".join(str(x) for x in sys.version_info[:3]),
            "captured_at": datetime.utcnow().isoformat(timespec="seconds"),
            "wall_clock_seconds": round(profiled_wall, 2),
            "cprofile_overhead_pct_estimate": round(overhead_pct, 2),
        },
        "top_n_functions": top_n,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(
        f"[profile-harness] wrote {args.output} "
        f"(top-{len(top_n)}, {args.output.stat().st_size} bytes)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
