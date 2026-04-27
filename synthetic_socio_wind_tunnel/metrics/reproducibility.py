"""
Reproducibility lock — 7-field metadata stamping for publishable runs.

Implements `validation-strategy` Part VI. Every publishable RunMetrics
SHALL contain the 7 fields produced by `compute_reproducibility_lock`,
serialized into RunMetrics.extensions.

Sim hot path MUST NOT import this module — only run_variant_suite invokes
it once per suite (cheap, < 10 ms total).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from typing import Any

from synthetic_socio_wind_tunnel.agent import LANE_COVE_PROFILE


def _hash_string(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _hash_prompt_template(use_real_llm: bool, variant_name: str | None = None) -> str:
    """
    SHA-256 of the active Planner prompt template, OR `stub:<variant_name>`
    when running stub-only (no real LLM prompt is sent).
    """
    if not use_real_llm:
        return f"stub:{variant_name or 'default'}"

    # Real-LLM mode: hash the actual prompt template literal.
    # Lazy-import to keep this module's imports light.
    from synthetic_socio_wind_tunnel.agent.planner import _PLAN_PROMPT_TEMPLATE
    return _hash_string(_PLAN_PROMPT_TEMPLATE)


def _hash_profile() -> str:
    """SHA-256 of LANE_COVE_PROFILE serialized to canonical JSON."""
    # Pydantic v2 model_dump_json doesn't accept sort_keys; use model_dump + json.dumps
    payload = LANE_COVE_PROFILE.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return _hash_string(canonical)


def _hash_variants(variant_names: list[str]) -> dict[str, str]:
    """
    Per-variant config hash. Variant configs are imported lazily to avoid
    cyclic imports if metrics is loaded before tools/.
    """
    # Best-effort: variants are defined in tools/ + policy_hack capability.
    # We hash the variant_name itself as a stable identifier; a future change
    # could deepen this to hash the actual variant config dict.
    return {name: _hash_string(name) for name in variant_names}


def _resolve_model_version(use_real_llm: bool, provider: str | None = None) -> str:
    if not use_real_llm:
        return "stub:v1"
    if provider == "anthropic":
        return "claude-haiku-4-5-20251001"
    if provider == "gemini":
        return "gemini-3-flash-preview"
    return f"real_llm:{provider or 'unknown'}"


def _git_rev_parse_head() -> str:
    """`git rev-parse HEAD` with graceful fallback."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "unknown"


def compute_reproducibility_lock(
    *,
    seed_pool: list[int],
    use_real_llm: bool,
    variant_names: list[str],
    phase_config: dict[str, Any],
    provider: str | None = None,
) -> dict[str, Any]:
    """
    Build the 7-field reproducibility lock for a publishable suite.

    All 7 fields per `validation-strategy` Part VI are populated. Stub
    mode produces deterministic placeholder hashes (`stub:*`); real-LLM
    mode hashes actual prompts.
    """
    return {
        "seed_pool": list(seed_pool),
        "model_version": _resolve_model_version(use_real_llm, provider),
        "prompt_template_hash": _hash_prompt_template(
            use_real_llm,
            variant_name=variant_names[0] if variant_names else None,
        ),
        "LANE_COVE_PROFILE_hash": _hash_profile(),
        "variants_loaded": _hash_variants(variant_names),
        "code_commit": _git_rev_parse_head(),
        "phase_config": dict(phase_config),
    }


__all__ = ["compute_reproducibility_lock"]
