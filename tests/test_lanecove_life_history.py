"""Tests for Lane Cove per-protag life-history backstory generation + injection."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

import pytest

from synthetic_socio_wind_tunnel.agent import AgentProfile
from synthetic_socio_wind_tunnel.agent.population import (
    LANE_COVE_PROFILE,
    sample_population,
)
from synthetic_socio_wind_tunnel.data_loader import (
    LifeHistoryRecord,
    generate_life_history_for_protagonists,
    inject_life_history,
    load_archetypes,
)
from synthetic_socio_wind_tunnel.memory.service import MemoryService


_T0 = datetime(2026, 4, 22, 0, 0)


def _profile(agent_id: str = "emma", *, protag: bool = True, **overrides) -> AgentProfile:
    base = dict(
        agent_id=agent_id, name=agent_id.title(), age=32,
        occupation="librarian", household="single",
        home_location=f"home_{agent_id}",
        is_protagonist=protag,
        identity_text="Emma is a 32-year-old Lane Cove librarian.",
        plan_text="Find a quiet cafe today.",
    )
    base.update(overrides)
    return AgentProfile(**base)


class _StubLLM:
    """Returns canned LLM JSON for life history, optionally per-call list."""

    def __init__(self, responses: list[str] | str | None = None) -> None:
        if isinstance(responses, str):
            responses = [responses]
        self._responses = responses or [
            json.dumps([
                {
                    "title": f"事件 {i}",
                    "content": f"我 {i} 年前的一段经历。",
                    "years_ago": float(i),
                    "location_hint": "Lane Cove Plaza" if i % 2 == 0 else None,
                    "importance": 0.5,
                    "tags": ["test"],
                }
                for i in range(1, 11)  # 10 records
            ])
        ]
        self.calls: list[str] = []

    async def generate(self, prompt: str, *, model: str = "", **kw) -> str:
        self.calls.append(prompt)
        idx = min(len(self.calls) - 1, len(self._responses) - 1)
        return self._responses[idx]


# ---------------------------------------------------------------------------
# generate_life_history_for_protagonists — LLM batch
# ---------------------------------------------------------------------------


class TestGenerate:

    def test_only_protag_get_records(self):
        profiles = [
            _profile("emma", protag=True),
            _profile("linda", protag=True),
            _profile("scripted_a", protag=False),
        ]
        llm = _StubLLM()
        result = asyncio.run(generate_life_history_for_protagonists(
            profiles, llm_client=llm, n_records_per_protag=10,
        ))
        assert "emma" in result
        assert "linda" in result
        assert "scripted_a" not in result
        # 10 records each
        assert len(result["emma"]) == 10
        assert len(result["linda"]) == 10
        # LLM called once per protag
        assert len(llm.calls) == 2

    def test_record_fields_populated(self):
        profiles = [_profile("emma", protag=True)]
        llm = _StubLLM()
        result = asyncio.run(generate_life_history_for_protagonists(
            profiles, llm_client=llm,
        ))
        for rec in result["emma"]:
            assert rec.agent_id == "emma"
            assert rec.title.startswith("事件 ")
            assert rec.content.startswith("我 ")
            assert 0.5 <= rec.years_ago <= 15.0
            assert 0.0 <= rec.importance <= 1.0

    def test_archetype_passed_into_prompt(self):
        archs = load_archetypes()
        profiles = [_profile("emma", protag=True, age=63,
                             housing_tenure="owner_occupier",
                             work_mode="nonworking",
                             income_tier="mid",
                             community_tenure_5yr="established_5plus",
                             family_composition="couple_no_kids",
                             dwelling_structure="separate_house",
                             volunteer_status="volunteer",
                             education_level="bachelor")]
        llm = _StubLLM()
        asyncio.run(generate_life_history_for_protagonists(
            profiles, llm_client=llm, archetypes=archs,
        ))
        # Prompt should reference matched archetype
        prompt = llm.calls[0]
        assert "creative_retiree_volunteer" in prompt or "退休" in prompt

    def test_llm_failure_returns_empty(self):
        class _BoomLLM:
            async def generate(self, prompt, **kw):
                raise RuntimeError("LLM down")
        profiles = [_profile("emma", protag=True)]
        result = asyncio.run(generate_life_history_for_protagonists(
            profiles, llm_client=_BoomLLM(),
        ))
        assert result == {"emma": []}

    def test_unparseable_json_returns_empty(self):
        profiles = [_profile("emma", protag=True)]
        llm = _StubLLM(responses="not json at all")
        result = asyncio.run(generate_life_history_for_protagonists(
            profiles, llm_client=llm,
        ))
        assert result == {"emma": []}

    def test_markdown_fenced_json_stripped(self):
        profiles = [_profile("emma", protag=True)]
        fenced = '```json\n[' + json.dumps({
            "title": "fence test", "content": "我经历过一件事。",
            "years_ago": 2.0, "location_hint": None,
            "importance": 0.6, "tags": [],
        }) + ']\n```'
        llm = _StubLLM(responses=fenced)
        result = asyncio.run(generate_life_history_for_protagonists(
            profiles, llm_client=llm,
        ))
        assert len(result["emma"]) == 1
        assert result["emma"][0].title == "fence test"


# ---------------------------------------------------------------------------
# inject_life_history — write into MemoryService
# ---------------------------------------------------------------------------


class TestInject:

    def test_writes_one_event_per_record(self):
        msvc = MemoryService()
        recs = [
            LifeHistoryRecord(
                record_id=f"lh_emma_{i:02d}", agent_id="emma",
                title=f"事件 {i}", content=f"内容 {i}",
                years_ago=float(i), location_hint=None,
                importance=0.5, tags=("test",),
            )
            for i in range(10)
        ]
        n = inject_life_history(
            "emma", recs, memory_service=msvc, sim_start_time=_T0,
        )
        assert n == 10
        events = msvc.all_for("emma")
        assert len(events) == 10
        for ev in events:
            assert ev.kind == "life_history"
            assert ev.tick == -1
            assert ev.day_index == -1
            assert "life_history" in ev.tags
            assert "test" in ev.tags

    def test_simulated_time_anchored_in_past(self):
        msvc = MemoryService()
        rec = LifeHistoryRecord(
            record_id="lh_emma_5y", agent_id="emma",
            title="搬家", content="5 年前我搬来 Lane Cove。",
            years_ago=5.0, location_hint=None,
            importance=0.8, tags=(),
        )
        inject_life_history(
            "emma", [rec], memory_service=msvc, sim_start_time=_T0,
        )
        ev = msvc.all_for("emma")[0]
        # Should be ~5 years before _T0
        delta = _T0 - ev.simulated_time
        assert 1700 < delta.days < 2000  # 5 years ± a bit

    def test_idempotent(self):
        msvc = MemoryService()
        recs = [LifeHistoryRecord(
            record_id="lh_emma_only", agent_id="emma",
            title="t", content="c", years_ago=1.0,
            location_hint=None, importance=0.5, tags=(),
        )]
        inject_life_history(
            "emma", recs, memory_service=msvc, sim_start_time=_T0,
        )
        # Second call no-op
        n2 = inject_life_history(
            "emma", recs, memory_service=msvc, sim_start_time=_T0,
        )
        assert n2 == 0
        assert len(msvc.all_for("emma")) == 1

    def test_location_hint_persists(self):
        msvc = MemoryService()
        rec = LifeHistoryRecord(
            record_id="lh_loc", agent_id="emma",
            title="去 Plaza", content="第一次去 Lane Cove Plaza。",
            years_ago=3.0, location_hint="Lane Cove Plaza",
            importance=0.6, tags=(),
        )
        inject_life_history(
            "emma", [rec], memory_service=msvc, sim_start_time=_T0,
        )
        ev = msvc.all_for("emma")[0]
        assert ev.location_id == "Lane Cove Plaza"


# ---------------------------------------------------------------------------
# E2E: sample_population + life_history + retrieval
# ---------------------------------------------------------------------------


class TestE2EIntegration:

    def test_protag_can_retrieve_life_history(self):
        from synthetic_socio_wind_tunnel.memory.models import MemoryQuery

        small = LANE_COVE_PROFILE.model_copy(update={"size": 30})
        profiles = sample_population(small, seed=42, num_protagonists=2)
        # Generate via stub LLM
        llm = _StubLLM()
        result = asyncio.run(generate_life_history_for_protagonists(
            profiles, llm_client=llm,
        ))

        # Inject into MemoryService
        msvc = MemoryService()
        for agent_id, recs in result.items():
            inject_life_history(
                agent_id, recs, memory_service=msvc, sim_start_time=_T0,
            )

        # Retrieve by kind
        for agent_id in result:
            results = msvc.retrieve(
                agent_id, MemoryQuery(kind="life_history"), top_k=20,
            )
            assert len(results) == 10

    def test_invalid_record_skipped(self):
        """Items missing 'content' should be filtered out without crash."""
        bad_response = json.dumps([
            {"title": "ok", "content": "good 1", "years_ago": 1.0,
             "location_hint": None, "importance": 0.5, "tags": []},
            {"title": "missing content"},  # invalid
            {"title": "ok2", "content": "good 2", "years_ago": 2.0,
             "location_hint": None, "importance": 0.4, "tags": []},
        ])
        profiles = [_profile("emma", protag=True)]
        llm = _StubLLM(responses=bad_response)
        result = asyncio.run(generate_life_history_for_protagonists(
            profiles, llm_client=llm,
        ))
        # Only the 2 valid records survive
        assert len(result["emma"]) == 2
