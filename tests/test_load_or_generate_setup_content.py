"""Tests for tools.run_variant_suite._load_or_generate_setup_content.

Covers the cache HIT (zero LLM) and MISS (online + persist) paths."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import pytest

from synthetic_socio_wind_tunnel.agent import AgentProfile
from synthetic_socio_wind_tunnel.data_loader import (
    SimulationContentCache,
    save_setup_cache,
)
from tools.run_variant_suite import _load_or_generate_setup_content


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


class _CountingLLM:
    """Tracks how many LLM calls were made; raises if asked when not expected."""

    def __init__(self, response_text: str | None = None):
        self.calls = 0
        self.response = response_text or json.dumps([
            {
                "title": f"事件 {i}",
                "content": f"内容 {i}",
                "years_ago": float(i),
                "location_hint": None,
                "importance": 0.5,
                "tags": [],
            } for i in range(1, 21)
        ])

    async def generate(self, prompt, **kw):
        self.calls += 1
        return self.response


class TestCacheHit:

    def test_cache_hit_returns_zero_llm_call(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """When cache HIT, the LLM SHALL NOT be called."""
        # Pre-populate cache with both life_history + identity_text for emma
        cache = SimulationContentCache(
            seed=42,
            generated_at=datetime(2026, 5, 16, 22, 0, 0),
            generator={"tier": "sonnet"},
            life_history={
                "emma": [
                    {
                        "record_id": "lh_emma_01", "agent_id": "emma",
                        "title": "搬家", "content": "我搬来了 Lane Cove。",
                        "years_ago": 3.0, "location_hint": "Lane Cove",
                        "importance": 0.8, "tags": ["move"],
                    },
                ],
            },
            identity_text={
                "emma": "我是 Emma，32 岁，住 Lane Cove。",
            },
            failed_protag=[],
        )
        save_setup_cache(42, cache, cache_dir=tmp_path)

        # Patch the load_setup_cache caller to use tmp_path
        import tools.run_variant_suite as suite_mod
        from synthetic_socio_wind_tunnel.data_loader import setup_cache as cache_mod
        monkeypatch.setattr(
            cache_mod, "_default_cache_dir", lambda: tmp_path,
        )

        llm = _CountingLLM()
        history, identity, hit = asyncio.run(_load_or_generate_setup_content(
            seed=42,
            profiles=[_profile("emma", protag=True)],
            llm_client=llm,
            archetypes=[],
        ))
        assert hit is True
        assert llm.calls == 0
        assert "emma" in history
        assert len(history["emma"]) == 1
        assert history["emma"][0].title == "搬家"
        assert identity["emma"] == "我是 Emma，32 岁，住 Lane Cove。"

    def test_partial_cache_treated_as_miss(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """If cache only has emma but profiles have emma + linda → MISS."""
        cache = SimulationContentCache(
            seed=42,
            generated_at=datetime(2026, 5, 16, 22, 0, 0),
            generator={"tier": "sonnet"},
            life_history={
                "emma": [{
                    "record_id": "lh_emma_01", "agent_id": "emma",
                    "title": "搬家", "content": "c", "years_ago": 1.0,
                    "location_hint": None, "importance": 0.5, "tags": [],
                }],
            },
            identity_text={"emma": "我是 Emma."},
            failed_protag=[],
        )
        save_setup_cache(42, cache, cache_dir=tmp_path)

        from synthetic_socio_wind_tunnel.data_loader import setup_cache as cache_mod
        monkeypatch.setattr(
            cache_mod, "_default_cache_dir", lambda: tmp_path,
        )

        llm = _CountingLLM()
        history, identity, hit = asyncio.run(_load_or_generate_setup_content(
            seed=42,
            profiles=[
                _profile("emma", protag=True),
                _profile("linda", protag=True),
            ],
            llm_client=llm,
            archetypes=[],
        ))
        assert hit is False
        # Live generation should have happened
        assert llm.calls > 0


class TestCacheMiss:

    def test_cache_miss_generates_and_writes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """Cache MISS path: generates via LLM and writes cache file."""
        from synthetic_socio_wind_tunnel.data_loader import setup_cache as cache_mod
        monkeypatch.setattr(
            cache_mod, "_default_cache_dir", lambda: tmp_path,
        )

        llm = _CountingLLM()
        history, identity, hit = asyncio.run(_load_or_generate_setup_content(
            seed=99,
            profiles=[_profile("emma", protag=True)],
            llm_client=llm,
            archetypes=[],
        ))
        assert hit is False
        assert llm.calls >= 2  # at least life_history + identity_text
        assert "emma" in history
        assert "emma" in identity

        # Cache file written
        cache_path = tmp_path / "seed_99.json"
        assert cache_path.exists()
        payload = json.loads(cache_path.read_text())
        assert payload["seed"] == 99
        assert "emma" in payload["life_history"]
        assert "emma" in payload["identity_text"]

    def test_non_protag_skipped_from_generation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """Non-protag agents SHALL NOT trigger LLM calls."""
        from synthetic_socio_wind_tunnel.data_loader import setup_cache as cache_mod
        monkeypatch.setattr(
            cache_mod, "_default_cache_dir", lambda: tmp_path,
        )

        llm = _CountingLLM()
        history, identity, hit = asyncio.run(_load_or_generate_setup_content(
            seed=77,
            profiles=[
                _profile("emma", protag=True),
                _profile("scripted_a", protag=False),
            ],
            llm_client=llm,
            archetypes=[],
        ))
        assert "scripted_a" not in history
        assert "scripted_a" not in identity
        # Only emma triggered calls (1 life + 1 identity = 2)
        assert llm.calls == 2
