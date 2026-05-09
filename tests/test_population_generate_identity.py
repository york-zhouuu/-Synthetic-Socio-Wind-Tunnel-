"""Tests for sample_population's generate_identity / llm_client params
(agent-stack-aitown-port Phase D task 16)."""

from __future__ import annotations

import asyncio
import json

import pytest

from synthetic_socio_wind_tunnel.agent.population import (
    LANE_COVE_PROFILE,
    PopulationProfile,
    generate_identities_for_protagonists,
    sample_population,
)


class _StubLLM:
    """In-memory deterministic-ish LLM stub.

    `responses` indexed by call order. If a response is None it raises.
    """

    def __init__(self, responses: list[str | None]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    async def generate(self, prompt: str, *, model: str = "", **kw) -> str:
        self.calls.append(prompt)
        if not self._responses:
            return json.dumps({"identity": "default", "plan": "default plan"})
        nxt = self._responses.pop(0)
        if nxt is None:
            raise RuntimeError("LLM down")
        return nxt


def _small_profile(size: int = 4) -> PopulationProfile:
    """Trim Lane Cove to a smaller size for fast tests."""
    return LANE_COVE_PROFILE.model_copy(update={"size": size})


# ---------------------------------------------------------------------------
# Backwards compat: generate_identity=False (default) → identity stays None
# ---------------------------------------------------------------------------


class TestSamplePopulationBackwardsCompat:

    def test_default_no_llm_no_identity(self):
        profile = _small_profile(size=3)
        profiles = sample_population(profile, seed=42, num_protagonists=1)
        for p in profiles:
            assert p.identity_text is None
            assert p.plan_text is None

    def test_generate_identity_requires_llm(self):
        profile = _small_profile(size=3)
        with pytest.raises(ValueError, match="requires llm_client"):
            sample_population(
                profile, seed=42, num_protagonists=1,
                generate_identity=True,
                llm_client=None,
            )


# ---------------------------------------------------------------------------
# Happy path: LLM fills identity for protagonists only
# ---------------------------------------------------------------------------


class TestGenerateIdentities:

    def test_only_protagonists_get_llm_filled(self):
        """After Stage 1 (lane cove archetypes), scripted agents may also
        get archetype-template-filled identity_text (deterministic, no
        LLM). Only protagonists get LLM-driven creative variation. The
        `persona-{i}` LLM stub response should appear ONLY in protagonist
        identity, never in scripted identity."""
        profile = _small_profile(size=4)
        # Stub returns valid JSON for every call
        responses = [
            json.dumps({
                "identity": f"persona-{i}", "plan": f"plan-{i}",
            })
            for i in range(2)  # only 2 protagonists
        ]
        llm = _StubLLM(responses)

        profiles = sample_population(
            profile, seed=42, num_protagonists=2,
            generate_identity=True,
            llm_client=llm,
        )
        protag = [p for p in profiles if p.is_protagonist]
        scripted = [p for p in profiles if not p.is_protagonist]
        assert len(protag) == 2
        for p in protag:
            # Protag identity comes from LLM stub
            assert p.identity_text and p.identity_text.startswith("persona-")
            assert p.plan_text and p.plan_text.startswith("plan-")
        for p in scripted:
            # Scripted may have identity (from archetype template) but
            # NOT the LLM stub response.
            if p.identity_text is not None:
                assert not p.identity_text.startswith("persona-"), (
                    "scripted should never get LLM stub response"
                )
        # LLM called once per protagonist (not per scripted)
        assert len(llm.calls) == 2

    def test_async_helper_directly(self):
        profile = _small_profile(size=3)
        profiles = sample_population(profile, seed=42, num_protagonists=1)
        llm = _StubLLM([
            json.dumps({"identity": "Emma is curious.", "plan": "explore"}),
        ])
        out = asyncio.run(generate_identities_for_protagonists(
            profiles, llm_client=llm,
        ))
        protag = [p for p in out if p.is_protagonist][0]
        assert protag.identity_text == "Emma is curious."
        assert protag.plan_text == "explore"

    def test_empty_protagonists_no_op(self):
        profile = _small_profile(size=3)
        profiles = sample_population(profile, seed=42, num_protagonists=0)
        llm = _StubLLM([])
        out = asyncio.run(generate_identities_for_protagonists(
            profiles, llm_client=llm,
        ))
        assert out == profiles
        assert llm.calls == []


# ---------------------------------------------------------------------------
# Failure handling: LLM error / unparseable response → fallback
# ---------------------------------------------------------------------------


class TestIdentityFallback:

    def test_llm_exception_falls_back(self):
        profile = _small_profile(size=3)
        # 1 protagonist; LLM raises
        llm = _StubLLM([None])
        profiles = sample_population(
            profile, seed=42, num_protagonists=1,
            generate_identity=True, llm_client=llm,
        )
        protag = [p for p in profiles if p.is_protagonist][0]
        # fallback identity contains age + occupation
        assert protag.identity_text is not None
        assert str(protag.age) in protag.identity_text
        assert protag.occupation in protag.identity_text
        assert protag.plan_text is not None

    def test_unparseable_json_falls_back(self):
        profile = _small_profile(size=3)
        llm = _StubLLM(["not json at all 🚧"])
        profiles = sample_population(
            profile, seed=42, num_protagonists=1,
            generate_identity=True, llm_client=llm,
        )
        protag = [p for p in profiles if p.is_protagonist][0]
        assert protag.identity_text is not None
        assert "year-old" in protag.identity_text  # fallback text contains it

    def test_partial_json_missing_plan_falls_back(self):
        profile = _small_profile(size=3)
        llm = _StubLLM([json.dumps({"identity": "ok"})])  # no "plan"
        profiles = sample_population(
            profile, seed=42, num_protagonists=1,
            generate_identity=True, llm_client=llm,
        )
        protag = [p for p in profiles if p.is_protagonist][0]
        # Both fields fall back together (consistency rule)
        assert "year-old" in protag.identity_text
        assert protag.occupation in protag.plan_text

    def test_markdown_fenced_json_is_stripped(self):
        profile = _small_profile(size=3)
        llm = _StubLLM([
            '```json\n{"identity": "Sam likes books.", "plan": "read"}\n```',
        ])
        profiles = sample_population(
            profile, seed=42, num_protagonists=1,
            generate_identity=True, llm_client=llm,
        )
        protag = [p for p in profiles if p.is_protagonist][0]
        assert protag.identity_text == "Sam likes books."
        assert protag.plan_text == "read"


# ---------------------------------------------------------------------------
# Determinism: same seed + stub LLM → same identities
# ---------------------------------------------------------------------------


class TestDeterminism:

    def test_same_seed_same_protagonist_set(self):
        profile = _small_profile(size=5)
        # Reproducible LLM responses (stub returns by call order; population
        # ordering is seeded so call order is stable)
        responses1 = [
            json.dumps({"identity": f"p{i}", "plan": f"goal{i}"})
            for i in range(2)
        ]
        responses2 = list(responses1)  # fresh list, same content
        out1 = sample_population(
            profile, seed=42, num_protagonists=2,
            generate_identity=True, llm_client=_StubLLM(responses1),
        )
        out2 = sample_population(
            profile, seed=42, num_protagonists=2,
            generate_identity=True, llm_client=_StubLLM(responses2),
        )
        protag1 = [p.identity_text for p in out1 if p.is_protagonist]
        protag2 = [p.identity_text for p in out2 if p.is_protagonist]
        assert protag1 == protag2
