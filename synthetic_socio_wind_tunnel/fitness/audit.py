"""
run_audit - Top-level fitness audit entry point.

Takes an atlas path, runs all category audits, returns a FitnessReport.
Optionally writes to disk (atomic).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from synthetic_socio_wind_tunnel.fitness._common import atlas_signature, iso_now, load_atlas
from synthetic_socio_wind_tunnel.fitness.audits import (
    audit_cost_baseline,
    audit_e1_digital_lure,
    audit_e2_spatial_unlock,
    audit_e3_shared_perception,
    audit_ledger_observability,
    audit_phase1_baseline,
    audit_phase2_gaps,
    audit_profile_distribution,
    audit_scale_baseline,
    audit_site_fitness,
)
from synthetic_socio_wind_tunnel.fitness.report import (
    AuditResult,
    AuditStatus,
    CategoryResult,
    FitnessReport,
)


_DEFAULT_SEED = 42


def run_audit(
    atlas_path: Path | str,
    *,
    scale: Literal["quick", "full"] = "quick",
    output_path: Path | str | None = None,
    profile_seed: int = _DEFAULT_SEED,
    categories: tuple[str, ...] | None = None,
) -> FitnessReport:
    """
    Run the Phase 1.5 fitness audit.

    Args:
        atlas_path: Path to atlas JSON (e.g. data/lanecove_atlas.json).
        scale: "quick" (100×72) or "full" (1000×288) for scale baseline.
        output_path: If given, atomically write FitnessReport JSON to this path.
        profile_seed: Seed for profile-distribution sampling (deterministic).
        categories: Optional whitelist of category ids to run; None = all.

    Returns:
        FitnessReport with all requested category results.
    """
    atlas_path = Path(atlas_path)
    atlas = load_atlas(atlas_path)
    sig = atlas_signature(atlas_path)

    def _wanted(name: str) -> bool:
        return categories is None or name in categories

    results: list[CategoryResult] = []
    scale_baseline = None
    cost_baseline = None
    site_fitness_obj = None

    # Baseline / gap probes first — these provide the anchors Phase 2 changes cite.
    if _wanted("phase1-baseline"):
        results.append(audit_phase1_baseline())
    if _wanted("phase2-gaps"):
        results.append(audit_phase2_gaps())
    # Integration audits (require the corresponding capability to exist).
    if _wanted("e1-digital-lure"):
        results.append(audit_e1_digital_lure(atlas))
    if _wanted("e2-spatial-unlock"):
        results.append(audit_e2_spatial_unlock(atlas))
    if _wanted("e3-shared-perception"):
        results.append(audit_e3_shared_perception(atlas))
    if _wanted("profile-distribution"):
        results.append(audit_profile_distribution(seed=profile_seed))
    if _wanted("ledger-observability"):
        results.append(audit_ledger_observability(atlas))
    # Diagnostic (pure data) categories.
    if _wanted("site-fitness"):
        cat, sf = audit_site_fitness(atlas)
        results.append(cat)
        site_fitness_obj = sf
    if _wanted("scale-baseline"):
        cat, sb = audit_scale_baseline(atlas, scale=scale)
        results.append(cat)
        scale_baseline = sb
    if _wanted("cost-baseline"):
        cat, cb = audit_cost_baseline()
        results.append(cat)
        cost_baseline = cb

    report = FitnessReport(
        generated_at=iso_now(),
        atlas_source=str(atlas_path),
        atlas_signature=sig,
        categories=tuple(results),
        scale_baseline=scale_baseline,
        cost_baseline=cost_baseline,
        site_fitness=site_fitness_obj,
        seeds={"profile_seed": profile_seed},
    )

    if output_path is not None:
        report.to_json(Path(output_path))

    return report


__all__ = ["run_audit"]
