"""Tests for PushPersonalizer — audience tag, relevance, content rendering."""

from __future__ import annotations

from datetime import datetime

import pytest

from synthetic_socio_wind_tunnel.agent import AgentProfile
from synthetic_socio_wind_tunnel.agent.personality import PersonalityTraits
from synthetic_socio_wind_tunnel.policy_hack import (
    PUSH_TEMPLATES,
    PushPersonalizer,
    PushTemplate,
)


def _profile(**overrides) -> AgentProfile:
    base = dict(
        agent_id="a", name="A", age=30, occupation="x",
        household="single", home_location="home",
        personality=PersonalityTraits(),
    )
    base.update(overrides)
    return AgentProfile(**base)


def _template(**overrides) -> PushTemplate:
    base = dict(
        template_id="t1", topic_id="hp_t1",
        base_content="{location} 本街活动",
        audience_variants={
            "parents": "{location} 亲子活动",
            "young_adult": "{location} 街角活动",
            "elderly": "{location} 适合长者的活动",
            "newcomer": "{location} 新邻居见面会",
            "default": "{location} 本街默认活动",
        },
        target_audience_tags=("parents",),
        base_salience=0.8,
    )
    base.update(overrides)
    return PushTemplate(**base)


class TestAudienceTagFor:

    def test_parents_tag_via_family_composition(self):
        p = _profile(family_composition="couple_kids_under_15", household="family_with_kids")
        assert PushPersonalizer.audience_tag_for(p) == "parents"

    def test_newcomer_tag_via_tenure(self):
        p = _profile(community_tenure_5yr="new_<1yr")
        assert PushPersonalizer.audience_tag_for(p) == "newcomer"

    def test_elderly_tag_via_age(self):
        p = _profile(age=70)
        assert PushPersonalizer.audience_tag_for(p) == "elderly"

    def test_elderly_tag_via_tenure(self):
        p = _profile(age=45, community_tenure_5yr="established_5plus")
        assert PushPersonalizer.audience_tag_for(p) == "elderly"

    def test_young_adult_tag(self):
        p = _profile(age=25, household="single")
        assert PushPersonalizer.audience_tag_for(p) == "young_adult"

    def test_default_tag_fallback(self):
        # 40-year-old, couple, no extra info → no special tag
        p = _profile(age=40, household="couple")
        assert PushPersonalizer.audience_tag_for(p) == "default"


class TestRelevance:

    def test_match_returns_one(self):
        p = _profile(age=25, household="single")  # young_adult
        t = _template(target_audience_tags=("young_adult",))
        assert PushPersonalizer.relevance(p, t) == 1.0

    def test_default_returns_06(self):
        p = _profile(age=40, household="couple")  # default
        t = _template(target_audience_tags=("parents",))  # not in target
        assert PushPersonalizer.relevance(p, t) == 0.6

    def test_mismatch_returns_03(self):
        p = _profile(age=70)  # elderly
        t = _template(target_audience_tags=("young_adult",))
        assert PushPersonalizer.relevance(p, t) == 0.3


class TestPersonalize:

    def test_different_profiles_get_different_content(self):
        t = _template()
        mom = _profile(family_composition="couple_kids_under_15", household="family_with_kids")
        elder = _profile(age=70)

        item_mom, _ = PushPersonalizer.personalize(
            t, mom, location="cafe_main", feed_item_id="f1",
            created_at=datetime(2026, 5, 8),
        )
        item_elder, _ = PushPersonalizer.personalize(
            t, elder, location="cafe_main", feed_item_id="f2",
            created_at=datetime(2026, 5, 8),
        )
        assert item_mom.content != item_elder.content
        assert "亲子" in item_mom.content
        assert "长者" in item_elder.content

    def test_relevance_affects_urgency(self):
        t = _template(target_audience_tags=("parents",))
        # parents → 1.0; mismatch → 0.3
        mom = _profile(family_composition="couple_kids_under_15", household="family_with_kids")
        elder = _profile(age=70)

        item_mom, rel_mom = PushPersonalizer.personalize(
            t, mom, location="X", feed_item_id="f1",
            created_at=datetime(2026, 5, 8), base_urgency=0.6,
        )
        item_elder, rel_elder = PushPersonalizer.personalize(
            t, elder, location="X", feed_item_id="f2",
            created_at=datetime(2026, 5, 8), base_urgency=0.6,
        )
        # 0.6 × (0.5 + 0.5 × 1.0) = 0.6
        assert item_mom.urgency == pytest.approx(0.6, abs=1e-3)
        # 0.6 × (0.5 + 0.5 × 0.3) = 0.39
        assert item_elder.urgency == pytest.approx(0.39, abs=1e-3)
        assert rel_mom == 1.0
        assert rel_elder == 0.3

    def test_topic_id_propagated(self):
        t = _template(topic_id="hp_event_42")
        p = _profile()
        item, _ = PushPersonalizer.personalize(
            t, p, location="X", feed_item_id="f",
            created_at=datetime(2026, 5, 8),
        )
        assert item.topic_id == "hp_event_42"
        assert item.target_audience_tags == ("parents",)

    def test_location_placeholder_replaced(self):
        t = _template()
        p = _profile()
        item, _ = PushPersonalizer.personalize(
            t, p, location="cafe_main", feed_item_id="f",
            created_at=datetime(2026, 5, 8),
        )
        assert "cafe_main" in item.content
        assert "{location}" not in item.content


class TestPresetPool:

    def test_preset_count_in_range(self):
        assert 5 <= len(PUSH_TEMPLATES) <= 12

    def test_each_preset_validates(self):
        # Re-construct each template; constructor validates
        for t in PUSH_TEMPLATES:
            assert "default" in t.audience_variants
            assert len(t.target_audience_tags) >= 1
            assert 0.6 <= t.base_salience <= 0.9

    def test_audience_tag_coverage(self):
        # All 5 audience tags should be reachable from at least one template's
        # target_audience_tags or audience_variants
        all_targets: set[str] = set()
        all_variants: set[str] = set()
        for t in PUSH_TEMPLATES:
            all_targets.update(t.target_audience_tags)
            all_variants.update(t.audience_variants.keys())
        # Variants should cover all 5 tags (each template should have all 5
        # variants per design D2 best practice)
        assert {"parents", "young_adult", "elderly", "newcomer", "default"} <= all_variants
