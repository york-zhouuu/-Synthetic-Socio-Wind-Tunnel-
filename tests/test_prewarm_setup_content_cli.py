"""Tests for tools.prewarm_setup_content CLI.

Focus on argparse + skip path + dry-run path. Full LLM end-to-end is
covered manually by Phase F real-run (1000 agent × N seed = expensive).
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from tools.prewarm_setup_content import (
    _build_parser,
    _parse_seed_range,
    main,
)


class TestParseSeedRange:

    def test_single_seed(self):
        assert _parse_seed_range("42") == [42]

    def test_range_dash(self):
        assert _parse_seed_range("42-44") == [42, 43, 44]

    def test_csv(self):
        assert _parse_seed_range("42,43,44") == [42, 43, 44]

    def test_csv_with_spaces(self):
        assert _parse_seed_range("42, 43, 44") == [42, 43, 44]

    def test_range_inclusive(self):
        assert _parse_seed_range("42-56") == list(range(42, 57))

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            _parse_seed_range("")

    def test_inverted_range_raises(self):
        with pytest.raises(ValueError):
            _parse_seed_range("56-42")

    def test_malformed_raises(self):
        with pytest.raises(ValueError):
            _parse_seed_range("abc")


class TestArgparse:

    def test_defaults(self):
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.seeds == "42-51"  # β=10 publishable (2026-05-17)
        assert args.concurrency == 4
        assert args.tier == "sonnet"
        assert args.provider == "deepseek"
        assert args.n_records == 20
        assert args.prompt_version == "v2"
        assert args.n_agents == 1000
        assert args.num_protag == 500
        assert args.force is False
        assert args.dry_run is False

    def test_overrides(self):
        parser = _build_parser()
        args = parser.parse_args([
            "--seeds", "42",
            "--concurrency", "2",
            "--tier", "haiku",
            "--provider", "anthropic",
            "--n-records", "10",
            "--n-agents", "100",
            "--num-protag", "50",
            "--force",
            "--dry-run",
        ])
        assert args.seeds == "42"
        assert args.concurrency == 2
        assert args.tier == "haiku"
        assert args.provider == "anthropic"
        assert args.n_records == 10
        assert args.n_agents == 100
        assert args.num_protag == 50
        assert args.force is True
        assert args.dry_run is True

    def test_invalid_tier_rejected(self):
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--tier", "opus"])


class TestMainExitCodes:

    def test_invalid_seed_range_exits_2(self, capsys: pytest.CaptureFixture):
        rc = main(["--seeds", "abc", "--dry-run"])
        assert rc == 2
        captured = capsys.readouterr()
        assert "invalid --seeds" in captured.err

    def test_inverted_range_exits_2(self, capsys: pytest.CaptureFixture):
        rc = main(["--seeds", "56-42", "--dry-run"])
        assert rc == 2

    def test_dry_run_no_provider_key_still_ok(
        self, monkeypatch: pytest.MonkeyPatch,
    ):
        """--dry-run should skip the env var check."""
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEYS", raising=False)
        rc = main([
            "--seeds", "42",
            "--n-agents", "10",
            "--num-protag", "2",
            "--dry-run",
        ])
        assert rc == 0

    def test_missing_deepseek_key_exits_2(
        self, monkeypatch: pytest.MonkeyPatch,
    ):
        """Without --dry-run + no env keys → exit 2."""
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEYS", raising=False)
        rc = main(["--seeds", "42", "--provider", "deepseek"])
        assert rc == 2


class TestSkipPath:

    def test_existing_cache_skipped_without_force(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """If cache file exists and --force not passed, should skip."""
        # Pre-populate a cache file
        cache_payload = {
            "schema_version": "1",
            "seed": 42,
            "generated_at": "2026-05-16T00:00:00",
            "generator": {"tier": "sonnet", "model": "test"},
            "life_history": {
                "a_42_0001": [{
                    "record_id": "lh_1", "agent_id": "a_42_0001",
                    "title": "t", "content": "c", "years_ago": 1.0,
                    "location_hint": None, "importance": 0.5, "tags": [],
                }],
            },
            "identity_text": {"a_42_0001": "I am a test agent."},
            "failed_protag": [],
        }
        (tmp_path / "seed_42.json").write_text(json.dumps(cache_payload))

        # Set API key so we get past the provider check
        monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key-for-test")

        rc = main([
            "--seeds", "42",
            "--n-agents", "10",
            "--num-protag", "2",
            "--cache-dir", str(tmp_path),
        ])
        # Should succeed (exit 0) without actually calling any LLM
        assert rc == 0
        # Cache file untouched
        assert (tmp_path / "seed_42.json").exists()
        # Verify it's still the pre-populated content (didn't get overwritten)
        loaded = json.loads((tmp_path / "seed_42.json").read_text())
        assert loaded["seed"] == 42
        assert "a_42_0001" in loaded["life_history"]


class TestDryRun:

    def test_dry_run_doesnt_write_cache(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """--dry-run SHALL NOT write any cache file."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
        rc = main([
            "--seeds", "42",
            "--n-agents", "10",
            "--num-protag", "2",
            "--cache-dir", str(tmp_path),
            "--dry-run",
        ])
        assert rc == 0
        assert list(tmp_path.glob("*.json")) == []
