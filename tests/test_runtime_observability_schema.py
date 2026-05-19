"""Schema-level tests for DayRunSummary observability fields and the
RSS time-series fixture.

Covers spec scenarios:
- Requirement "DayRunSummary 必须包含 runtime observability 字段" →
  * new fields show in model_dump
  * legacy JSON (missing fields) loads with defaults
- Requirement "RSS time-series harness" → fixture schema
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from synthetic_socio_wind_tunnel.orchestrator.multi_day import DayRunSummary

REPO_ROOT = Path(__file__).resolve().parent.parent
RSS_FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "rss_timeseries_dev_100agent_1day.json"


# ============================================================
# A. DayRunSummary observability field schema
# ============================================================


class TestDayRunSummaryObservabilityFields:

    def test_new_fields_appear_in_construction(self) -> None:
        """All 6 new observability fields SHALL be settable + readable."""
        d = DayRunSummary(
            day_index=0,
            simulated_date=date(2026, 4, 22),
            tick_count=288,
            commit_succeeded=100,
            commit_failed=0,
            encounter_count=10,
            # The 6 new observability fields:
            rss_mb=512.5,
            vms_mb=8192.0,
            memory_store_event_count=1234,
            dialogue_count=42,
            gc_collections=(120, 30, 5),
            tick_latency_ms_p50=4.2,
            tick_latency_ms_p95=12.8,
            tick_latency_ms_max=45.1,
        )
        assert d.rss_mb == 512.5
        assert d.vms_mb == 8192.0
        assert d.memory_store_event_count == 1234
        assert d.dialogue_count == 42
        assert d.gc_collections == (120, 30, 5)
        assert d.tick_latency_ms_p50 == 4.2
        assert d.tick_latency_ms_p95 == 12.8
        assert d.tick_latency_ms_max == 45.1

    def test_new_fields_have_safe_defaults(self) -> None:
        """Construction without observability fields SHALL not raise."""
        d = DayRunSummary(
            day_index=0,
            simulated_date=date(2026, 4, 22),
            tick_count=288,
            commit_succeeded=0,
            commit_failed=0,
            encounter_count=0,
        )
        # defaults from spec
        assert d.rss_mb == 0.0
        assert d.vms_mb == 0.0
        assert d.memory_store_event_count == 0
        assert d.dialogue_count == 0
        assert d.gc_collections == (0, 0, 0)
        assert d.tick_latency_ms_p50 == 0.0
        assert d.tick_latency_ms_p95 == 0.0
        assert d.tick_latency_ms_max == 0.0

    def test_model_dump_includes_new_fields(self) -> None:
        """MultiDayResult.model_dump SHALL emit all observability fields."""
        from synthetic_socio_wind_tunnel.orchestrator.multi_day import (
            MultiDayResult,
        )
        from datetime import datetime

        d = DayRunSummary(
            day_index=0,
            simulated_date=date(2026, 4, 22),
            tick_count=288,
            commit_succeeded=0,
            commit_failed=0,
            encounter_count=0,
            rss_mb=100.0,
            memory_store_event_count=50,
        )
        result = MultiDayResult(
            per_day_summaries=(d,),
            total_ticks=288,
            total_encounters=0,
            seed=42,
            started_at=datetime(2026, 4, 22),
            ended_at=datetime(2026, 4, 23),
        )
        dump = result.model_dump()
        pd = dump["per_day_summaries"][0]
        assert "rss_mb" in pd
        assert "vms_mb" in pd
        assert "memory_store_event_count" in pd
        assert "dialogue_count" in pd
        assert "gc_collections" in pd
        assert "tick_latency_ms_p50" in pd
        assert "tick_latency_ms_p95" in pd
        assert "tick_latency_ms_max" in pd
        assert pd["rss_mb"] == 100.0
        assert pd["memory_store_event_count"] == 50


# ============================================================
# B. RSS time-series fixture schema
# ============================================================


_RSS_REQUIRED_METADATA = {
    "scale", "agents", "num_days", "seed",
    "sample_every_n_ticks", "captured_at",
}
_RSS_REQUIRED_SAMPLE = {
    "tick_global", "rss_mb", "vms_mb", "elapsed_seconds",
}


def _validate_rss_schema(doc: dict) -> None:
    assert isinstance(doc, dict)
    assert "metadata" in doc
    assert "samples" in doc
    md = doc["metadata"]
    missing = _RSS_REQUIRED_METADATA - md.keys()
    assert not missing, f"metadata missing: {sorted(missing)}"
    samples = doc["samples"]
    assert isinstance(samples, list)
    assert len(samples) > 0
    # sorted ascending by tick_global
    ticks = [s["tick_global"] for s in samples]
    assert ticks == sorted(ticks), f"samples must be tick-sorted ascending"
    for i, s in enumerate(samples):
        missing = _RSS_REQUIRED_SAMPLE - s.keys()
        assert not missing, f"sample[{i}] missing: {sorted(missing)}"
        assert s["rss_mb"] > 0, f"sample[{i}].rss_mb must be > 0"


class TestRssTimeSeriesFixture:

    def test_handcrafted_minimal_validates(self) -> None:
        doc = {
            "metadata": {
                "scale": "dev", "agents": 100, "num_days": 1,
                "seed": 42, "sample_every_n_ticks": 12,
                "captured_at": "2026-05-19T12:00:00",
            },
            "samples": [
                {"tick_global": 0, "rss_mb": 200.0, "vms_mb": 1024.0,
                 "elapsed_seconds": 0.0},
                {"tick_global": 12, "rss_mb": 210.5, "vms_mb": 1024.0,
                 "elapsed_seconds": 0.5},
                {"tick_global": 24, "rss_mb": 215.0, "vms_mb": 1024.0,
                 "elapsed_seconds": 1.0},
            ],
        }
        _validate_rss_schema(doc)  # no raise

    def test_validator_rejects_unsorted_samples(self) -> None:
        doc = {
            "metadata": {
                "scale": "dev", "agents": 100, "num_days": 1,
                "seed": 42, "sample_every_n_ticks": 12,
                "captured_at": "2026-05-19T12:00:00",
            },
            "samples": [
                {"tick_global": 12, "rss_mb": 210.0, "vms_mb": 1024.0,
                 "elapsed_seconds": 0.5},
                {"tick_global": 0, "rss_mb": 200.0, "vms_mb": 1024.0,
                 "elapsed_seconds": 0.0},  # out of order
            ],
        }
        with pytest.raises(AssertionError, match="tick-sorted"):
            _validate_rss_schema(doc)

    def test_fixture_file_present(self) -> None:
        assert RSS_FIXTURE_PATH.exists(), (
            f"RSS time-series fixture missing: "
            f"{RSS_FIXTURE_PATH.relative_to(REPO_ROOT)}. "
            f"Run: python tools/dump_runtime_observability.py "
            f"--output {RSS_FIXTURE_PATH.relative_to(REPO_ROOT)}"
        )

    def test_fixture_schema_valid(self) -> None:
        if not RSS_FIXTURE_PATH.exists():
            pytest.fail(f"fixture missing: {RSS_FIXTURE_PATH}")
        doc = json.loads(RSS_FIXTURE_PATH.read_text())
        _validate_rss_schema(doc)
        # dev smoke contract:
        assert doc["metadata"]["scale"] == "dev"
        assert doc["metadata"]["agents"] == 100
        # 288 tick / 12 sample-rate ≈ 24 samples expected
        assert len(doc["samples"]) >= 20
