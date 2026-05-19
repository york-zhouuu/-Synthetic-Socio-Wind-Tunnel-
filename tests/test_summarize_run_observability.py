"""Unit tests for tools/summarize_run_observability.py.

Spec: the tool SHALL pull observability data from DayRunSummary fields
when DONE, fall back to worker log `[gc]` lines when in-flight, and
detect known failure signals (FallbackBudgetExceeded, 8-key cooldown,
APIConnectionError bursts).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.summarize_run_observability import (
    _GC_RSS_PATTERN,
    _scan_log,
    _summarize_cell,
)


def _write_worker_log(suite_dir: Path, variant: str, text: str) -> Path:
    log = suite_dir / f"worker_{variant}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(text)
    return log


def _write_partials(
    suite_dir: Path, variant: str, seed: int, days: list[int],
) -> None:
    vdir = suite_dir / f"variant_{variant}"
    vdir.mkdir(parents=True, exist_ok=True)
    for d in days:
        (vdir / f"seed_{seed}_day{d}.partial.json").write_text(json.dumps({
            "schema_version": 1, "seed": seed, "day_index": d,
        }))


def test_scan_log_extracts_gc_rss_samples(tmp_path: Path) -> None:
    """spec: _scan_log SHALL parse `[gc] tick_global=N rss=MMB` lines
    into (tick, rss_mb) samples."""
    log_text = (
        "[setup] starting\n"
        "[gc] tick_global=200 freed=3 rss=1024MB\n"
        "[gc] tick_global=400 freed=5 rss=1156MB\n"
        "[gc] tick_global=600 freed=2 rss=1098MB\n"
        "do_something LLM failed for agent x: APIConnectionError('blip')\n"
        "all 8 keys open; next available at unix=12345.6\n"
    )
    log_path = tmp_path / "worker_baseline.log"
    log_path.write_text(log_text)

    counts = _scan_log(log_path)
    assert counts["log_lines"] == 6
    assert counts["gc_collect_fires"] == 3
    assert counts["apiconnection_errors"] == 1
    assert counts["all_keys_open_events"] == 1
    assert counts["rss_samples"] == [
        (200, 1024), (400, 1156), (600, 1098),
    ]


def test_scan_log_missing_file_returns_zero_counts(tmp_path: Path) -> None:
    """Missing log file → all counts 0, no crash."""
    counts = _scan_log(tmp_path / "nonexistent.log")
    assert counts["log_lines"] == 0
    assert counts["rss_samples"] == []


def test_summarize_cell_done_path(tmp_path: Path) -> None:
    """DONE cell with seed_N.json + per_day_summaries → state=DONE +
    fields extracted."""
    suite = tmp_path / "fake_suite"
    vdir = suite / "variant_baseline"
    vdir.mkdir(parents=True)
    (vdir / "seed_42.json").write_text(json.dumps({
        "multi_day_result": {
            "per_day_summaries": [
                {"rss_mb": 800.0, "memory_store_event_count": 30000,
                 "evicted_encounter_count": 0, "tick_latency_ms_p50": 12.0},
                {"rss_mb": 1200.0, "memory_store_event_count": 50000,
                 "evicted_encounter_count": 5000, "tick_latency_ms_p50": 18.5},
            ],
        },
    }))

    result = _summarize_cell(suite, 42, "baseline")
    assert result["state"] == "DONE"
    assert result["days_observed"] == 2
    assert result["rss_mb_max"] == 1200.0
    assert result["rss_mb_last_day"] == 1200.0
    assert result["memory_store_event_count_last_day"] == 50000
    assert result["evicted_encounter_total"] == 5000


def test_summarize_cell_interrupted_with_partials(tmp_path: Path) -> None:
    """Cell with partials + worker log → state reflects partial count."""
    suite = tmp_path / "fake_suite"
    _write_partials(suite, "phone_friction", 42, [0, 1, 2, 11])
    _write_worker_log(suite, "phone_friction",
                      "[gc] tick_global=200 freed=3 rss=512MB\n")
    result = _summarize_cell(suite, 42, "phone_friction")
    assert "INTERRUPTED" in result["state"]
    assert "day3" in result["state"]  # 4 partials → day 0..3 means day3 reached
    assert result["partial_count"] == 4


def test_summarize_cell_log_rss_used_when_no_done_data(tmp_path: Path) -> None:
    """In-flight cell SHALL use worker log RSS samples as fallback."""
    suite = tmp_path / "fake_suite"
    _write_partials(suite, "phone_friction", 42, [0, 1])
    _write_worker_log(suite, "phone_friction",
        "[gc] tick_global=200 freed=3 rss=900MB\n"
        "[gc] tick_global=400 freed=5 rss=1500MB\n"
        "[gc] tick_global=600 freed=2 rss=1200MB\n")
    result = _summarize_cell(suite, 42, "phone_friction")
    # Log-derived RSS max + last
    assert result["rss_mb_max"] == 1500
    assert result["rss_mb_last_day"] == 1200
    assert result["rss_sample_count_from_log"] == 3


def test_summarize_cell_no_artifacts_returns_unknown(tmp_path: Path) -> None:
    """No partials, no snapshot, no log → UNKNOWN."""
    suite = tmp_path / "fake_suite"
    (suite / "variant_baseline").mkdir(parents=True)
    result = _summarize_cell(suite, 42, "baseline")
    assert result["state"] == "UNKNOWN"


def test_fallback_budget_exceeded_flagged_in_health(tmp_path: Path) -> None:
    """FallbackBudgetExceeded count > 0 SHALL be visible in log_counts."""
    suite = tmp_path / "fake_suite"
    _write_partials(suite, "phone_friction", 42, [0, 1])
    _write_worker_log(suite, "phone_friction",
        "do_something LLM failed: APIConnectionError\n"
        "all 8 keys open\n"
        "synthetic_socio_wind_tunnel.run_resilience.llm_health."
        "FallbackBudgetExceeded: fallback budget exceeded\n")
    result = _summarize_cell(suite, 42, "phone_friction")
    assert result["log_counts"]["fallback_budget_exceeded"] >= 1
    assert result["log_counts"]["all_keys_open_events"] >= 1
    assert result["log_counts"]["apiconnection_errors"] >= 1


def test_gc_rss_pattern_handles_realistic_log_format() -> None:
    """Regression: pattern SHALL match production log format exactly."""
    sample = (
        "INFO 2026-05-19 14:23:01,234 multi_day:818 "
        "[gc] tick_global=200 freed=42 rss=1024MB"
    )
    m = _GC_RSS_PATTERN.search(sample)
    assert m is not None
    assert int(m.group(1)) == 200
    assert int(m.group(2)) == 1024
