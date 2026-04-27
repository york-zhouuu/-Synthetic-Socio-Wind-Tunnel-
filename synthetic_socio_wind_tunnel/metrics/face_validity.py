"""
Face validity protocol — narrative sampling + score aggregation.

Implements `validation-strategy` Part III. Two stages:
1. Pre-survey: `sample_narratives` produces M narratives from a suite for
   reviewers to score on Prolific (or equivalent).
2. Post-survey: `assess_face_validity` reads the score matrix and
   computes pass/fail per spec thresholds.

Spec thresholds: overall_avg ≥ 3.5/5 AND ≤ 20% ratings ≤ 2.

Sim hot path MUST NOT import this module.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from synthetic_socio_wind_tunnel.agent import (
    LANE_COVE_PROFILE,
    AgentProfile,
    sample_population,
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Narrative(BaseModel):
    """One agent's 3-day narrative shown to reviewers."""
    narrative_id: str
    agent_id: str
    variant_name: str
    profile_excerpt: str
    """Short prose: gender / age / occupation / family / community tenure."""
    summary_text: str
    """3-day excerpt, structured per-day with destinations + activities."""

    model_config = ConfigDict(frozen=True)


class Score(BaseModel):
    """One reviewer-narrative scoring tuple."""
    reviewer_id: str
    narrative_id: str
    authenticity: int = Field(ge=1, le=5)
    realism: int = Field(ge=1, le=5)
    free_text: str = ""

    model_config = ConfigDict(frozen=True)


class FaceValidityStatus(BaseModel):
    passed: bool
    overall_avg: float
    pct_low: float
    n_narratives: int
    n_reviewers: int
    details: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(frozen=True)


# ---------------------------------------------------------------------------
# Narrative generation (template-based; no LLM cost)
# ---------------------------------------------------------------------------

def _profile_excerpt(profile: AgentProfile) -> str:
    """One-line snapshot of the agent's identity for reviewer context."""
    parts = [
        f"{profile.age}岁 {profile.gender or '?'} {profile.occupation}",
    ]
    if profile.family_composition:
        parts.append(profile.family_composition.replace("_", " "))
    if profile.community_tenure_5yr:
        parts.append(f"在 Lane Cove {profile.community_tenure_5yr}")
    if profile.unpaid_child_care_hours and profile.unpaid_child_care_hours != "none":
        parts.append(f"育儿 {profile.unpaid_child_care_hours}h/wk")
    if profile.volunteer_status == "volunteer":
        parts.append("志愿者")
    if profile.english_proficiency and profile.english_proficiency != "english_only":
        parts.append(f"母语非英语 (proficiency: {profile.english_proficiency})")
    if profile.work_mode:
        parts.append(profile.work_mode)
    return "；".join(parts)


_DAY_TEMPLATE = (
    "Day {day}: {dest_summary}。"
    "{social} 与邻居{interaction}。"
)

_VARIANT_CONTEXT = {
    "baseline": "无外部干预",
    "hyperlocal_push": "干预期 8-13 日收到附近社区活动推送",
    "global_distraction": "干预期 8-13 日收到全国新闻推送",
    "shared_anchor": "干预期 8-13 日社区共享锚点提示",
    "phone_friction": "干预期 8-13 日手机使用受限",
    "catalyst_seeding": "干预期 8-13 日 social catalyst 引介",
}


def _render_narrative(profile: AgentProfile, variant_name: str, rng: random.Random) -> str:
    """Generate a 3-day narrative for one agent + variant pair."""
    excerpt = _profile_excerpt(profile)
    days = []
    moods = ["独自", "和家人", "和同事"]
    interactions = ["简短问候", "深聊片刻", "擦肩而过", "未交谈"]
    venues = ["咖啡馆", "公园", "图书馆", "便利店", "社区中心"]

    for d in range(1, 4):
        venue = rng.choice(venues)
        social = rng.choice(moods)
        interaction = rng.choice(interactions)
        days.append(
            _DAY_TEMPLATE.format(
                day=d,
                dest_summary=f"早上去{venue}，傍晚回家",
                social=social,
                interaction=interaction,
            )
        )

    variant_note = _VARIANT_CONTEXT.get(variant_name, variant_name)

    return (
        f"【{excerpt}】\n\n"
        f"{chr(10).join(days)}\n\n"
        f"（实验语境：{variant_note}）"
    )


