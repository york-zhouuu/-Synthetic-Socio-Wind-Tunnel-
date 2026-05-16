"""Tests for synthetic_socio_wind_tunnel.data_loader.setup_cache."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest

from synthetic_socio_wind_tunnel.data_loader.setup_cache import (
    SimulationContentCache,
    is_cache_complete,
    load_setup_cache,
    save_setup_cache,
)


@dataclass
class MockProfile:
    agent_id: str
    is_protagonist: bool = True


def _make_cache(seed: int = 42, *, n_protag: int = 3) -> SimulationContentCache:
    return SimulationContentCache(
        seed=seed,
        generated_at=datetime(2026, 5, 16, 22, 0, 0),
        generator={
            "tier": "sonnet",
            "model": "deepseek-v4-pro",
            "n_records_per_protag": 20,
            "prompt_version": "v2",
            "concurrency": 4,
        },
        life_history={
            f"a_{seed}_{i:04d}": [
                {
                    "record_id": f"lh_{i}_{j}",
                    "agent_id": f"a_{seed}_{i:04d}",
                    "title": f"Title {j}",
                    "content": f"Content {j}",
                    "years_ago": 1.0,
                    "location_hint": "Lane Cove Plaza",
                    "importance": 0.5,
                    "tags": ["test"],
                }
                for j in range(20)
            ]
            for i in range(n_protag)
        },
        identity_text={
            f"a_{seed}_{i:04d}": f"我是 Test Agent {i}, 30 岁, 住 Lane Cove。"
            for i in range(n_protag)
        },
        failed_protag=[],
    )


class TestSimulationContentCache:

    def test_defaults_and_frozen(self) -> None:
        cache = _make_cache()
        assert cache.schema_version == "1"
        assert cache.seed == 42
        # frozen
        with pytest.raises(Exception):
            cache.seed = 99  # type: ignore[misc]

    def test_model_dump_json_safe(self) -> None:
        cache = _make_cache()
        s = json.dumps(cache.model_dump(mode="json"), ensure_ascii=False)
        assert "schema_version" in s
        assert "deepseek-v4-pro" in s


class TestSaveLoadRoundTrip:

    def test_save_load_round_trip(self, tmp_path: Path) -> None:
        cache = _make_cache()
        path = save_setup_cache(42, cache, cache_dir=tmp_path)
        assert path == tmp_path / "seed_42.json"
        assert path.exists()
        loaded = load_setup_cache(42, cache_dir=tmp_path)
        assert loaded is not None
        assert loaded.model_dump(mode="json") == cache.model_dump(mode="json")

    def test_atomic_no_tmp_residue(self, tmp_path: Path) -> None:
        cache = _make_cache()
        save_setup_cache(42, cache, cache_dir=tmp_path)
        assert list(tmp_path.glob("*.tmp")) == []

    def test_cleans_stale_tmp(self, tmp_path: Path) -> None:
        tmp_path.mkdir(exist_ok=True)
        stale = tmp_path / "seed_42.json.tmp"
        stale.write_text("garbage from prior failed write")
        assert stale.exists()
        cache = _make_cache()
        save_setup_cache(42, cache, cache_dir=tmp_path)
        assert not stale.exists()

    def test_save_seed_mismatch_raises(self, tmp_path: Path) -> None:
        cache = _make_cache(seed=42)
        with pytest.raises(ValueError):
            save_setup_cache(99, cache, cache_dir=tmp_path)


class TestLoadMissingOrInvalid:

    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        assert load_setup_cache(99, cache_dir=tmp_path) is None

    def test_load_incompatible_schema_returns_none(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        bad = tmp_path / "seed_42.json"
        bad.write_text(json.dumps({
            "schema_version": "99",
            "seed": 42,
            "generated_at": "2026-05-16T22:00:00",
            "generator": {},
            "life_history": {},
            "identity_text": {},
            "failed_protag": [],
        }))
        with caplog.at_level("WARNING"):
            result = load_setup_cache(42, cache_dir=tmp_path)
        assert result is None
        assert any("schema mismatch" in r.message for r in caplog.records)

    def test_load_corrupt_json_returns_none(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        bad = tmp_path / "seed_42.json"
        bad.write_text("{not valid json")
        with caplog.at_level("WARNING"):
            result = load_setup_cache(42, cache_dir=tmp_path)
        assert result is None


class TestIsCacheComplete:

    def test_complete(self) -> None:
        cache = _make_cache(n_protag=3)
        profiles = [MockProfile(agent_id=f"a_42_{i:04d}") for i in range(3)]
        assert is_cache_complete(cache, profiles) is True

    def test_missing_life_history(self) -> None:
        cache = _make_cache(n_protag=3)
        # Add a 4th protag — cache doesn't have it
        profiles = [MockProfile(agent_id=f"a_42_{i:04d}") for i in range(4)]
        assert is_cache_complete(cache, profiles) is False

    def test_missing_identity_text(self) -> None:
        cache = _make_cache(n_protag=3)
        # Remove one identity_text entry
        modified = SimulationContentCache(
            **{**cache.model_dump(),
               "identity_text": {k: v for k, v in cache.identity_text.items()
                                  if k != "a_42_0001"}}
        )
        profiles = [MockProfile(agent_id=f"a_42_{i:04d}") for i in range(3)]
        assert is_cache_complete(modified, profiles) is False

    def test_non_protag_not_required(self) -> None:
        """Non-protag agents don't need to be in cache."""
        cache = _make_cache(n_protag=3)
        profiles = [MockProfile(agent_id=f"a_42_{i:04d}") for i in range(3)]
        # Add a non-protag (no biography needed for them)
        profiles.append(MockProfile(agent_id="a_42_9999", is_protagonist=False))
        assert is_cache_complete(cache, profiles) is True

    def test_empty_protag_set_vacuously_complete(self) -> None:
        cache = _make_cache(n_protag=0)
        profiles = [
            MockProfile(agent_id="a_42_0000", is_protagonist=False),
            MockProfile(agent_id="a_42_0001", is_protagonist=False),
        ]
        assert is_cache_complete(cache, profiles) is True


class TestFailedProtagPersists:

    def test_failed_protag_round_trip(self, tmp_path: Path) -> None:
        cache_data = _make_cache(n_protag=3)
        # Add failed_protag manually
        cache_with_fails = SimulationContentCache(
            **{**cache_data.model_dump(),
               "failed_protag": ["a_42_0002"]}
        )
        save_setup_cache(42, cache_with_fails, cache_dir=tmp_path)
        loaded = load_setup_cache(42, cache_dir=tmp_path)
        assert loaded is not None
        assert loaded.failed_protag == ["a_42_0002"]
