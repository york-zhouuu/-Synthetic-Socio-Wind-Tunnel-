"""
Fitness Audit - Phase 1 基建能否承载社会实验 thesis 的可执行审计

产出结构化 FitnessReport，每条 AuditResult 带 pass/fail/skip + rationale。
作为 Phase 2 每块 change 的前置证据：fail/skip 条目必须被对应 change 的
## Why 引用。

详见：openspec/changes/realign-to-social-thesis/specs/fitness-audit/spec.md
"""

from synthetic_socio_wind_tunnel.fitness.report import (
    AuditResult,
    AuditStatus,
    CategoryResult,
    FitnessReport,
)
from synthetic_socio_wind_tunnel.fitness.audit import run_audit

__all__ = [
    "AuditResult",
    "AuditStatus",
    "CategoryResult",
    "FitnessReport",
    "run_audit",
]
