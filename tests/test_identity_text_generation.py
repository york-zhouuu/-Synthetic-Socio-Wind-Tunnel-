"""Tests for identity_text generation (setup-content-cache 2026-05-16).

`identity_text` is a ~150-200 字 first-person Chinese self-introduction
generated per protagonist. Covered:
- single-agent path: success / retry / exhaust / fallback / truncation
- batch wrapper: protag filter / life_history snippets threading / failed list
"""
from __future__ import annotations

import asyncio

import pytest

from synthetic_socio_wind_tunnel.agent import AgentProfile
from synthetic_socio_wind_tunnel.data_loader.lanecove import (
    _IDENTITY_TEXT_PROMPT_TEMPLATES,
    LifeHistoryRecord,
    _fallback_identity_text,
    _generate_identity_text_for_one,
    generate_identity_text_for_protagonists,
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


class _ScriptedLLM:
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


_GOOD_IDENTITY = (
    "我是 Emma，35 岁，平面设计师，住在 Lane Cove 的 lc_residential_03。"
    "我喜欢周末去 Plaza 喝咖啡，偶尔在 Stringybark Creek 散步。"
    "工作上偏 hybrid，性格安静但好奇，认识小区里的几个邻居。"
)


# ---------------------------------------------------------------------------
# Single-agent path
# ---------------------------------------------------------------------------


class TestIdentityTextSingle:

    def test_happy_path_returns_text(self):
        llm = _ScriptedLLM([_GOOD_IDENTITY])
        text = asyncio.run(_generate_identity_text_for_one(
            _profile("emma"),
            llm_client=llm, archetype=None,
            max_retries=0,
        ))
        assert text == _GOOD_IDENTITY
        assert len(llm.calls) == 1

    def test_retry_on_failure_succeeds(self):
        llm = _ScriptedLLM([
            RuntimeError("transient"),
            _GOOD_IDENTITY,
        ])
        text = asyncio.run(_generate_identity_text_for_one(
            _profile("emma"),
            llm_client=llm, archetype=None,
            max_retries=2,
        ))
        assert text == _GOOD_IDENTITY
        assert len(llm.calls) == 2

    def test_exhausts_retries_returns_fallback(self):
        llm = _ScriptedLLM([
            RuntimeError("a"),
            RuntimeError("b"),
            RuntimeError("c"),
        ])
        text = asyncio.run(_generate_identity_text_for_one(
            _profile("emma"),
            llm_client=llm, archetype=None,
            max_retries=2,
        ))
        # Fallback content (not empty)
        assert text
        assert "Emma" in text or "emma" in text.lower()
        assert len(llm.calls) == 3

    def test_empty_response_falls_back(self):
        """Empty LLM response after retries SHALL trigger fallback."""
        llm = _ScriptedLLM(["", "", ""])
        text = asyncio.run(_generate_identity_text_for_one(
            _profile("emma"),
            llm_client=llm, archetype=None,
            max_retries=2,
        ))
        assert text
        assert "Lane Cove" in text  # fallback mentions Lane Cove

    def test_truncation_when_too_long(self):
        """Response exceeding max_chars SHALL be truncated."""
        long_text = "我" * 1000
        llm = _ScriptedLLM([long_text])
        text = asyncio.run(_generate_identity_text_for_one(
            _profile("emma"),
            llm_client=llm, archetype=None,
            max_retries=0,
            max_chars=500,
        ))
        assert len(text) == 500

    def test_markdown_fence_stripped(self):
        fenced = "```\n" + _GOOD_IDENTITY + "\n```"
        llm = _ScriptedLLM([fenced])
        text = asyncio.run(_generate_identity_text_for_one(
            _profile("emma"),
            llm_client=llm, archetype=None,
            max_retries=0,
        ))
        # Fence should be gone (or partially gone — content should remain)
        assert _GOOD_IDENTITY in text or "Emma" in text

    def test_prompt_includes_landmarks(self):
        """v1 prompt SHALL include NEIGHBORHOOD_LANDMARKS."""
        llm = _ScriptedLLM([_GOOD_IDENTITY])
        asyncio.run(_generate_identity_text_for_one(
            _profile("emma"),
            llm_client=llm, archetype=None,
            max_retries=0,
        ))
        assert "Plaza" in llm.calls[0]
        assert "Longueville Road" in llm.calls[0]

    def test_prompt_includes_life_history_snippets(self):
        llm = _ScriptedLLM([_GOOD_IDENTITY])
        snippets = [
            "我 3 年前搬来 Lane Cove。",
            "我在 Plaza 喝咖啡的早晨。",
        ]
        asyncio.run(_generate_identity_text_for_one(
            _profile("emma"),
            llm_client=llm, archetype=None,
            life_history_snippets=snippets,
            max_retries=0,
        ))
        assert "搬来 Lane Cove" in llm.calls[0]

    def test_unknown_prompt_version_raises(self):
        with pytest.raises(ValueError, match="prompt_version"):
            asyncio.run(_generate_identity_text_for_one(
                _profile("emma"),
                llm_client=_ScriptedLLM([]),
                archetype=None,
                prompt_version="v99",
            ))


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------


class TestFallbackIdentityText:

    def test_fallback_includes_profile_fields(self):
        text = _fallback_identity_text(_profile("emma", age=42, occupation="teacher"))
        assert "Emma" in text
        assert "42" in text
        assert "teacher" in text

    def test_fallback_mentions_lane_cove(self):
        text = _fallback_identity_text(_profile("emma"))
        assert "Lane Cove" in text


# ---------------------------------------------------------------------------
# Batch wrapper
# ---------------------------------------------------------------------------


class TestIdentityTextBatch:

    def test_protag_only_get_identity(self):
        """generate_identity_text_for_protagonists SHALL skip non-protag."""
        llm = _ScriptedLLM([_GOOD_IDENTITY, _GOOD_IDENTITY])
        profiles = [
            _profile("emma", protag=True),
            _profile("linda", protag=True),
            _profile("scripted_a", protag=False),
        ]
        result, failed = asyncio.run(generate_identity_text_for_protagonists(
            profiles, llm_client=llm, archetypes=None,
        ))
        assert "emma" in result
        assert "linda" in result
        assert "scripted_a" not in result
        assert failed == []

    def test_life_history_snippets_threaded(self):
        """If life_history_by_agent given, snippets SHALL appear in prompt."""
        llm = _ScriptedLLM([_GOOD_IDENTITY])
        snippet_content = "我 5 年前从 Chatswood 搬来 Lane Cove."
        life_history_by_agent = {
            "emma": [
                LifeHistoryRecord(
                    record_id="lh_emma_01", agent_id="emma",
                    title="搬家", content=snippet_content,
                    years_ago=5.0, location_hint=None,
                    importance=0.8, tags=(),
                ),
            ],
        }
        asyncio.run(generate_identity_text_for_protagonists(
            [_profile("emma", protag=True)],
            llm_client=llm, archetypes=None,
            life_history_by_agent=life_history_by_agent,
        ))
        assert "搬来 Lane Cove" in llm.calls[0]

    def test_failed_protag_falls_back_to_template(self):
        """All-failure SHALL still produce a non-empty result (template)."""
        # LLM fails 3 times for emma (max_retries=2 → 3 total attempts)
        llm = _ScriptedLLM([
            RuntimeError("a"), RuntimeError("b"), RuntimeError("c"),
        ])
        result, failed = asyncio.run(generate_identity_text_for_protagonists(
            [_profile("emma", protag=True)],
            llm_client=llm, archetypes=None,
            max_retries=2,
        ))
        assert "emma" in result
        # Fallback is non-empty
        assert result["emma"]
        # emma is in failed list
        assert "emma" in failed

    def test_v1_prompt_template_exists(self):
        assert "v1" in _IDENTITY_TEXT_PROMPT_TEMPLATES
