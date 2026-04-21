"""
FitnessReport schema - 结构化审计结果

Phase 2 每块 change 的前置证据入口：其 `## Why` 应引用本文件定义的
`FitnessReport` 中 `fail` / `skip` 条目（通过 `mitigation_change` 字段索引）。
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


SCHEMA_VERSION = "1.0"


class AuditStatus(str, Enum):
    """审计结果三态。"""

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


class AuditResult(BaseModel):
    """单条审计条目。"""

    model_config = ConfigDict(frozen=True)

    id: str
    status: AuditStatus
    detail: str = ""
    mitigation_change: str | None = None
    # Phase 2 change name, e.g. "memory" / "orchestrator" / "policy-hack"；
    # 对 fail / skip 必填，对 pass 可为 None。

    extras: dict[str, Any] = Field(default_factory=dict)
    # 自由字段：数值（比例 / 时间 / 计数）与可重现元数据（seed, atlas_sig）


class CategoryResult(BaseModel):
    """一个 category 下的所有 AuditResult。"""

    model_config = ConfigDict(frozen=True)

    category: str
    results: tuple[AuditResult, ...]


class ScaleBaseline(BaseModel):
    """规模基线指标。"""

    model_config = ConfigDict(frozen=True)

    agents: int
    ticks: int
    wall_seconds_total: float
    wall_seconds_p50: float
    wall_seconds_p99: float
    notes: str = ""


class CostBaseline(BaseModel):
    """LLM 成本估算（纯计算，无真实调用）。"""

    model_config = ConfigDict(frozen=True)

    sonnet_calls_estimated: int
    haiku_calls_estimated: int
    skip_calls_estimated: int
    sonnet_cost_usd_lower: float
    sonnet_cost_usd_upper: float
    haiku_cost_usd_lower: float
    haiku_cost_usd_upper: float
    total_usd_lower: float
    total_usd_upper: float
    notes: str = ""


class SiteFitness(BaseModel):
    """Lane Cove atlas 数据诊断（不做门禁，仅报告）。"""

    model_config = ConfigDict(frozen=True)

    named_building_ratio: float
    residential_ratio: float
    density_buildings_per_km2: float
    notes: tuple[str, ...] = ()


class FitnessReport(BaseModel):
    """顶层报告。序列化为 JSON 写入 fitness-report.json。"""

    model_config = ConfigDict(frozen=True)

    schema_version: str = SCHEMA_VERSION
    generated_at: datetime
    atlas_source: str
    atlas_signature: str
    categories: tuple[CategoryResult, ...]
    scale_baseline: ScaleBaseline | None = None
    cost_baseline: CostBaseline | None = None
    site_fitness: SiteFitness | None = None
    seeds: dict[str, int] = Field(default_factory=dict)

    def category(self, name: str) -> CategoryResult | None:
        for cat in self.categories:
            if cat.category == name:
                return cat
        return None

    def failed_results(self) -> list[AuditResult]:
        """Flatten fail/skip results across categories (for Phase 2 引用)."""
        out: list[AuditResult] = []
        for cat in self.categories:
            for r in cat.results:
                if r.status in (AuditStatus.FAIL, AuditStatus.SKIP):
                    out.append(r)
        return out

    def to_json(self, path: Path) -> None:
        """Atomically write report to `path` (via tempfile + rename)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.model_dump(mode="json")
        # Atomic write: tempfile in same dir, then rename.
        fd, tmp = tempfile.mkstemp(
            prefix=path.name + ".",
            suffix=".tmp",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @classmethod
    def from_json(cls, path: Path) -> "FitnessReport":
        """Read report back from disk (for Phase 2 引用 / 回归)."""
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return cls.model_validate(payload)