def sample_narratives(
    suite_dir: Path | None = None,
    *,
    M: int = 10,
    seed: int = 42,
    variant_names: list[str] | None = None,
) -> list[Narrative]:
    """
    Sample M narratives, ensuring ≥1 per variant_name.

    suite_dir is optional; when provided, variant_names is read from its
    structure. Otherwise pass variant_names explicitly. Profile pool is
    drawn from LANE_COVE_PROFILE (deterministic by seed).
    """
    if variant_names is None:
        if suite_dir is not None:
            variant_names = [
                p.name.removeprefix("variant_") for p in suite_dir.iterdir()
                if p.is_dir() and p.name.startswith("variant_")
            ]
        if not variant_names:
            variant_names = ["baseline"]

    n_variants = len(variant_names)
    if M < n_variants:
        raise ValueError(
            f"M={M} too small to cover {n_variants} variants ≥1 each"
        )

    # Sample agent pool (M agents)
    template = LANE_COVE_PROFILE.model_copy(update={"size": M})
    profiles = sample_population(template, seed=seed)

    rng = random.Random(seed)
    narratives: list[Narrative] = []

    # Round-robin variant assignment so each variant gets ≥1 narrative
    for i, profile in enumerate(profiles):
        variant = variant_names[i % n_variants]
        text = _render_narrative(profile, variant, random.Random(seed * 1000 + i))
        narratives.append(Narrative(
            narrative_id=f"narrative_{i:02d}",
            agent_id=profile.agent_id,
            variant_name=variant,
            profile_excerpt=_profile_excerpt(profile),
            summary_text=text,
        ))
    return narratives


# ---------------------------------------------------------------------------
# Score aggregation
# ---------------------------------------------------------------------------

def assess_face_validity(
    scores: list[Score], narratives: list[Narrative],
) -> FaceValidityStatus:
    """Compute pass/fail per validation-strategy Part III thresholds."""
    if not scores:
        return FaceValidityStatus(
            passed=False, overall_avg=0.0, pct_low=1.0,
            n_narratives=len(narratives), n_reviewers=0,
            details={"reason": "no scores supplied"},
        )

    auth_avg = sum(s.authenticity for s in scores) / len(scores)
    real_avg = sum(s.realism for s in scores) / len(scores)
    overall_avg = (auth_avg + real_avg) / 2

    # "≤ 20% ratings ≤ 2" — interpret as: percentage of (reviewer × narrative)
    # tuples where MIN of authenticity and realism is ≤ 2
    n_low = sum(1 for s in scores if min(s.authenticity, s.realism) <= 2)
    pct_low = n_low / len(scores)

    n_reviewers = len({s.reviewer_id for s in scores})

    passed = (overall_avg >= 3.5) and (pct_low <= 0.20)

    return FaceValidityStatus(
        passed=passed,
        overall_avg=overall_avg,
        pct_low=pct_low,
        n_narratives=len(narratives),
        n_reviewers=n_reviewers,
        details={
            "authenticity_avg": auth_avg,
            "realism_avg": real_avg,
            "n_ratings": len(scores),
            "thresholds": {"avg_min": 3.5, "pct_low_max": 0.20},
        },
    )


# ---------------------------------------------------------------------------
# Prolific question template renderer
# ---------------------------------------------------------------------------

def render_prolific_template(narratives: list[Narrative]) -> str:
    """Markdown template for Prolific reviewer survey."""
    lines = [
        "# Lane Cove Resident Narrative — Reviewer Survey",
        "",
        "You will read 10 anonymized 3-day narratives describing Lane Cove "
        "residents' daily life. For each, please rate two aspects on a 1-5 "
        "Likert scale (1=very unlikely, 5=very likely).",
        "",
        "**Brief**: Lane Cove (NSW 2066) is a Sydney suburb with ~16k people, "
        "median age 37, mixed apartment + house, high English-fluency + "
        "diverse ancestry (58% Australian-born, 5% China, 3% England, 2% India).",
        "",
    ]
    for n in narratives:
        lines.append(f"## {n.narrative_id}")
        lines.append("")
        lines.append("> " + n.summary_text.replace("\n", "\n> "))
        lines.append("")
        lines.append("- **Q1 (authenticity)**: How likely is this written by a real Lane Cove resident? [1–5]")
        lines.append("- **Q2 (realism)**: How well does this match daily life in Lane Cove? [1–5]")
        lines.append("- **Q3 (optional, free text)**: Which segment seems least realistic? Why?")
        lines.append("")
    return "\n".join(lines)


def parse_scores_csv(csv_text: str) -> list[Score]:
    """
    Parse Prolific scores CSV into Score objects.

    Expected columns: reviewer_id, narrative_id, q1_authenticity, q2_realism, q3_text
    """
    import csv as _csv
    import io
    reader = _csv.DictReader(io.StringIO(csv_text))
    scores: list[Score] = []
    for row in reader:
        try:
            scores.append(Score(
                reviewer_id=row["reviewer_id"].strip(),
                narrative_id=row["narrative_id"].strip(),
                authenticity=int(row.get("q1_authenticity") or row.get("authenticity") or 0),
                realism=int(row.get("q2_realism") or row.get("realism") or 0),
                free_text=row.get("q3_text") or row.get("free_text") or "",
            ))
        except (KeyError, ValueError):
            continue
    return scores


def write_face_validity_report(
    status: FaceValidityStatus, output_path: Path,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                **status.model_dump(),
                "spec_threshold_avg_min": 3.5,
                "spec_threshold_pct_low_max": 0.20,
            },
            indent=2, ensure_ascii=False,
        )
    )
    return output_path


__all__ = [
    "Narrative",
    "Score",
    "FaceValidityStatus",
    "sample_narratives",
    "render_prolific_template",
    "parse_scores_csv",
    "assess_face_validity",
    "write_face_validity_report",
]
