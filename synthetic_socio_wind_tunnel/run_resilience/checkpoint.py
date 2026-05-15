"""
DayCheckpointWriter — per-day partial 写盘 + resume 接续。

D1' 事故里 14-day run 是"全有或全无"——死锁/崩溃/Ctrl-C 发生在 dump 之前 =
100% 数据丢失。本模块在 MultiDayRunner.on_day_end hook 内同步落
`seed_{N}_day{D}.partial.json`，使最坏损失 ≤ 1 模拟天。

partial JSON schema_version "1"：

    {
        "schema_version": "1",
        "seed": <int>,
        "day_index": <int>,             # 已完成的最大 day index
        "simulated_date": "<iso>",
        "run_metrics": <RunMetrics.model_dump()>,
        "ledger_snapshot": <ledger 状态摘要>,
        "memory_dump": <agent_id → memory state>,
        "provider": "<gemini|deepseek|anthropic|stub>",
        "created_at": "<iso timestamp>"
    }
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import date as date_cls, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_CURRENT_SCHEMA_VERSION = "1"
_LARGE_DUMP_WARN_BYTES = 200 * 1024 * 1024  # 200 MB


class IncompatibleCheckpointError(RuntimeError):
    """partial JSON 的 schema_version 与当前 reader 不兼容。"""

    def __init__(self, *, expected: str, found: str, path: Path) -> None:
        super().__init__(
            f"checkpoint schema_version mismatch at {path}: "
            f"expected {expected!r}, found {found!r}",
        )
        self.expected = expected
        self.found = found
        self.path = path


class DayCheckpointWriter:
    """Per-day partial 落盘 + 读取 + 清理。无状态——可单例复用。"""

    def __init__(self, *, schema_version: str = _CURRENT_SCHEMA_VERSION) -> None:
        self.schema_version = schema_version

    def write_partial(
        self,
        *,
        output_dir: Path,
        seed: int,
        day_index: int,
        simulated_date: date_cls,
        run_metrics: dict[str, Any],
        ledger_snapshot: dict[str, Any],
        memory_dump: dict[str, Any],
        provider: str,
    ) -> Path:
        """原子写 partial 到 output_dir/seed_{seed}_day{day_index}.partial.json。

        先写 <target>.tmp，fsync，然后 rename——SIGKILL 期间目标路径要么不存在、
        要么是合法 JSON。
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # 启动时清扫前次失败留下的 .tmp 残骸（按 seed 范围）
        for stale in output_dir.glob(f"seed_{seed}_day*.partial.json.tmp"):
            try:
                stale.unlink()
            except OSError:
                logger.warning("无法清理残留 tmp 文件 %s", stale)

        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "seed": seed,
            "day_index": day_index,
            "simulated_date": simulated_date.isoformat(),
            "run_metrics": run_metrics,
            "ledger_snapshot": ledger_snapshot,
            "memory_dump": memory_dump,
            "provider": provider,
            "created_at": datetime.utcnow().isoformat() + "Z",
        }

        target = output_dir / f"seed_{seed}_day{day_index}.partial.json"
        tmp = target.with_suffix(target.suffix + ".tmp")

        body = json.dumps(payload, ensure_ascii=False, default=str)
        body_bytes = len(body.encode("utf-8"))
        if body_bytes > _LARGE_DUMP_WARN_BYTES:
            logger.warning(
                "partial dump for seed=%d day=%d is %d bytes (> 200 MB warn threshold); "
                "consider trimming memory_dump scope",
                seed, day_index, body_bytes,
            )

        # 写 + fsync + rename（POSIX 原子）
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(body)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    # 部分文件系统不支持 fsync（e.g. tmpfs/sshfs）；继续
                    pass
        except Exception:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
        os.replace(tmp, target)
        return target

    def read_partial(self, path: Path) -> dict[str, Any]:
        """读 + schema_version 校验。"""
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        found_version = str(payload.get("schema_version", ""))
        if found_version != self.schema_version:
            raise IncompatibleCheckpointError(
                expected=self.schema_version,
                found=found_version,
                path=path,
            )
        return payload

    def find_latest_partial(
        self, *, output_dir: Path, seed: int,
    ) -> Path | None:
        """扫描 output_dir，返回该 seed 最大 day_index 的 partial 路径。"""
        if not output_dir.exists():
            return None
        candidates: list[tuple[int, Path]] = []
        prefix = f"seed_{seed}_day"
        suffix = ".partial.json"
        for p in output_dir.glob(f"{prefix}*{suffix}"):
            stem = p.name[len(prefix):-len(suffix)]
            try:
                candidates.append((int(stem), p))
            except ValueError:
                continue
        if not candidates:
            return None
        candidates.sort(key=lambda t: t[0])
        return candidates[-1][1]

    def cleanup_partials(self, *, output_dir: Path, seed: int) -> list[Path]:
        """删除该 seed 所有 partial 文件；返回被删的路径列表。"""
        if not output_dir.exists():
            return []
        removed: list[Path] = []
        for p in output_dir.glob(f"seed_{seed}_day*.partial.json"):
            try:
                p.unlink()
                removed.append(p)
            except OSError as exc:
                logger.warning("无法删除 partial %s: %s", p, exc)
        return removed
