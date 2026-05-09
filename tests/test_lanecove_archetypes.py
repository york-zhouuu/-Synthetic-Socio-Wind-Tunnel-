"""Tests for Lane Cove archetype loader + matching + identity rendering."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from synthetic_socio_wind_tunnel.agent import AgentProfile
from synthetic_socio_wind_tunnel.agent.population import (
    LANE_COVE_PROFILE,
    _fill_archetype_identities,
    _render_template,
    sample_population,
)
from synthetic_socio_wind_tunnel.data_loader import (
    ArchetypeRecord,
    load_archetypes,
    match_archetype,
)


def _arch(
    arch_id: str = "test_arch",
    *,
    age_min: int = 30,
    age_max: int = 50,
    housing_tenure: str | list | None = "owner_occupier",
    work_mode: str | list | None = "commute",
    extra_criteria: dict | None = None,
    template: str = "{name} 是 {age} 岁的 {occupation}",
) -> ArchetypeRecord:
    crit: dict = {
        "age_bracket_min": age_min,
        "age_bracket_max": age_max,
    }
    if housing_tenure:
        crit["housing_tenure"] = housing_tenure
    if work_mode:
        crit["work_mode"] = work_mode
    if extra_criteria:
        crit.update(extra_criteria)
    return ArchetypeRecord(
        archetype_id=arch_id,
        label="Test",
        approx_pct=0.1,
        match_criteria=crit,
        personality_bias={},
        digital_bias={},
        occupation_pool=("test_occ",),
        interests_pool=("test_int",),
        identity_text_template=template,
        plan_text_template_examples=("Plan A.", "Plan B."),
        source_urls=(),
        uncertain=False,
    )


def _profile(**overrides) -> AgentProfile:
    base = dict(
        agent_id="test", name="Test", age=35, occupation="banker",
        household="couple", home_location="home",
        housing_tenure="owner_occupier", work_mode="commute",
        income_tier="high",
    )
    base.update(overrides)
    return AgentProfile(**base)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


class TestLoad:

    def test_load_default_archetypes(self):
        """The default lane cove archetypes file loads 7 records."""
        archs = load_archetypes()
        assert len(archs) == 7
        ids = {a.archetype_id for a in archs}
        assert "longtime_owner_occupier" in ids
        assert "primary_carer_parent" in ids

    def test_load_explicit_path(self, tmp_path: Path):
        payload = {
            "archetypes": [
                {
                    "archetype_id": "test_a",
                    "label": "Test A",
                    "approx_pct": 0.5,
                    "match_criteria": {
                        "age_bracket_min": 20,
                        "age_bracket_max": 30,
                    },
                    "personality_bias": {},
                    "digital_bias": {},
                    "occupation_pool": [],
                    "interests_pool": [],
                    "identity_text_template": "T",
                    "plan_text_template_examples": [],
                    "source_urls": [],
                }
            ]
        }
        p = tmp_path / "archs.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        archs = load_archetypes(p)
        assert len(archs) == 1
        assert archs[0].archetype_id == "test_a"

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_archetypes(tmp_path / "nope.json")

    def test_malformed_entry_skipped(self, tmp_path: Path):
        payload = {
            "archetypes": [
                {
                    "archetype_id": "ok", "label": "OK", "approx_pct": 0.1,
                    "match_criteria": {}, "personality_bias": {},
                    "digital_bias": {}, "occupation_pool": [],
                    "interests_pool": [], "identity_text_template": "",
                    "plan_text_template_examples": [], "source_urls": [],
                },
                {"label": "broken"},  # missing archetype_id
            ]
        }
        p = tmp_path / "a.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        archs = load_archetypes(p)
        assert len(archs) == 1
        assert archs[0].archetype_id == "ok"


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


class TestMatching:

    def test_age_out_of_range_vetoes(self):
        arch = _arch(age_min=30, age_max=50)
        p = _profile(age=20)  # Below min
        assert match_archetype(p, [arch]) is None

    def test_work_mode_mismatch_vetoes(self):
        """work_mode is a hard veto — mismatching work mode rules out
        the archetype regardless of how many other dims match."""
        arch = _arch(work_mode="commute", extra_criteria={
            "income_tier": "high",
            "family_composition": "couple_no_kids",
            "dwelling_structure": "separate_house",
        })
        # All non-work_mode criteria match BUT work_mode mismatches
        p = _profile(work_mode="remote", income_tier="high",
                     family_composition="couple_no_kids",
                     dwelling_structure="separate_house")
        assert match_archetype(p, [arch]) is None

    def test_housing_tenure_mismatch_vetoes(self):
        arch = _arch(housing_tenure="owner_occupier", work_mode="commute")
        p = _profile(housing_tenure="renter", work_mode="commute")
        assert match_archetype(p, [arch]) is None

    def test_explicit_mismatch_penalty(self):
        """Mismatched soft criteria reduce score (don't just leave at 0)."""
        arch = _arch(work_mode="commute", extra_criteria={
            "income_tier": "high",
            "education_level": "postgrad",
        })
        # work_mode match (+1), age match (+1), income mismatch (-1),
        # education mismatch (-1) → score = 0 → below threshold (2.0) → None
        p = _profile(work_mode="commute", income_tier="low",
                     education_level="year_12")
        assert match_archetype(p, [arch]) is None

    def test_match_when_score_high(self):
        arch = _arch(work_mode="commute", extra_criteria={
            "income_tier": "high",
            "family_composition": "couple_no_kids",
        })
        # age + work_mode + housing + income + family = +5
        p = _profile(work_mode="commute", income_tier="high",
                     family_composition="couple_no_kids")
        result = match_archetype(p, [arch])
        assert result is not None
        assert result.archetype_id == "test_arch"

    def test_unknown_field_no_change(self):
        """When profile has None for a criterion field, no penalty."""
        arch = _arch(work_mode="commute", extra_criteria={
            "income_tier": "high",
        })
        p = _profile(work_mode="commute", income_tier=None)
        # age + work_mode + housing = +3 ≥ 2 → match
        result = match_archetype(p, [arch])
        assert result is not None

    def test_no_archetypes_returns_none(self):
        assert match_archetype(_profile(), []) is None

    def test_real_archetypes_diverse_population(self):
        """End-to-end: sample 100 agents and check we get reasonable
        archetype distribution (not all matched, not none matched)."""
        archs = load_archetypes()
        small = LANE_COVE_PROFILE.model_copy(update={"size": 100})
        profiles = sample_population(small, seed=42, num_protagonists=0)
        matched = sum(
            1 for p in profiles if match_archetype(p, archs) is not None
        )
        # Expect 20-50% match rate for full LANE_COVE distribution
        # (rest are kids / edge ages)
        assert 15 <= matched <= 70, f"matched={matched} out of expected band"


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


class TestRender:

    def test_render_basic(self):
        arch = _arch(template="{name} is {age} years old, {occupation}")
        p = _profile(name="Emma", age=42, occupation="librarian")
        out = _render_template(p, arch)
        assert out == "Emma is 42 years old, librarian"

    def test_render_personality_descriptor_high_extra(self):
        from synthetic_socio_wind_tunnel.agent.personality import PersonalityTraits
        arch = _arch(template="{name}, {personality_descriptor}")
        p = _profile(personality=PersonalityTraits(
            extraversion=0.85, openness=0.5, conscientiousness=0.5,
            agreeableness=0.5, neuroticism=0.5, curiosity=0.5,
            routine_adherence=0.5, risk_tolerance=0.5,
        ))
        out = _render_template(p, arch)
        assert "外向" in out  # high extraversion → descriptor

    def test_render_with_chinese_template(self):
        archs = load_archetypes()
        owner = next(a for a in archs if a.archetype_id == "longtime_owner_occupier")
        p = _profile(
            name="Wang", age=65, occupation="retired",
            community_tenure_5yr="established_5plus",
        )
        out = _render_template(p, owner)
        assert "Wang" in out
        assert "65" in out
        assert "retired" in out
        # tenure_years map: established_5plus → "10"
        assert "10 年前" in out


# ---------------------------------------------------------------------------
# fill_archetype_identities (run-start template fill, deterministic)
# ---------------------------------------------------------------------------


class TestFillIdentities:

    def test_fill_real_population(self):
        archs = load_archetypes()
        small = LANE_COVE_PROFILE.model_copy(update={"size": 30})
        profiles = sample_population(small, seed=42, num_protagonists=2)
        rng = random.Random(42)
        filled = _fill_archetype_identities(profiles, archs, rng)
        # All filled profiles should still be 30
        assert len(filled) == 30
        # At least some should have non-None identity_text
        with_id = sum(1 for p in filled if p.identity_text)
        assert with_id >= 5
        # Filled identity should reference name
        for p in filled:
            if p.identity_text:
                assert p.name in p.identity_text

    def test_fill_no_archetypes_does_nothing(self):
        small = LANE_COVE_PROFILE.model_copy(update={"size": 5})
        profiles = sample_population(small, seed=42, num_protagonists=0)
        rng = random.Random(42)
        out = _fill_archetype_identities(profiles, [], rng)
        # All should be unchanged (identity_text still None)
        for p in out:
            assert p.identity_text is None


# ---------------------------------------------------------------------------
# Sample-time integration: protag with archetype-grounded LLM call
# ---------------------------------------------------------------------------


class _StubLLM:
    """Returns archetype-aware fixed response."""

    def __init__(self, response: str | None = None) -> None:
        self.response = response or json.dumps({
            "identity": "ARCHETYPE-GROUNDED ANSWER", "plan": "today: do X",
        })
        self.calls: list[str] = []

    async def generate(self, prompt: str, *, model: str = "", **kw) -> str:
        self.calls.append(prompt)
        return self.response


class TestProtagIntegration:

    def test_protag_prompt_mentions_archetype(self):
        """sample_population with generate_identity should include
        archetype label in the protag's LLM prompt."""
        small = LANE_COVE_PROFILE.model_copy(update={"size": 40})
        llm = _StubLLM()
        profiles = sample_population(
            small, seed=42, num_protagonists=3,
            generate_identity=True, llm_client=llm,
        )
        protag_with_arch = [
            p for p in profiles if p.is_protagonist
            and p.identity_text and "ARCHETYPE-GROUNDED" in p.identity_text
        ]
        # Some protag should have the LLM-grounded identity (those that
        # got matched to an archetype). The rest fall back to free-form
        # which the stub LLM also covers (same response).
        assert len(protag_with_arch) >= 1
        # Some prompt should reference archetype
        archetype_aware_prompts = [c for c in llm.calls if "archetype" in c.lower()]
        assert len(archetype_aware_prompts) >= 1

    def test_scripted_get_template_filled_when_matched(self):
        """Even non-protag scripted agents should get an archetype
        template-filled identity_text when they match an archetype."""
        small = LANE_COVE_PROFILE.model_copy(update={"size": 50})
        llm = _StubLLM()
        profiles = sample_population(
            small, seed=42, num_protagonists=2,
            generate_identity=True, llm_client=llm,
        )
        scripted_with_id = [
            p for p in profiles if not p.is_protagonist and p.identity_text
        ]
        # At least 5 scripted should have archetype-template identity
        assert len(scripted_with_id) >= 5
        # Their identity should contain the agent name
        for p in scripted_with_id[:5]:
            assert p.name in p.identity_text
