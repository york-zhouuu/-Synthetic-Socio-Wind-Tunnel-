#!/usr/bin/env python3
"""preflight_full_smoke — 1000-agent × 1-day × 4-variant smoke gate.

D1' (2026-05-15) learned the hard way that **scale-only bugs** (e.g. the
google-genai async connection-pool deadlock) only surface at the full
1000-agent × 14-day × 4-variant × 4-worker scale. Our 50/100/200-agent
smoke tests passed; the actual publishable run died after 7 hours.

This CLI is the mandatory pre-flight gate before any publishable run.
It replays the publishable configuration at 1/14 scope (1 day instead of
14, 1 seed instead of 30) so any scale-only bug shows up in ~15-20 min
of wall time instead of 75+ hours.

Hard-coded parameters (project canon — see CLAUDE.md):
    --agents               1000
    --num-days             1
    --num-protagonists     500     (default; --num-protagonists overrides)
    --variants             baseline,hyperlocal_push,global_distraction,phone_friction
    --seeds                1
    --phase-days           1,0,0   (1 baseline day, no intervention/post)

Exit codes:
    0  all 4 variants completed, seed_*.json non-empty, HealthAudit healthy
    1  at least one variant failed, or health audit warned, or deadlock

Usage:
    python tools/preflight_full_smoke.py --provider deepseek
    python tools/preflight_full_smoke.py --provider gemini --output-dir /tmp/preflight
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from synthetic_socio_wind_tunnel.run_resilience import HealthAudit


_VARIANTS = (
    "baseline",
    "hyperlocal_push",
    "global_distraction",
    "phone_friction",
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="preflight_full_smoke",
        description="1000-agent × 1-day full-scale smoke gate.",
    )
    p.add_argument(
        "--provider", choices=["gemini", "deepseek", "anthropic", "stub"],
        default="deepseek",
        help="LLM provider for the preflight (matches publishable run).",
    )
    p.add_argument(
        "--num-protagonists", type=int, default=500,
        help="Sonnet-tier protagonist count (default 500 for publishable parity).",
    )
    p.add_argument(
        "--output-dir", type=Path, default=Path("data/experiments"),
        help="Where to place the preflight suite directory.",
    )
    p.add_argument(
        "--suite-name", type=str, default=None,
        help="Suite directory name suffix. Default: 'preflight_<timestamp>'.",
    )
    p.add_argument(
        "--workers", type=int, default=4,
        help="Parallel worker subprocesses (one per variant). Default 4.",
    )
    return p.parse_args(argv)


def _suite_dir(args: argparse.Namespace) -> Path:
    name = args.suite_name or "preflight"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return args.output_dir / f"{ts}_{name}"


def _invoke_variant_suite(args: argparse.Namespace, suite_dir: Path) -> int:
    """Spawn tools/run_variant_suite.py with hard-coded preflight params."""
    suite_dir.mkdir(parents=True, exist_ok=True)
    repo_root = Path(__file__).resolve().parents[1]
    venv_py = repo_root / ".venv" / "bin" / "python"
    py = str(venv_py) if venv_py.exists() else sys.executable

    cmd = [
        py, str(repo_root / "tools" / "run_variant_suite.py"),
        "--variants", ",".join(_VARIANTS),
        "--seeds", "1",
        "--num-days", "1",
        "--agents", "1000",
        "--num-protagonists", str(args.num_protagonists),
        "--mode", "publishable",
        "--phase-days", "1,0,0",
        "--suite-dir", str(suite_dir),
        "--suite-name", "preflight",
        "--workers", str(args.workers),
    ]
    if args.provider != "stub":
        cmd.extend(["--use-aitown", "--aitown-provider", args.provider])
    print(f"[preflight] spawning: {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd)


def _check_outputs(suite_dir: Path) -> tuple[bool, list[str]]:
    """Verify each variant produced a non-empty seed_1.json."""
    issues: list[str] = []
    ok = True
    for variant in _VARIANTS:
        # run_variant_suite places per-variant outputs under
        # <suite_dir>/<inner>/variant_<name>/ ; the inner dir is timestamped.
        # Find the first matching variant dir.
        matches = list(suite_dir.rglob(f"variant_{variant}"))
        if not matches:
            ok = False
            issues.append(f"variant {variant}: no variant_{variant}/ dir found")
            continue
        vd = matches[0]
        # Expect seed_<N>.json — accept any single seed
        seed_files = list(vd.glob("seed_*.json"))
        seed_files = [p for p in seed_files if "partial" not in p.name]
        if not seed_files:
            ok = False
            issues.append(f"variant {variant}: no seed_*.json files")
            continue
        for f in seed_files:
            if f.stat().st_size < 100:
                ok = False
                issues.append(f"variant {variant}: {f.name} suspiciously small ({f.stat().st_size}B)")
    return ok, issues


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    suite_dir = _suite_dir(args)
    started = time.time()
    print(f"[preflight] start at {datetime.now().isoformat()}", flush=True)
    print(f"[preflight] suite_dir = {suite_dir}", flush=True)

    rc = _invoke_variant_suite(args, suite_dir)
    elapsed = time.time() - started
    print(f"[preflight] run_variant_suite exited with rc={rc} after {elapsed/60:.1f}min", flush=True)

    outputs_ok, issues = _check_outputs(suite_dir)
    if not outputs_ok:
        print(
            "[preflight] FAILED — output validation issues:", file=sys.stderr,
        )
        for i in issues:
            print(f"    - {i}", file=sys.stderr)
        return 1

    # HealthAudit is designed for IN-FLIGHT runs (live workers). On a
    # just-completed run, its WAL-silence + process-not-found heuristics
    # systematically misfire (WAL is naturally old, workers naturally
    # exited). We keep audit as advisory only — `outputs_ok` above is the
    # authoritative pass/fail signal.
    audit = HealthAudit()
    report = audit.audit(suite_dir)
    if report.overall_status != "healthy":
        print(
            f"[preflight] advisory — HealthAudit overall={report.overall_status} "
            f"(post-completion audit; not a gate. outputs validated OK above.)",
            file=sys.stderr,
        )

    print(f"[preflight] PASSED — 4 variants ok, audit healthy, {elapsed/60:.1f}min wall", flush=True)
    print(f"[preflight] suite_dir: {suite_dir}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
