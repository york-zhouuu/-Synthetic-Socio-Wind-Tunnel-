"""
setup_cache — per-seed 持久化 setup phase LLM 内容。

2026-05-16 D2 attempt 3 失败暴露：setup phase 在 publishable scale 下
（4 worker × 500 protag 并发）把 DeepSeek 端打到 connection refusal，
500 protag 中 0 个有 life_history 被成功生成。同时发现 life_history 和
identity_text 是确定性内容（给定 seed + agent_id 应当是同一虚构人物），
每次 run 都从零生成是重复浪费。

本模块提供：
- `SimulationContentCache` Pydantic frozen 模型
- `load_setup_cache(seed)` / `save_setup_cache(seed, cache)` /
  `is_cache_complete(cache, profiles)`
- per-seed 一文件：data/setup_content_cache/seed_<N>.json
- schema_version-based 自动 invalidation

调用约定（典型 cache-or-generate 流程）：

    cache = load_setup_cache(seed)
    if cache and is_cache_complete(cache, profiles):
        # HIT — 零 LLM call
        life_history = cache.life_history
        identity_text = cache.identity_text
    else:
        # MISS — 在线生成 + 写盘
        life_history = await generate_life_history_for_protagonists(...)
        identity_text = await generate_identity_text_for_protagonists(...)
        new_cache = SimulationContentCache(
            seed=seed,
            life_history=...,
            identity_text=...,
            ...
        )
        save_setup_cache(seed, new_cache)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


_CURRENT_SCHEMA_VERSION = "1"
_DEFAULT_CACHE_DIRNAME = "setup_content_cache"


def _default_cache_dir() -> Path:
    """Default at <repo_root>/data/setup_content_cache/."""
    return Path(__file__).resolve().parents[2] / "data" / _DEFAULT_CACHE_DIRNAME


class SimulationContentCache(BaseModel):
    """Persistent per-seed cache of setup phase LLM content.

    Serialized as plain JSON (NOT Pydantic .json() round-trip) so files
    remain human-readable + manually editable. Fields are read back via
    `model_validate` from the JSON dict at load time.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: str = _CURRENT_SCHEMA_VERSION
    seed: int
    generated_at: datetime
    generator: dict[str, Any] = Field(default_factory=dict)
    """Metadata about how this cache was generated:
    tier / model / n_records_per_protag / prompt_version / concurrency."""

    life_history: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    """agent_id → list of LifeHistoryRecord dict.
    Each record: record_id / title / content / years_ago / location_hint /
    importance / tags."""

    identity_text: dict[str, str] = Field(default_factory=dict)
    """agent_id → ~150-200 字第一人称中文自我介绍。"""

    failed_protag: list[str] = Field(default_factory=list)
    """agent_ids that fell back to template (audit trail)."""


def load_setup_cache(
    seed: int,
    *,
    cache_dir: Path | None = None,
) -> SimulationContentCache | None:
    """Read + schema-validate the per-seed cache file.

    Returns None for any reason the cache should be treated as miss:
    - File doesn't exist
    - JSON parse failure
    - schema_version doesn't match current

    Caller decides cache HIT vs MISS based on return value.
    """
    cache_dir = cache_dir or _default_cache_dir()
    path = cache_dir / f"seed_{seed}.json"
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "setup_cache: failed to read %s (%s); treating as cache miss",
            path, exc,
        )
        return None

    found_version = str(payload.get("schema_version", ""))
    if found_version != _CURRENT_SCHEMA_VERSION:
        logger.warning(
            "setup_cache: schema mismatch at %s (expected %r, found %r); "
            "treating as cache miss — re-prewarm needed",
            path, _CURRENT_SCHEMA_VERSION, found_version,
        )
        return None

    try:
        return SimulationContentCache.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "setup_cache: validation failed for %s (%s); treating as cache miss",
            path, exc,
        )
        return None


def save_setup_cache(
    seed: int,
    cache: SimulationContentCache,
    *,
    cache_dir: Path | None = None,
) -> Path:
    """Atomically write the cache to disk.

    Uses .tmp + os.replace pattern (same as run-resilience checkpoint).
    Returns the final path. Raises OSError on write failure (caller
    should NOT swallow — failed cache writes leave the run without
    persistence, important to surface).
    """
    cache_dir = cache_dir or _default_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    if seed != cache.seed:
        raise ValueError(
            f"save_setup_cache: seed arg ({seed}) != cache.seed ({cache.seed})",
        )

    target = cache_dir / f"seed_{seed}.json"
    tmp = target.with_suffix(target.suffix + ".tmp")

    # Clean any stale .tmp from prior failed write
    if tmp.exists():
        try:
            tmp.unlink()
        except OSError:
            pass

    body = json.dumps(
        cache.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        default=str,
    )

    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # Some filesystems (tmpfs / sshfs) don't support fsync
                pass
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    os.replace(tmp, target)
    return target


def is_cache_complete(
    cache: SimulationContentCache,
    profiles: list,
) -> bool:
    """Check if cache covers all protagonist agent_ids in profiles.

    Returns True iff:
    - All protag (is_protagonist=True) agent_ids appear in life_history keys
    - AND all protag agent_ids appear in identity_text keys

    Partial coverage is treated as cache miss (caller re-generates,
    cache overwrites). This is simpler than per-protag incremental merge.
    """
    expected = {
        getattr(p, "agent_id", None)
        for p in profiles
        if getattr(p, "is_protagonist", False)
    }
    expected.discard(None)
    if not expected:
        # Nothing to satisfy — vacuously complete
        return True
    cached_life = set(cache.life_history.keys())
    cached_id = set(cache.identity_text.keys())
    return expected <= cached_life and expected <= cached_id


__all__ = [
    "SimulationContentCache",
    "load_setup_cache",
    "save_setup_cache",
    "is_cache_complete",
]
