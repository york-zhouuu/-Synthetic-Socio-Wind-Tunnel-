"""tick-level-resume audit — verify SimulationCheckpoint wiring is complete.

Probes:
1. module `state_snapshot` importable
2. SimulationCheckpoint write_atomic + read round-trip
3-6. Each of 4 subsystems (Ledger / AgentRuntime / MemoryService /
   AttentionService) exposes `to_snapshot_state` + `from_snapshot_state`
"""

from __future__ import annotations

import importlib
from datetime import datetime
from pathlib import Path
import tempfile

from synthetic_socio_wind_tunnel.fitness.report import (
    AuditResult,
    AuditStatus,
    CategoryResult,
)


def _probe_module_importable() -> AuditResult:
    try:
        importlib.import_module(
            "synthetic_socio_wind_tunnel.run_resilience.state_snapshot",
        )
        return AuditResult(
            id="phase2-gaps.tick-level-resume.module",
            status=AuditStatus.PASS,
            detail="run_resilience.state_snapshot importable",
        )
    except ImportError as exc:
        return AuditResult(
            id="phase2-gaps.tick-level-resume.module",
            status=AuditStatus.FAIL,
            detail=f"import failed: {exc}",
            mitigation_change="tick-level-resume",
        )


def _probe_checkpoint_roundtrip() -> AuditResult:
    try:
        from synthetic_socio_wind_tunnel.run_resilience import (
            SimulationCheckpoint,
        )
        snap = SimulationCheckpoint(
            seed=1, tick_index=0, day_index=0,
            simulated_time=datetime(2026, 1, 1),
        )
        with tempfile.TemporaryDirectory() as tdir:
            p = Path(tdir) / "snap.json"
            snap.write_atomic(p)
            snap2 = SimulationCheckpoint.read(p)
            if snap2.tick_index != snap.tick_index:
                raise ValueError("round-trip mismatch")
        return AuditResult(
            id="phase2-gaps.tick-level-resume.checkpoint-roundtrip",
            status=AuditStatus.PASS,
            detail="SimulationCheckpoint.write_atomic + read round-trip ok",
        )
    except Exception as exc:  # noqa: BLE001
        return AuditResult(
            id="phase2-gaps.tick-level-resume.checkpoint-roundtrip",
            status=AuditStatus.FAIL,
            detail=f"round-trip failed: {exc}",
            mitigation_change="tick-level-resume",
        )


def _probe_subsystem_has_methods(
    dotted_class: str, audit_id_suffix: str,
) -> AuditResult:
    """Probe a subsystem class has both `to_snapshot_state` and
    `from_snapshot_state` methods."""
    audit_id = f"phase2-gaps.tick-level-resume.{audit_id_suffix}"
    try:
        module_path, class_name = dotted_class.rsplit(".", 1)
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
    except (ImportError, AttributeError) as exc:
        return AuditResult(
            id=audit_id, status=AuditStatus.FAIL,
            detail=f"cannot import {dotted_class}: {exc}",
            mitigation_change="tick-level-resume",
        )
    missing = []
    if not callable(getattr(cls, "to_snapshot_state", None)):
        missing.append("to_snapshot_state")
    if not callable(getattr(cls, "from_snapshot_state", None)):
        missing.append("from_snapshot_state")
    if missing:
        return AuditResult(
            id=audit_id, status=AuditStatus.FAIL,
            detail=f"{class_name} missing methods: {missing}",
            mitigation_change="tick-level-resume",
        )
    return AuditResult(
        id=audit_id, status=AuditStatus.PASS,
        detail=f"{class_name} exposes to/from_snapshot_state",
    )


def audit_tick_level_resume() -> CategoryResult:
    results: list[AuditResult] = [
        _probe_module_importable(),
        _probe_checkpoint_roundtrip(),
        _probe_subsystem_has_methods(
            "synthetic_socio_wind_tunnel.ledger.service.Ledger",
            "subsys-ledger",
        ),
        _probe_subsystem_has_methods(
            "synthetic_socio_wind_tunnel.agent.runtime.AgentRuntime",
            "subsys-agent",
        ),
        _probe_subsystem_has_methods(
            "synthetic_socio_wind_tunnel.memory.service.MemoryService",
            "subsys-memory",
        ),
        _probe_subsystem_has_methods(
            "synthetic_socio_wind_tunnel.attention.service.AttentionService",
            "subsys-attention",
        ),
    ]
    return CategoryResult(category="phase2-gaps", results=tuple(results))
