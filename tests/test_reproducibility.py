"""Unit tests for synthetic_socio_wind_tunnel.metrics.reproducibility."""

from __future__ import annotations

from synthetic_socio_wind_tunnel.metrics.reproducibility import (
    _git_rev_parse_head,
    _hash_profile,
    _hash_prompt_template,
    _hash_variants,
    compute_reproducibility_lock,
)


class TestComputeReproducibilityLock:

    def test_seven_fields_present(self):
        lock = compute_reproducibility_lock(
            seed_pool=[42, 99],
            use_real_llm=False,
            variant_names=["baseline", "hyperlocal_push"],
            phase_config={"baseline_days": 4, "intervention_days": 6, "post_days": 4},
        )
        required = {
            "seed_pool", "model_version", "prompt_template_hash",
            "LANE_COVE_PROFILE_hash", "variants_loaded", "code_commit",
            "phase_config",
        }
        assert required <= set(lock.keys())

    def test_seed_pool_preserved(self):
        lock = compute_reproducibility_lock(
            seed_pool=[42, 99],
            use_real_llm=False,
            variant_names=["baseline"],
            phase_config={},
        )
        assert lock["seed_pool"] == [42, 99]

    def test_phase_config_preserved(self):
        pc = {"baseline_days": 4, "intervention_days": 6, "post_days": 4}
        lock = compute_reproducibility_lock(
            seed_pool=[1],
            use_real_llm=False,
            variant_names=["baseline"],
            phase_config=pc,
        )
        assert lock["phase_config"] == pc

    def test_stub_mode_model_version(self):
        lock = compute_reproducibility_lock(
            seed_pool=[1], use_real_llm=False,
            variant_names=["baseline"], phase_config={},
        )
        assert lock["model_version"] == "stub:v1"

    def test_real_llm_anthropic_model_version(self):
        lock = compute_reproducibility_lock(
            seed_pool=[1], use_real_llm=True,
            variant_names=["baseline"], phase_config={},
            provider="anthropic",
        )
        assert "claude" in lock["model_version"]

    def test_real_llm_gemini_model_version(self):
        lock = compute_reproducibility_lock(
            seed_pool=[1], use_real_llm=True,
            variant_names=["baseline"], phase_config={},
            provider="gemini",
        )
        assert "gemini" in lock["model_version"]


class TestPromptTemplateHash:

    def test_stub_mode_returns_stub_prefix(self):
        h = _hash_prompt_template(use_real_llm=False, variant_name="hyperlocal_push")
        assert h == "stub:hyperlocal_push"

    def test_real_mode_returns_sha256(self):
        h = _hash_prompt_template(use_real_llm=True)
        # SHA-256 hex string is 64 chars
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


class TestProfileHash:

    def test_consistent_across_calls(self):
        h1 = _hash_profile()
        h2 = _hash_profile()
        assert h1 == h2

    def test_sha256_format(self):
        h = _hash_profile()
        assert len(h) == 64


class TestVariantsLoaded:

    def test_returns_dict_per_variant(self):
        v = _hash_variants(["baseline", "hyperlocal_push"])
        assert set(v.keys()) == {"baseline", "hyperlocal_push"}
        for hash_str in v.values():
            assert len(hash_str) == 64


class TestGitRevParse:

    def test_returns_string(self):
        # In the repo, git is available; test should return real hash.
        # In CI without git, fallback to "unknown".
        h = _git_rev_parse_head()
        assert isinstance(h, str)
        assert h == "unknown" or len(h) >= 7  # short or full SHA


class TestHotPathIsolation:
    """reproducibility module must not be imported by sim runtime."""

    def test_runtime_does_not_import_reproducibility(self):
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-c", (
                "import sys; "
                "import synthetic_socio_wind_tunnel.agent.runtime; "
                "import synthetic_socio_wind_tunnel.agent.planner; "
                "assert 'synthetic_socio_wind_tunnel.metrics.reproducibility' not in sys.modules, "
                "    'reproducibility module leaked into hot path'"
            )],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr
