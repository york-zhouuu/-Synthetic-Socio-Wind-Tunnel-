"""
StubReplanLLM — 零成本、seed-reproducible 的 replan 客户端

按 `variant_name` 分派行为（设计 D2）：
- `hyperlocal_push`  → 1 条 PlanStep 走向 target_location（模拟注意力被
                       拉向推送地点）
- `global_distraction` → `"[]"` 空 plan（证明 global news 不拉 scripted agent）
- `shared_anchor`    → 1 条 PlanStep 走向 community heuristic location
- 其它 / 未知        → `"[]"` 空 plan（Planner.replan 内部 fallback 保持原 plan）

不解析 prompt 内容——variant_name 在构造时注入。

也提供 `_AnthropicClient` 作为 `--use-real-llm` opt-in 时的 drop-in（无
retry / cost 控制；model-budget 未来 change 的事）。
"""

from __future__ import annotations

import json
import os
import sys
from random import Random
from typing import Any

# 允许 anthropic 可选
try:
    from anthropic import Anthropic  # type: ignore[import-not-found]
    _HAS_ANTHROPIC = True
except ImportError:
    _HAS_ANTHROPIC = False


# -----------------------------------------------------------------------------
# Community heuristic location picker
# -----------------------------------------------------------------------------

def _pick_community_location(
    atlas, destinations: tuple[str, ...],
) -> str | None:
    """
    shared_anchor variant 的 target heuristic：
    优先 park / plaza；无则 destinations[0]；都没有返 None
    """
    if atlas is None:
        return destinations[0] if destinations else None
    try:
        area_ids = atlas.list_outdoor_areas()
    except Exception:
        return destinations[0] if destinations else None
    for aid in area_ids:
        try:
            area = atlas.get_outdoor_area(aid)
        except Exception:
            continue
        if area is None:
            continue
        if area.area_type in ("park", "plaza", "square"):
            return area.id
    return destinations[0] if destinations else None


# -----------------------------------------------------------------------------
# Plan-toward helper
# -----------------------------------------------------------------------------

def _plan_toward(
    destination: str, *, rng: Random,
) -> str:
    """生成一条走向 destination 的 PlanStep JSON（Planner._parse_plan 兼容）。"""
    # 随机时间避免所有 agent 同 tick 集中
    hour = 10 + rng.randint(0, 4)
    minute = rng.choice([0, 15, 30, 45])
    steps: list[dict[str, Any]] = [
        {
            "time": f"{hour}:{minute:02d}",
            "action": "move",
            "destination": destination,
            "activity": f"走向推荐地点 {destination}",
            "duration_minutes": 45,
            "reason": "被 hyperlocal 推送吸引",
            "social_intent": "open_to_chat",
        },
    ]
    return json.dumps(steps, ensure_ascii=False)


# -----------------------------------------------------------------------------
# StubReplanLLM — variant-aware dispatch
# -----------------------------------------------------------------------------

class StubReplanLLM:
    """
    零 LLM 成本的 replan 客户端。符合 `Planner` 的 `LLMClient` 协议
    （`async generate(prompt, *, model, **_) -> str`）。

    dispatch 表：
        hyperlocal_push   → _plan_toward(target_location)
        global_distraction → "[]"
        shared_anchor     → _plan_toward(community_heuristic)
        phone_friction / catalyst_seeding / baseline / 未知 → "[]"
    """

    __slots__ = ("_seed", "_variant_name", "_target_location", "_shared_location",
                 "_call_counter")

    def __init__(
        self,
        *,
        seed: int,
        variant_name: str,
        target_location: str | None = None,
        shared_location: str | None = None,
    ) -> None:
        self._seed = seed
        self._variant_name = variant_name
        self._target_location = target_location
        self._shared_location = shared_location or target_location
        self._call_counter = 0

    async def generate(
        self, prompt: str, *, model: str = "", **_: Any,
    ) -> str:
        # 每次 generate 用独立 rng（seed + call_counter）；保证同 seed 同调用
        # 序列下输出 byte-equal
        self._call_counter += 1
        rng = Random(self._seed * 1000 + self._call_counter)

        name = self._variant_name
        if name == "hyperlocal_push":
            if self._target_location:
                return _plan_toward(self._target_location, rng=rng)
        elif name == "global_distraction":
            return "[]"
        elif name == "shared_anchor":
            if self._shared_location:
                return _plan_toward(self._shared_location, rng=rng)
        # phone_friction / catalyst_seeding / baseline / unknown
        return "[]"


# -----------------------------------------------------------------------------
# Real Anthropic client (最小 wrap)
# -----------------------------------------------------------------------------

class _AnthropicClient:
    """
    --use-real-llm 下的真 Anthropic 客户端。最小实现：无 retry、无 cost
    预算、无 rate limit。Haiku 默认。

    未来 model-budget change 会替换为更完整的客户端。
    """

    def __init__(self, *, model: str = "claude-haiku-4-5-20251001") -> None:
        if not _HAS_ANTHROPIC:
            raise RuntimeError(
                "anthropic SDK not installed; `--use-real-llm` needs "
                "`pip install anthropic`"
            )
        self._client = Anthropic()
        self._model = model

    async def generate(
        self, prompt: str, *, model: str = "", **_: Any,
    ) -> str:
        used_model = model or self._model
        # 同步调用（Anthropic SDK 有 sync API；wrap in async 只是协议匹配）
        response = self._client.messages.create(
            model=used_model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        # 提取文本 block
        text_parts: list[str] = []
        for block in response.content:
            if hasattr(block, "text"):
                text_parts.append(block.text)
        return "".join(text_parts)


# -----------------------------------------------------------------------------
# Factory
# -----------------------------------------------------------------------------

def make_llm_client(
    *,
    use_real: bool,
    variant_name: str,
    seed: int,
    target_location: str | None = None,
    shared_location: str | None = None,
):
    """构造 Planner 用的 LLMClient；--use-real-llm 路径走 Anthropic。"""
    if use_real:
        if not _HAS_ANTHROPIC:
            sys.stderr.write(
                "error: --use-real-llm requires `pip install anthropic`\n"
            )
            sys.exit(2)
        # anthropic key via env
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.stderr.write(
                "error: --use-real-llm requires ANTHROPIC_API_KEY in env\n"
            )
            sys.exit(2)
        return _AnthropicClient()
    return StubReplanLLM(
        seed=seed,
        variant_name=variant_name,
        target_location=target_location,
        shared_location=shared_location,
    )


__all__ = [
    "StubReplanLLM",
    "make_llm_client",
    "_pick_community_location",
    "_plan_toward",
]
