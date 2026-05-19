"""Bug C — emit_llm_call wired into tier clients (subprocess e2e).

Real dev smoke with `LLM_SAMPLE_RATE=1.0` → llm.jsonl SHALL contain
real call records. This is the test that would have caught the
"spec'd but not wired" gap.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[1]


def _run_smoke(tmp_path: Path, *, suite_name: str = "smoke_llm") -> Path:
    """Run dev smoke subprocess; return variant dir."""
    env = os.environ.copy()
    env.pop("INSTRUMENTATION_OUTPUT_DIR", None)
    env.pop("INSTRUMENTATION_SEED", None)
    env["LLM_SAMPLE_RATE"] = "1.0"  # 100% sample so test is deterministic
    env["LLM_RECORD_ERRORS_ALL"] = "true"
    env["INSTRUMENTATION_SAMPLE_EVERY_N_TICKS"] = "12"

    cmd = [
        sys.executable, "tools/run_variant_suite.py",
        "--variants", "baseline",
        "--seeds", "1", "--seed-start", "42",
        "--num-days", "1", "--agents", "10",
        "--num-protagonists", "5",
        "--mode", "dev", "--phase-days", "1,0,0",
        "--output-dir", str(tmp_path),
        "--suite-name", suite_name,
        "--skip-preflight",
        "--use-aitown", "--aitown-provider", "stub",
    ]
    result = subprocess.run(
        cmd, env=env, capture_output=True, text=True,
        timeout=360, cwd=str(_REPO),
    )
    assert result.returncode == 0, (
        f"smoke failed rc={result.returncode}\n"
        f"stderr={result.stderr[-2000:]}"
    )
    suite_dirs = list(tmp_path.glob(f"*_{suite_name}"))
    assert len(suite_dirs) == 1
    return suite_dirs[0] / "variant_baseline"


@pytest.mark.slow
def test_dev_smoke_writes_llm_jsonl_with_success_records(
    tmp_path: Path,
) -> None:
    """spec: llm.jsonl SHALL have real LLM call records after a real run."""
    out_dir = _run_smoke(tmp_path)
    llm_path = out_dir / "seed_42.llm.jsonl"
    assert llm_path.exists(), (
        f"llm.jsonl missing — emit_llm_call wiring broken. "
        f"dir contents: {list(out_dir.iterdir())}"
    )
    lines = [
        json.loads(l) for l in llm_path.read_text().splitlines() if l
    ]
    # 10 agents × 288 ticks dev smoke with stub provider. Stub does NOT
    # call generate per-tick for every agent; the aitown OperationPool
    # only triggers it for ops like do_something / generate_message /
    # reflect. Empirically ~50 calls for 10agent/1day smoke. Floor
    # at 10 to detect "0 records = wiring broken".
    assert len(lines) >= 10, (
        f"expected ≥10 llm.jsonl records at sample_rate=1.0, "
        f"got {len(lines)} — emit_llm_call wiring may be broken"
    )


@pytest.mark.slow
def test_emit_llm_call_includes_required_fields(tmp_path: Path) -> None:
    """Each emit line SHALL have schema fields per spec."""
    out_dir = _run_smoke(tmp_path, suite_name="smoke_llm_schema")
    llm_path = out_dir / "seed_42.llm.jsonl"
    lines = [
        json.loads(l) for l in llm_path.read_text().splitlines() if l
    ]
    assert lines, "no llm records"
    required = {"v", "tier", "provider", "model", "status",
                "latency_ms", "attempt", "max_attempts"}
    for line in lines[:5]:
        missing = required - set(line.keys())
        assert not missing, f"missing fields {missing} in {line}"
    # At least one success status
    success_lines = [l for l in lines if l.get("status") == "success"]
    assert len(success_lines) >= 1
    # provider is one of our known providers (stub for dev smoke)
    providers = {l.get("provider") for l in lines}
    assert "stub" in providers, (
        f"expected stub provider in dev smoke, got {providers}"
    )
