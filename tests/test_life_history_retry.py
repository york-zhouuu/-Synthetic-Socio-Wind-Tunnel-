"""Tests for life_history retry + prompt v2 + fallback path.

Covers the ABCD refinement done in setup-content-cache:
- A. n_records default 20
- B. tier hint passed through (caller's responsibility)
- C. retry on transient failure (2 attempts default)
- D. prompt_version v2 vs v1 — v2 includes NEIGHBORHOOD_LANDMARKS + home_location

Existing test_lanecove_life_history.py covers the success/non-retry paths;
this file focuses on the new retry + prompt versioning paths.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from synthetic_socio_wind_tunnel.agent import AgentProfile
from synthetic_socio_wind_tunnel.data_loader.lanecove import (
    NEIGHBORHOOD_LANDMARKS,
    _LIFE_HISTORY_PROMPT_TEMPLATES,
    _fallback_template_life_history,
    _generate_life_history_for_one,
    generate_life_history_for_protagonists,
)


def _profile(agent_id: str = "emma", *, protag: bool = True, **overrides) -> AgentProfile:
    base = dict(
        agent_id=agent_id, name=agent_id.title(), age=32,
        occupation="librarian", household="single",
        home_location=f"home_{agent_id}",
        is_protagonist=protag,
        identity_text="",
        plan_text="",
    )
    base.update(overrides)
    return AgentProfile(**base)


_GOOD_JSON_RESPONSE = json.dumps([
    {
        "title": f"事件 {i}",
        "content": f"我 {i}. 在 Lane Cove Plaza 经历过这事。",
        "years_ago": float(i) + 0.5,
        "location_hint": "Lane Cove Plaza",
        "importance": 0.5,
        "tags": ["test"],
    }
    for i in range(20)
])


class _ScriptedLLM:
    """LLM stub returning a programmed sequence of responses or exceptions."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def generate(self, prompt, **kw):
        self.calls.append(prompt)
        if not self.script:
            raise RuntimeError("script exhausted")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


# ---------------------------------------------------------------------------
# C. retry path
# ---------------------------------------------------------------------------


class TestRetryPath:

    def test_first_call_fails_then_succeeds(self):
        """Single transient failure → retry succeeds → records returned."""
        llm = _ScriptedLLM([
            RuntimeError("transient"),
            _GOOD_JSON_RESPONSE,
        ])
        recs = asyncio.run(_generate_life_history_for_one(
            _profile("emma"),
            llm_client=llm, archetype=None,
            max_retries=2, prompt_version="v2",
        ))
        assert len(recs) == 20
        assert len(llm.calls) == 2

    def test_unparseable_then_succeeds(self):
        """Bad JSON → retry → good JSON → records returned."""
        llm = _ScriptedLLM([
            "not json at all",
            _GOOD_JSON_RESPONSE,
        ])
        recs = asyncio.run(_generate_life_history_for_one(
            _profile("emma"),
            llm_client=llm, archetype=None,
            max_retries=2, prompt_version="v2",
        ))
        assert len(recs) == 20
        assert len(llm.calls) == 2

    def test_exhausts_retries_returns_empty(self):
        """max_retries=2 → 3 attempts total → all fail → empty list."""
        llm = _ScriptedLLM([
            RuntimeError("attempt 1"),
            RuntimeError("attempt 2"),
            RuntimeError("attempt 3"),
        ])
        recs = asyncio.run(_generate_life_history_for_one(
            _profile("emma"),
            llm_client=llm, archetype=None,
            max_retries=2, prompt_version="v2",
        ))
        assert recs == []
        assert len(llm.calls) == 3  # 1 initial + 2 retries

    def test_max_retries_zero_means_one_attempt(self):
        """max_retries=0 → exactly 1 attempt total."""
        llm = _ScriptedLLM([RuntimeError("boom")])
        recs = asyncio.run(_generate_life_history_for_one(
            _profile("emma"),
            llm_client=llm, archetype=None,
            max_retries=0, prompt_version="v2",
        ))
        assert recs == []
        assert len(llm.calls) == 1


# ---------------------------------------------------------------------------
# D. prompt versioning
# ---------------------------------------------------------------------------


