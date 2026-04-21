"""Tests for E1/E2/E3 audits — run on a programmatically-built small atlas."""

from __future__ import annotations

import pytest

from synthetic_socio_wind_tunnel.atlas import Atlas
from synthetic_socio_wind_tunnel.cartography.builder import RegionBuilder
from synthetic_socio_wind_tunnel.fitness.audits import (
    audit_e1_digital_lure,
    audit_e2_spatial_unlock,
    audit_e3_shared_perception,
)
from synthetic_socio_wind_tunnel.fitness.report import AuditStatus


def _small_atlas() -> Atlas:
    region = (
        RegionBuilder("test_region", "test_region")
        .add_outdoor("street_a", "Street A", area_type="street")
        .polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        .end_outdoor()
        .add_outdoor("street_b", "Street B", area_type="street")
        .polygon([(15, 0), (25, 0), (25, 10), (15, 10)])
        .end_outdoor()
        .connect("street_a", "street_b", path_type="road", distance=5.0)
        .build()
    )
    return Atlas(region)


class TestE1:

    def test_all_three_checks_pass(self):
        atlas = _small_atlas()
        cat = audit_e1_digital_lure(atlas)
        assert cat.category == "e1-digital-lure"
        ids = [r.id for r in cat.results]
        assert ids == [
            "e1.push-reaches-target",
            "e1.push-respects-attention-state",
            "e1.feed-log-extractable",
        ]
        statuses = [r.status for r in cat.results]
        assert all(s == AuditStatus.PASS for s in statuses), [
            (r.id, r.status.value, r.detail) for r in cat.results
        ]


class TestE2:

    def test_skips_when_no_doors(self):
        """Pure street atlas has no doors — E2 audit SHALL skip with pointer."""
        atlas = _small_atlas()
        cat = audit_e2_spatial_unlock(atlas)
        assert cat.category == "e2-spatial-unlock"
        assert len(cat.results) == 3
        for r in cat.results:
            assert r.status == AuditStatus.SKIP
            assert r.mitigation_change == "cartography"


class TestE3:

    def test_shared_task_memory_seam_skips(self):
        atlas = _small_atlas()
        cat = audit_e3_shared_perception(atlas)
        assert cat.category == "e3-shared-perception"
        seam = next(r for r in cat.results if r.id == "e3.shared-task-memory-seam")
        assert seam.status == AuditStatus.SKIP
        assert seam.mitigation_change == "memory"

    def test_looking_for_propagation_passes(self):
        atlas = _small_atlas()
        cat = audit_e3_shared_perception(atlas)
        prop = next(r for r in cat.results if r.id == "e3.looking-for-propagation")
        assert prop.status == AuditStatus.PASS
