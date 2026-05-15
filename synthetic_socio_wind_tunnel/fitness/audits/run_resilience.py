"""run-resilience audit — verify D1' fix is wired through.

Probes:
1. Module `synthetic_socio_wind_tunnel.run_resilience` importable
2. `tools/audit_run_health.py` exists + executable
3. `tools/preflight_full_smoke.py` exists + executable
4. `_GeminiTierClient` httpx limits have `max_keepalive_connections == 0`
5. `_DeepSeekTierClient` httpx limits have `max_keepalive_connections == 0`
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

from synthetic_socio_wind_tunnel.fitness.report import (
    AuditResult,
    AuditStatus,
    CategoryResult,
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _probe_module_importable() -> AuditResult:
    try:
        importlib.import_module("synthetic_socio_wind_tunnel.run_resilience")
        return AuditResult(
            id="phase2-gaps.run-resilience.module",
            status=AuditStatus.PASS,
            detail="synthetic_socio_wind_tunnel.run_resilience importable",
        )
    except ImportError as exc:
        return AuditResult(
            id="phase2-gaps.run-resilience.module",
            status=AuditStatus.FAIL,
            detail=f"import failed: {exc}",
            mitigation_change="run-resilience",
        )


def _probe_cli(name: str, audit_id: str) -> AuditResult:
    path = _project_root() / "tools" / name
    if not path.exists():
        return AuditResult(
            id=audit_id,
            status=AuditStatus.FAIL,
            detail=f"missing {path}",
            mitigation_change="run-resilience",
        )
    if not os.access(path, os.X_OK):
        return AuditResult(
            id=audit_id,
            status=AuditStatus.FAIL,
            detail=f"{path} exists but is not executable",
            mitigation_change="run-resilience",
        )
    return AuditResult(
        id=audit_id,
        status=AuditStatus.PASS,
        detail=f"{path.name} present + executable",
    )


def _probe_keepalive_zero(provider: str, audit_id: str) -> AuditResult:
    """Construct a tier client with a fake api key, introspect httpx limits."""
    try:
        # Set fake env keys so SDK construction doesn't refuse
        os.environ.setdefault("GEMINI_API_KEY", "audit-fake-key")
        os.environ.setdefault("DEEPSEEK_API_KEY", "audit-fake-key")
        os.environ.setdefault("ANTHROPIC_API_KEY", "audit-fake-key")
        from tools.tier_llm_factory import build_tier_clients
        clients = build_tier_clients(provider=provider)
        sonnet = clients["sonnet"]
        # Gemini/DeepSeek: _contexts[0].httpx_client
        # Anthropic: _ctx.httpx_client
        ctx = getattr(sonnet, "_contexts", None)
        if ctx is not None and len(ctx) > 0:
            httpx_client = ctx[0].httpx_client
        else:
            httpx_client = sonnet._ctx.httpx_client
        pool = httpx_client._transport._pool
        keepalive = pool._max_keepalive_connections
        if keepalive == 0:
            return AuditResult(
                id=audit_id,
                status=AuditStatus.PASS,
                detail=f"{provider} keepalive=0 (CLOSE_WAIT path blocked)",
            )
        return AuditResult(
            id=audit_id,
            status=AuditStatus.FAIL,
            detail=f"{provider} keepalive={keepalive}, expected 0",
            mitigation_change="run-resilience",
        )
    except Exception as exc:  # noqa: BLE001
        return AuditResult(
            id=audit_id,
            status=AuditStatus.FAIL,
            detail=f"could not probe {provider}: {exc}",
            mitigation_change="run-resilience",
        )


def audit_run_resilience() -> CategoryResult:
    results: list[AuditResult] = [
        _probe_module_importable(),
        _probe_cli("audit_run_health.py", "phase2-gaps.run-resilience.audit-cli"),
        _probe_cli("preflight_full_smoke.py", "phase2-gaps.run-resilience.preflight-cli"),
        _probe_keepalive_zero("gemini", "phase2-gaps.run-resilience.gemini-keepalive"),
        _probe_keepalive_zero("deepseek", "phase2-gaps.run-resilience.deepseek-keepalive"),
    ]
    return CategoryResult(category="phase2-gaps", results=tuple(results))