class TestPromptVersioning:

    def test_v2_includes_landmarks_in_prompt(self):
        """v2 prompt SHALL include NEIGHBORHOOD_LANDMARKS list."""
        llm = _ScriptedLLM([_GOOD_JSON_RESPONSE])
        asyncio.run(_generate_life_history_for_one(
            _profile("emma"),
            llm_client=llm, archetype=None,
            max_retries=0, prompt_version="v2",
        ))
        prompt = llm.calls[0]
        # At least one landmark should appear in v2 prompt
        found = sum(1 for lm in NEIGHBORHOOD_LANDMARKS if lm in prompt)
        assert found >= 3, f"expected ≥3 landmarks in v2 prompt, found {found}"

    def test_v1_prompt_template_exists(self):
        """v1 still available for backward compat."""
        assert "v1" in _LIFE_HISTORY_PROMPT_TEMPLATES
        assert "v2" in _LIFE_HISTORY_PROMPT_TEMPLATES

    def test_unknown_prompt_version_raises(self):
        with pytest.raises(ValueError, match="prompt_version"):
            asyncio.run(_generate_life_history_for_one(
                _profile("emma"),
                llm_client=_ScriptedLLM([]),
                archetype=None,
                prompt_version="v99",
            ))

    def test_v2_includes_home_location(self):
        """v2 prompt SHALL inject profile.home_location."""
        llm = _ScriptedLLM([_GOOD_JSON_RESPONSE])
        asyncio.run(_generate_life_history_for_one(
            _profile("emma", home_location="lc_residential_42_special"),
            llm_client=llm, archetype=None,
            max_retries=0, prompt_version="v2",
        ))
        assert "lc_residential_42_special" in llm.calls[0]


# ---------------------------------------------------------------------------
# Batch wrapper retry threading
# ---------------------------------------------------------------------------


class TestBatchWrapperThreadsRetry:

    def test_batch_wrapper_passes_max_retries(self):
        """generate_life_history_for_protagonists threads max_retries
        through to _generate_life_history_for_one."""
        llm = _ScriptedLLM([
            RuntimeError("first attempt"),
            _GOOD_JSON_RESPONSE,
        ])
        result, failed = asyncio.run(generate_life_history_for_protagonists(
            [_profile("emma", protag=True)],
            llm_client=llm,
            archetypes=None,
            max_retries=2,
            prompt_version="v2",
        ))
        assert "emma" in result
        assert len(result["emma"]) == 20
        assert failed == []

    def test_batch_wrapper_passes_n_records_default_20(self):
        """Default n_records_per_protag SHALL be 20 (setup-content-cache upgrade)."""
        llm = _ScriptedLLM([_GOOD_JSON_RESPONSE])
        result, _ = asyncio.run(generate_life_history_for_protagonists(
            [_profile("emma", protag=True)],
            llm_client=llm,
            archetypes=None,
        ))
        # Should be 20 (from GOOD_JSON_RESPONSE which is also 20-length)
        assert len(result["emma"]) == 20

    def test_failed_protag_tracked(self):
        """failed_protag list SHALL contain agent_ids whose LLM exhausted retries."""
        # LLM fails for both protag (no responses)
        llm = _ScriptedLLM([
            RuntimeError("a"), RuntimeError("a"), RuntimeError("a"),
            RuntimeError("b"), RuntimeError("b"), RuntimeError("b"),
        ])
        result, failed = asyncio.run(generate_life_history_for_protagonists(
            [_profile("emma", protag=True), _profile("linda", protag=True)],
            llm_client=llm,
            archetypes=None,
            max_retries=2,
            fallback_to_template=False,
        ))
        assert set(failed) == {"emma", "linda"}
        assert result["emma"] == []
        assert result["linda"] == []


# ---------------------------------------------------------------------------
# Fallback template path
# ---------------------------------------------------------------------------


class TestFallbackTemplate:

    def test_fallback_returns_n_records(self):
        """_fallback_template_life_history SHALL return up to n records."""
        recs = _fallback_template_life_history(_profile("emma"), None, n=20)
        assert len(recs) > 0
        assert all(r.agent_id == "emma" for r in recs)
        assert all("fallback_template" in r.tags for r in recs)

    def test_fallback_records_have_required_fields(self):
        recs = _fallback_template_life_history(_profile("emma"), None, n=5)
        for r in recs:
            assert r.title
            assert r.content
            assert 0.5 <= r.years_ago <= 15.0
            assert 0.0 <= r.importance <= 1.0

    def test_batch_wrapper_substitutes_fallback_when_enabled(self):
        """fallback_to_template=True SHALL replace empty result with templates."""
        llm = _ScriptedLLM([
            RuntimeError("a"), RuntimeError("a"), RuntimeError("a"),
        ])
        result, failed = asyncio.run(generate_life_history_for_protagonists(
            [_profile("emma", protag=True)],
            llm_client=llm,
            archetypes=None,
            max_retries=2,
            fallback_to_template=True,
        ))
        assert "emma" in failed
        assert len(result["emma"]) > 0
        assert all("fallback_template" in r.tags for r in result["emma"])
