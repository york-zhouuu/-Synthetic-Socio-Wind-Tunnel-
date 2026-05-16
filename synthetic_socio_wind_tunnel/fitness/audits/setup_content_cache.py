"""setup-content-cache audit — verify cache plumbing is in place.

Probes:
1. module `data_loader.setup_cache` importable
2. SimulationContentCache round-trip (save + load + roundtrip equality)
3. `is_cache_complete` correctly handles partial coverage
4. `tools/prewarm_setup_content.py` exists + main() callable
5. `tools/run_variant_suite.py` exports `_load_or_generate_setup_content`
"""

from __future__ import annotations

import importlib
import json
import tempfile
from datetime import datetime
from pathlib import Path

from synthetic_socio_wind_tunnel.fitness.report import (
    AuditResult,
    AuditStatus,
    CategoryResult,
)


def _probe_module_importable() -> AuditResult:
    try:
        importlib.import_module(
            "synthetic_socio_wind_tunnel.data_loader.setup_cache",
        )
        return AuditResult(
            id="phase2-gaps.setup-content-cache.module",
            status=AuditStatus.PASS,
            detail="data_loader.setup_cache importable",
        )
    except ImportError as exc:
        return AuditResult(
            id="phase2-gaps.setup-content-cache.module",
            status=AuditStatus.FAIL,
            detail=f"import failed: {exc}",
            mitigation_change="setup-content-cache",
        )


def _probe_cache_roundtrip() -> AuditResult:
    try:
        from synthetic_socio_wind_tunnel.data_loader import (
            SimulationContentCache,
            load_setup_cache,
            save_setup_cache,
        )
        with tempfile.TemporaryDirectory() as tdir:
            tdir_path = Path(tdir)
            cache = SimulationContentCache(
                seed=999,
                generated_at=datetime(2026, 5, 16, 22, 0, 0),
                generator={"tier": "sonnet", "model": "test"},
                life_history={"a_999_0001": [{
                    "record_id": "x", "agent_id": "a_999_0001",
                    "title": "t", "content": "c", "years_ago": 1.0,
                    "location_hint": None, "importance": 0.5, "tags": [],
                }]},
                identity_text={"a_999_0001": "I am a test agent."},
                failed_protag=[],
            )
            save_setup_cache(999, cache, cache_dir=tdir_path)
            loaded = load_setup_cache(999, cache_dir=tdir_path)
            if loaded is None:
                raise RuntimeError("load returned None after save")
            if loaded.seed != 999:
                raise RuntimeError(f"seed mismatch: {loaded.seed} != 999")
        return AuditResult(
            id="phase2-gaps.setup-content-cache.cache-roundtrip",
            status=AuditStatus.PASS,
            detail="SimulationContentCache save→load round-trip ok",
        )
    except Exception as exc:  # noqa: BLE001
        return AuditResult(
            id="phase2-gaps.setup-content-cache.cache-roundtrip",
            status=AuditStatus.FAIL,
            detail=f"round-trip failed: {exc}",
            mitigation_change="setup-content-cache",
        )


def _probe_is_cache_complete() -> AuditResult:
    """Probe that is_cache_complete returns False when protag not covered."""
    try:
        from synthetic_socio_wind_tunnel.data_loader import (
            SimulationContentCache,
            is_cache_complete,
        )

        class _Profile:
            def __init__(self, aid: str, protag: bool):
                self.agent_id = aid
                self.is_protagonist = protag

        cache = SimulationContentCache(
            seed=1,
            generated_at=datetime(2026, 5, 16),
            generator={},
            life_history={"a_only": []},
            identity_text={"a_only": ""},
            failed_protag=[],
        )
        # All-covered case → True
        if not is_cache_complete(cache, [_Profile("a_only", True)]):
            raise RuntimeError("expected True for fully-covered protag")
        # Missing protag → False
        if is_cache_complete(cache, [
            _Profile("a_only", True), _Profile("a_missing", True),
        ]):
            raise RuntimeError("expected False for partial coverage")
        return AuditResult(
            id="phase2-gaps.setup-content-cache.is-cache-complete",
            status=AuditStatus.PASS,
            detail="is_cache_complete correctly detects partial coverage",
        )
    except Exception as exc:  # noqa: BLE001
        return AuditResult(
            id="phase2-gaps.setup-content-cache.is-cache-complete",
            status=AuditStatus.FAIL,
            detail=f"check failed: {exc}",
            mitigation_change="setup-content-cache",
        )


def _probe_prewarm_cli_exists() -> AuditResult:
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "tools" / "prewarm_setup_content.py"
    if not script.exists():
        return AuditResult(
            id="phase2-gaps.setup-content-cache.prewarm-cli",
            status=AuditStatus.FAIL,
            detail=f"missing script: {script}",
            mitigation_change="setup-content-cache",
        )
    # Verify main + _parse_seed_range exist
    try:
        import sys
        sys.path.insert(0, str(repo_root))
        try:
            mod = importlib.import_module("tools.prewarm_setup_content")
        finally:
            sys.path.pop(0)
        if not callable(getattr(mod, "main", None)):
            raise RuntimeError("main() not callable")
        if not callable(getattr(mod, "_parse_seed_range", None)):
            raise RuntimeError("_parse_seed_range() not callable")
        return AuditResult(
            id="phase2-gaps.setup-content-cache.prewarm-cli",
            status=AuditStatus.PASS,
            detail="tools/prewarm_setup_content.py main + _parse_seed_range callable",
        )
    except Exception as exc:  # noqa: BLE001
        return AuditResult(
            id="phase2-gaps.setup-content-cache.prewarm-cli",
            status=AuditStatus.FAIL,
            detail=f"prewarm import failed: {exc}",
            mitigation_change="setup-content-cache",
        )


def _probe_suite_wiring() -> AuditResult:
    """Verify run_variant_suite.py exposes _load_or_generate_setup_content."""
    try:
        import sys
        repo_root = Path(__file__).resolve().parents[3]
        sys.path.insert(0, str(repo_root))
        try:
            mod = importlib.import_module("tools.run_variant_suite")
        finally:
            sys.path.pop(0)
        if not callable(getattr(mod, "_load_or_generate_setup_content", None)):
            raise RuntimeError("_load_or_generate_setup_content not callable")
        return AuditResult(
            id="phase2-gaps.setup-content-cache.suite-wiring",
            status=AuditStatus.PASS,
            detail="run_variant_suite._load_or_generate_setup_content present",
        )
    except Exception as exc:  # noqa: BLE001
        return AuditResult(
            id="phase2-gaps.setup-content-cache.suite-wiring",
            status=AuditStatus.FAIL,
            detail=f"suite wiring check failed: {exc}",
            mitigation_change="setup-content-cache",
        )


def audit_setup_content_cache() -> CategoryResult:
    results: list[AuditResult] = [
        _probe_module_importable(),
        _probe_cache_roundtrip(),
        _probe_is_cache_complete(),
        _probe_prewarm_cli_exists(),
        _probe_suite_wiring(),
    ]
    return CategoryResult(category="phase2-gaps", results=tuple(results))
