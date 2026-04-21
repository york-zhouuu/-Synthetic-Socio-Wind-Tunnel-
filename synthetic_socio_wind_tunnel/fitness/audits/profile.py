"""Profile distribution audit."""

from __future__ import annotations

import statistics

from synthetic_socio_wind_tunnel.agent import LANE_COVE_PROFILE, sample_population
from synthetic_socio_wind_tunnel.fitness.report import AuditResult, AuditStatus, CategoryResult


def audit_profile_distribution(*, seed: int = 42) -> CategoryResult:
    """
    Three checks on a 1000-agent Lane Cove sample:
    - structural-dims-populated: every value in each distribution appears ≥ once
    - digital-profile-variance:  daily_screen_hours std ≥ 1.5
    - language-coverage-matches-site: at least 2 languages including English and
                                     one Asian language
    """
    results: list[AuditResult] = []
    sample = sample_population(LANE_COVE_PROFILE, seed=seed, num_protagonists=10)

    # 1. structural-dims-populated
    dims_ok = True
    missing: dict[str, list[str]] = {}
    for attr, expected_values in [
        ("ethnicity_group", set(LANE_COVE_PROFILE.ethnicity_distribution.keys())),
        ("housing_tenure", set(LANE_COVE_PROFILE.housing_distribution.keys())),
        ("income_tier", set(LANE_COVE_PROFILE.income_distribution.keys())),
        ("work_mode", set(LANE_COVE_PROFILE.work_mode_distribution.keys())),
    ]:
        seen = {getattr(p, attr) for p in sample}
        missing_vals = expected_values - seen
        if missing_vals:
            dims_ok = False
            missing[attr] = sorted(missing_vals)

    if dims_ok:
        results.append(AuditResult(
            id="profile.structural-dims-populated",
            status=AuditStatus.PASS,
            detail="all 4 structural dimensions fully covered by 1000-sample",
        ))
    else:
        results.append(AuditResult(
            id="profile.structural-dims-populated",
            status=AuditStatus.FAIL,
            detail=f"missing values: {missing}",
            mitigation_change="agent",
            extras={"missing_values": missing},
        ))

    # 2. digital-profile-variance
    screens = [p.digital.daily_screen_hours for p in sample]
    std = statistics.stdev(screens) if len(screens) > 1 else 0.0
    if std >= 1.5:
        results.append(AuditResult(
            id="profile.digital-profile-variance",
            status=AuditStatus.PASS,
            detail=f"daily_screen_hours std = {std:.2f}",
            extras={"std": std, "mean": statistics.mean(screens)},
        ))
    else:
        results.append(AuditResult(
            id="profile.digital-profile-variance",
            status=AuditStatus.FAIL,
            detail=f"std {std:.2f} < 1.5; distribution too narrow",
            mitigation_change="attention-channel",
            extras={"std": std},
        ))

    # 3. language-coverage-matches-site
    languages = {lang for p in sample for lang in p.languages}
    asian_langs = {"Mandarin", "Cantonese", "Korean", "Vietnamese", "Hindi"}
    has_english = "English" in languages
    has_asian = bool(languages & asian_langs)
    if has_english and has_asian:
        results.append(AuditResult(
            id="profile.language-coverage-matches-site",
            status=AuditStatus.PASS,
            detail=f"languages present: {sorted(languages)}",
            extras={"languages": sorted(languages)},
        ))
    else:
        results.append(AuditResult(
            id="profile.language-coverage-matches-site",
            status=AuditStatus.FAIL,
            detail=f"expected English + an Asian language; got {sorted(languages)}",
            mitigation_change="agent",
        ))

    # 4. personality-variance (typed-personality change)
    curiosities = [p.personality.curiosity for p in sample]
    personality_std = statistics.stdev(curiosities) if len(curiosities) > 1 else 0.0
    if personality_std >= 0.15:
        results.append(AuditResult(
            id="profile.personality-variance",
            status=AuditStatus.PASS,
            detail=f"personality.curiosity std = {personality_std:.3f}",
            extras={"std": personality_std},
        ))
    else:
        results.append(AuditResult(
            id="profile.personality-variance",
            status=AuditStatus.FAIL,
            detail=(f"personality.curiosity std {personality_std:.3f} < 0.15; "
                    "agents are too homogeneous — check PersonalityParams"),
            mitigation_change="agent",
            extras={"std": personality_std},
        ))

    return CategoryResult(
        category="profile-distribution",
        results=tuple(results),
    )
