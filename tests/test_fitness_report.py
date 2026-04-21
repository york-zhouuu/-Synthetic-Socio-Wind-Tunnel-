"""Tests for FitnessReport schema + atomic persistence."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from synthetic_socio_wind_tunnel.fitness.report import (
    SCHEMA_VERSION,
    AuditResult,
    AuditStatus,
    CategoryResult,
    CostBaseline,
    FitnessReport,
    ScaleBaseline,
    SiteFitness,
)


def _sample_report() -> FitnessReport:
    return FitnessReport(
        generated_at=datetime(2026, 4, 20, 12, 0, 0),
        atlas_source="data/fake_atlas.json",
        atlas_signature="deadbeef" * 8,
        categories=(
            CategoryResult(
                category="e1-digital-lure",
                results=(
                    AuditResult(id="e1.push-reaches-target",
                                status=AuditStatus.PASS,
                                detail="ok"),
                    AuditResult(id="e1.push-respects-attention-state",
                                status=AuditStatus.FAIL,
                                detail="no missed tag",
                                mitigation_change="attention-channel"),
                ),
            ),
            CategoryResult(
                category="e3-shared-perception",
                results=(
                    AuditResult(id="e3.shared-task-memory-seam",
                                status=AuditStatus.SKIP,
                                detail="no task store",
                                mitigation_change="memory"),
                ),
            ),
        ),
        scale_baseline=ScaleBaseline(
            agents=100, ticks=72,
            wall_seconds_total=5.2,
            wall_seconds_p50=0.04,
            wall_seconds_p99=0.12,
        ),
        cost_baseline=CostBaseline(
            sonnet_calls_estimated=120,
            haiku_calls_estimated=9900,
            skip_calls_estimated=0,
            sonnet_cost_usd_lower=2.0,
            sonnet_cost_usd_upper=8.0,
            haiku_cost_usd_lower=10.0,
            haiku_cost_usd_upper=40.0,
            total_usd_lower=12.0,
            total_usd_upper=48.0,
        ),
        site_fitness=SiteFitness(
            named_building_ratio=0.10,
            residential_ratio=0.96,
            density_buildings_per_km2=474.0,
            notes=("mostly residential",),
        ),
        seeds={"profile_seed": 42},
    )


class TestSchema:

    def test_version_stable(self):
        assert SCHEMA_VERSION == "1.0"

    def test_category_lookup(self):
        report = _sample_report()
        cat = report.category("e1-digital-lure")
        assert cat is not None
        assert len(cat.results) == 2

    def test_category_missing_returns_none(self):
        report = _sample_report()
        assert report.category("no-such-category") is None

    def test_failed_results_flattens_fail_and_skip(self):
        report = _sample_report()
        failed = report.failed_results()
        assert len(failed) == 2
        statuses = {r.status for r in failed}
        assert statuses == {AuditStatus.FAIL, AuditStatus.SKIP}


class TestAtomicWrite:

    def test_write_then_read_roundtrip(self, tmp_path: Path):
        report = _sample_report()
        target = tmp_path / "fitness-report.json"
        report.to_json(target)

        assert target.exists()

        restored = FitnessReport.from_json(target)
        assert restored.schema_version == SCHEMA_VERSION
        assert restored.atlas_signature == report.atlas_signature
        assert restored.category("e1-digital-lure").results[0].id == "e1.push-reaches-target"

    def test_write_creates_missing_parent_dir(self, tmp_path: Path):
        report = _sample_report()
        target = tmp_path / "deep" / "nested" / "report.json"
        report.to_json(target)
        assert target.exists()

    def test_no_tmp_leftover_on_success(self, tmp_path: Path):
        report = _sample_report()
        target = tmp_path / "r.json"
        report.to_json(target)
        # No *.tmp files should remain
        leftover = list(tmp_path.glob("*.tmp"))
        assert leftover == []

    def test_overwrite_existing_file(self, tmp_path: Path):
        report = _sample_report()
        target = tmp_path / "r.json"
        report.to_json(target)
        # Write again with different content
        modified = report.model_copy(update={"atlas_signature": "new_signature"})
        modified.to_json(target)
        restored = FitnessReport.from_json(target)
        assert restored.atlas_signature == "new_signature"


class TestAuditResult:

    def test_pass_without_mitigation(self):
        r = AuditResult(id="x", status=AuditStatus.PASS, detail="ok")
        assert r.mitigation_change is None

    def test_extras_preserved(self):
        r = AuditResult(id="x", status=AuditStatus.PASS,
                        extras={"count": 42, "note": "hello"})
        assert r.extras == {"count": 42, "note": "hello"}
