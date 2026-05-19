"""Phase G15 — tail_memstat + analyze_memstat tool tests.

Construct synthetic JSONL inputs and verify both tools surface key signals.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


@pytest.fixture
def synthetic_cell(tmp_path: Path) -> tuple[Path, str, int]:
    """Build a synthetic cell directory with memstat + events + llm."""
    suite = tmp_path / "fake_suite"
    variant = "phone_friction"
    seed = 42
    vdir = suite / f"variant_{variant}"
    vdir.mkdir(parents=True)

    # 5 memstat samples — RSS climbing then stable
    memstat = []
    for i, rss in enumerate([800, 950, 1200, 1180, 1220]):
        memstat.append({
            "v": 1, "ts_iso": f"2026-05-20T01:0{i}:00",
            "ts_monotonic": 100.0 + i,
            "tick_global": 200 * (i + 1),
            "day_index": 0, "tick_in_day": 200 * (i + 1),
            "memory": {"rss_mb": rss, "vms_mb": 5000,
                       "rss_peak_mb": 1250, "threads": 8},
            "cpu": {"percent_recent": 75.0, "user_sec": 10.0,
                    "sys_sec": 0.5,
                    "wall_since_last_sample_sec": 60.0,
                    "tick_count_since_last_sample": 200},
            "gc": {"gen0": 100, "gen1": 10, "gen2": 1},
            "memory_store": {"agents": 1000, "total_events": 50000,
                             "events_by_kind": {"encounter": 40000}},
            "dialogue_service": {"live": 5, "evicted_total": 100},
            "llm_health": {"rolling_fallback_rate": 0.05,
                           "rolling_sample_n": 1000,
                           "keys_open": 0, "keys_total": 8},
            "handler_times_sec": {},
        })
    _write_jsonl(vdir / "seed_42.memstat.jsonl", memstat)

    # Events: phases + 1 eviction + 2 retries + 1 snapshot write
    events = [
        {"v": 1, "kind": "PHASE", "phase": "PROCESS_START",
         "ts_iso": "2026-05-20T01:00:00", "rss_mb": 500},
        {"v": 1, "kind": "PHASE", "phase": "SETUP_START",
         "ts_iso": "2026-05-20T01:00:01", "rss_mb": 500},
        {"v": 1, "kind": "PHASE", "phase": "SETUP_DONE",
         "ts_iso": "2026-05-20T01:01:00", "rss_mb": 800,
         "duration_sec": 59.0},
        {"v": 1, "kind": "EVICT",
         "ts_iso": "2026-05-20T01:02:00",
         "before_tick_cutoff": 100, "events_evicted": 5000,
         "memory_store_total_before": 55000,
         "memory_store_total_after": 50000,
         "duration_sec": 0.3,
         "rss_before_mb": 1300, "rss_after_mb": 1200},
        {"v": 1, "kind": "RETRY",
         "ts_iso": "2026-05-20T01:02:30",
         "tier": "sonnet", "provider": "deepseek", "key_id": 3,
         "attempt": 0, "max_attempts": 3,
         "exc_class": "openai.APIConnectionError",
         "backoff_sec": 0.5},
        {"v": 1, "kind": "RETRY",
         "ts_iso": "2026-05-20T01:02:31",
         "tier": "sonnet", "provider": "deepseek", "key_id": 3,
         "attempt": 1, "max_attempts": 3,
         "exc_class": "openai.APIConnectionError",
         "backoff_sec": 1.0},
        {"v": 1, "kind": "SNAPSHOT_WRITE",
         "ts_iso": "2026-05-20T01:03:00",
         "tick_global": 600, "path": "/tmp/snap.json",
         "duration_sec": 10.5, "size_bytes": 5 * 1024 * 1024,
         "rss_before_mb": 1200, "rss_peak_during_mb": 1280,
         "rss_after_mb": 1220},
        {"v": 1, "kind": "PHASE", "phase": "EXIT",
         "ts_iso": "2026-05-20T01:05:00", "rss_mb": 1220,
         "reason": "done", "final_rss_mb": 1220},
    ]
    _write_jsonl(vdir / "seed_42.events.jsonl", events)

    # LLM: 800 success + 200 fallback
    llm = []
    for i in range(800):
        llm.append({"v": 1, "ts_iso": "2026-05-20T01:02:00",
                    "tier": "sonnet", "provider": "deepseek",
                    "model": "deepseek-v4-pro",
                    "kind": "do_something", "agent_id": f"a_{i}",
                    "key_id": 0, "attempt": 0, "max_attempts": 3,
                    "latency_ms": 1200 + (i % 100),
                    "status": "success"})
    for i in range(200):
        llm.append({"v": 1, "ts_iso": "2026-05-20T01:02:30",
                    "tier": "sonnet", "provider": "deepseek",
                    "model": "deepseek-v4-pro",
                    "kind": "do_something", "agent_id": f"a_{i}",
                    "attempt": 2, "max_attempts": 3,
                    "latency_ms": 8000,
                    "status": "fallback",
                    "exc_class": "openai.APIConnectionError"})
    _write_jsonl(vdir / "seed_42.llm.jsonl", llm)

    return suite, variant, seed


def test_tail_memstat_prints_rss_and_phase(
    synthetic_cell: tuple[Path, str, int],
) -> None:
    """tail_memstat --once SHALL print key signals (RSS, phase, LLM)."""
    suite, variant, seed = synthetic_cell
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(repo / "tools" / "tail_memstat.py"),
         str(suite), variant, str(seed), "--once"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    # SHALL show last RSS (1220 from final sample)
    assert "1220" in out
    # SHALL show last phase
    assert "EXIT" in out
    # SHALL show LLM stats (counts reflect bounded read window —
    # not all 1000 may be in the last 500-line window)
    assert "LLM:" in out
    assert "success=" in out
    assert "fallback=" in out


def test_analyze_memstat_emits_markdown_report(
    synthetic_cell: tuple[Path, str, int],
) -> None:
    """analyze_memstat SHALL emit Markdown with phase / RSS / eviction /
    LLM / retry / snapshot sections."""
    suite, variant, seed = synthetic_cell
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(repo / "tools" / "analyze_memstat.py"),
         str(suite), variant, str(seed)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    md = result.stdout
    # Required sections
    for section in ("Phase timeline", "RSS trajectory", "Eviction",
                    "LLM", "Retries", "Snapshot"):
        assert section in md, f"missing section: {section}"
    # Specific facts
    assert "PROCESS_START" in md
    assert "EXIT" in md
    assert "5,000" in md or "5000" in md  # evicted events count
    assert "1220" in md  # final RSS
    assert "APIConnectionError" in md  # retry classification
    # LLM fallback rate ≥ 10% should set the health flag
    assert "fallback rate" in md.lower()


def test_analyze_json_output(
    synthetic_cell: tuple[Path, str, int],
) -> None:
    """--json mode SHALL emit parseable JSON."""
    suite, variant, seed = synthetic_cell
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(repo / "tools" / "analyze_memstat.py"),
         str(suite), variant, str(seed), "--json"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout)
    assert "phase_timeline" in parsed
    assert "rss" in parsed
    assert "eviction" in parsed
    assert "llm" in parsed
    assert "retries" in parsed
    assert parsed["eviction"]["total_events_evicted"] == 5000
    assert parsed["retries"]["total"] == 2
    assert parsed["llm"]["fallback"] == 200


def test_analyze_handles_missing_files(tmp_path: Path) -> None:
    """If no JSONL files exist, exit 1 with error message."""
    suite = tmp_path / "empty_suite"
    vdir = suite / "variant_phone_friction"
    vdir.mkdir(parents=True)
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(repo / "tools" / "analyze_memstat.py"),
         str(suite), "phone_friction", "42"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 1
    assert "no instrumentation" in result.stderr.lower()
