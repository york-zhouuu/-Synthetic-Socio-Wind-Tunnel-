"""Tests for synthetic_socio_wind_tunnel.data_loader.lanecove."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from synthetic_socio_wind_tunnel.agent import AgentProfile
from synthetic_socio_wind_tunnel.data_loader import (
    SharedMemoryRecord,
    inject_shared_memories_for_protagonists,
    inject_shared_memories_into_agent,
    load_shared_memories,
)
from synthetic_socio_wind_tunnel.memory.service import MemoryService


def _profile(agent_id: str, *, protag: bool = True) -> AgentProfile:
    return AgentProfile(
        agent_id=agent_id, name=agent_id.title(), age=30,
        occupation="librarian", household="single",
        home_location=f"home_{agent_id}",
        is_protagonist=protag,
    )


def _record(
    rid: str = "test_001",
    *,
    salience: float = 0.7,
    uncertain: bool = False,
    year: int = 2024,
) -> SharedMemoryRecord:
    return SharedMemoryRecord(
        id=rid,
        title=f"事件 {rid}",
        content=f"测试内容 {rid}",
        year=year,
        category="event",
        salience=salience,
        source_urls=("https://example.com/x",),
        tags=("test",),
        uncertain=uncertain,
    )


# ---------------------------------------------------------------------------
# load_shared_memories
# ---------------------------------------------------------------------------


class TestLoad:

    def test_loads_default_lanecove_file(self):
        recs = load_shared_memories()
        # Compiled with 12 entries; never less in this branch
        assert len(recs) == 12
        # All ids unique, non-empty
        ids = [r.id for r in recs]
        assert len(set(ids)) == 12
        # Sorted by descending salience
        sals = [r.salience for r in recs]
        assert sals == sorted(sals, reverse=True)

    def test_loads_explicit_path(self, tmp_path: Path):
        payload = {
            "_meta": {"schema_version": 1},
            "memories": [
                {
                    "id": "x_001", "title": "T", "content": "C",
                    "year": 2023, "category": "event",
                    "salience": 0.5,
                    "source_urls": ["https://example.com"],
                    "tags": ["t"], "uncertain": False,
                }
            ],
        }
        p = tmp_path / "smem.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        recs = load_shared_memories(p)
        assert len(recs) == 1
        assert recs[0].id == "x_001"

    def test_missing_file_raises(self, tmp_path: Path):
        p = tmp_path / "absent.json"
        with pytest.raises(FileNotFoundError):
            load_shared_memories(p)

    def test_malformed_entry_skipped_not_raised(self, tmp_path: Path):
        payload = {
            "memories": [
                {"id": "ok", "title": "T", "content": "C",
                 "year": 2023, "category": "x", "salience": 0.5,
                 "source_urls": [], "tags": []},
                # Missing required keys → should be skipped
                {"title": "broken"},
                # bad type for year
                {"id": "bad2", "title": "T", "content": "C",
                 "year": "not_a_year", "category": "x",
                 "salience": 0.5, "source_urls": [], "tags": []},
            ],
        }
        p = tmp_path / "smem.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        recs = load_shared_memories(p)
        # Only the first one survives
        assert len(recs) == 1
        assert recs[0].id == "ok"

    def test_salience_clamped(self, tmp_path: Path):
        payload = {
            "memories": [
                {"id": "high", "title": "T", "content": "C",
                 "year": 2024, "category": "x", "salience": 1.5,
                 "source_urls": [], "tags": []},
                {"id": "low", "title": "T", "content": "C",
                 "year": 2024, "category": "x", "salience": -0.2,
                 "source_urls": [], "tags": []},
            ],
        }
        p = tmp_path / "smem.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        recs = load_shared_memories(p)
        sals = {r.id: r.salience for r in recs}
        assert sals["high"] == 1.0
        assert sals["low"] == 0.0


# ---------------------------------------------------------------------------
# inject_shared_memories_into_agent
# ---------------------------------------------------------------------------


class TestInjectAgent:

    def test_writes_one_event_per_record(self):
        msvc = MemoryService()
        recs = [_record("a"), _record("b"), _record("c")]
        n = inject_shared_memories_into_agent(
            "emma", recs, memory_service=msvc,
        )
        assert n == 3
        events = msvc.all_for("emma")
        assert len(events) == 3
        for ev in events:
            assert ev.kind == "shared_memory"
            assert ev.tick == -1
            assert ev.day_index == -1
            assert ev.urgency == 0.0
            assert ev.importance == 0.7
            assert "event" in ev.tags  # category
            assert "test" in ev.tags

    def test_event_id_deterministic(self):
        msvc = MemoryService()
        recs = [_record("alpha")]
        inject_shared_memories_into_agent(
            "emma", recs, memory_service=msvc,
        )
        events = msvc.all_for("emma")
        assert events[0].event_id == "shared_alpha_emma"

    def test_idempotent(self):
        """Calling twice does not double-write."""
        msvc = MemoryService()
        recs = [_record("a"), _record("b")]
        inject_shared_memories_into_agent("emma", recs, memory_service=msvc)
        n2 = inject_shared_memories_into_agent(
            "emma", recs, memory_service=msvc,
        )
        assert n2 == 0  # nothing new written
        assert len(msvc.all_for("emma")) == 2

    def test_skip_uncertain(self):
        msvc = MemoryService()
        recs = [
            _record("certain"),
            _record("doubtful", uncertain=True),
        ]
        n = inject_shared_memories_into_agent(
            "emma", recs, memory_service=msvc, skip_uncertain=True,
        )
        assert n == 1
        ids = {ev.event_id for ev in msvc.all_for("emma")}
        assert "shared_certain_emma" in ids
        assert "shared_doubtful_emma" not in ids

    def test_simulated_time_anchored_to_year(self):
        msvc = MemoryService()
        rec = _record("y2021", year=2021)
        inject_shared_memories_into_agent(
            "emma", [rec], memory_service=msvc,
        )
        ev = msvc.all_for("emma")[0]
        assert ev.simulated_time.year == 2021
        assert ev.simulated_time.month == 7  # mid-year stable anchor

    def test_importance_passes_through_salience(self):
        msvc = MemoryService()
        recs = [_record("hi", salience=0.95), _record("lo", salience=0.2)]
        inject_shared_memories_into_agent(
            "emma", recs, memory_service=msvc,
        )
        by_id = {ev.event_id: ev.importance for ev in msvc.all_for("emma")}
        assert by_id["shared_hi_emma"] == pytest.approx(0.95)
        assert by_id["shared_lo_emma"] == pytest.approx(0.2)


# ---------------------------------------------------------------------------
# inject_shared_memories_for_protagonists
# ---------------------------------------------------------------------------


class TestInjectAll:

    def test_only_protagonists_get_injected(self):
        msvc = MemoryService()
        profiles = [
            _profile("emma", protag=True),
            _profile("linda", protag=True),
            _profile("bob", protag=False),  # scripted
        ]
        recs = [_record("a"), _record("b")]
        out = inject_shared_memories_for_protagonists(
            profiles, recs, memory_service=msvc,
        )
        assert out == {"emma": 2, "linda": 2}
        assert len(msvc.all_for("emma")) == 2
        assert len(msvc.all_for("linda")) == 2
        assert msvc.all_for("bob") == []  # scripted untouched

    def test_idempotent_across_protagonists(self):
        msvc = MemoryService()
        profiles = [_profile("emma"), _profile("linda")]
        recs = [_record("a")]
        inject_shared_memories_for_protagonists(
            profiles, recs, memory_service=msvc,
        )
        out2 = inject_shared_memories_for_protagonists(
            profiles, recs, memory_service=msvc,
        )
        assert out2 == {"emma": 0, "linda": 0}

    def test_loaded_dataset_e2e(self):
        """Use the real dataset; verify end-to-end coherence."""
        recs = load_shared_memories()
        msvc = MemoryService()
        profiles = [_profile("emma"), _profile("linda")]
        out = inject_shared_memories_for_protagonists(
            profiles, recs, memory_service=msvc,
        )
        assert out["emma"] == 12
        assert out["linda"] == 12
        # Each protagonist's events all kind="shared_memory"
        for aid in ("emma", "linda"):
            kinds = {ev.kind for ev in msvc.all_for(aid)}
            assert kinds == {"shared_memory"}

    def test_skip_uncertain_propagates(self):
        msvc = MemoryService()
        profiles = [_profile("emma")]
        recs = [
            _record("certain"),
            _record("doubt1", uncertain=True),
            _record("doubt2", uncertain=True),
        ]
        out = inject_shared_memories_for_protagonists(
            profiles, recs, memory_service=msvc, skip_uncertain=True,
        )
        assert out["emma"] == 1


# ---------------------------------------------------------------------------
# Integration: shared memories surface in retrieval
# ---------------------------------------------------------------------------


class TestRetrievalIntegration:
    """A protagonist seeded with shared memories should retrieve them when
    queried by category tag — confirming the events are indexable just
    like normal action/encounter events."""

    def test_retrieve_by_kind(self):
        from synthetic_socio_wind_tunnel.memory.models import MemoryQuery
        msvc = MemoryService()
        recs = load_shared_memories()
        inject_shared_memories_into_agent(
            "emma", recs, memory_service=msvc,
        )
        results = msvc.retrieve(
            "emma", MemoryQuery(kind="shared_memory"), top_k=20,
        )
        assert len(results) == 12

    def test_retrieve_by_tag(self):
        from synthetic_socio_wind_tunnel.memory.models import MemoryQuery
        msvc = MemoryService()
        recs = load_shared_memories()
        inject_shared_memories_into_agent(
            "emma", recs, memory_service=msvc,
        )
        # Lane Cove dataset has multiple "infrastructure" category memories
        results = msvc.retrieve(
            "emma", MemoryQuery(tags=("infrastructure",)), top_k=20,
        )
        # At least the 4 infrastructure-tagged Lane Cove events
        assert len(results) >= 4
        for r in results:
            assert "infrastructure" in r.tags
