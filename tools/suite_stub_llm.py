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

# 允许 google-genai 可选
try:
    from google import genai  # type: ignore[import-not-found]
    from google.genai import types as genai_types  # type: ignore[import-not-found]
    _HAS_GEMINI = True
except ImportError:
    _HAS_GEMINI = False


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
    --use-real-llm + provider=anthropic 下的真 Anthropic 客户端。最小实现：
    无 retry、无 cost 预算、无 rate limit。Haiku 默认。

    未来 model-budget change 会替换为更完整的客户端。
    """

    def __init__(self, *, model: str = "claude-haiku-4-5-20251001") -> None:
        if not _HAS_ANTHROPIC:
            raise RuntimeError(
                "anthropic SDK not installed; `--use-real-llm` with "
                "provider=anthropic needs `pip install anthropic`"
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


class _GeminiClient:
    """
    --use-real-llm + provider=gemini 下的真 Gemini 客户端。

    默认 gemini-3-flash-preview + thinking 关闭（thinking_budget=0），追求
    速度与低成本——agent.replan 不需要长链推理。

    使用 Gemini 的 structured output 模式（response_schema）强制 JSON +
    Literal 词汇——避免 prompt 里 "请输出 action='move'/'stay'/..." 不被
    遵守的实际问题（实测 Gemini 3 会自由发挥成 "visit"/"work" 等）。

    无 retry / cost 控制；与 _AnthropicClient 同等地"最小实现"。
    """

    def __init__(
        self,
        *,
        model: str = "gemini-3-flash-preview",
        enable_thinking: bool = False,
    ) -> None:
        if not _HAS_GEMINI:
            raise RuntimeError(
                "google-genai SDK not installed; `--use-real-llm` with "
                "provider=gemini needs `pip install google-genai`"
            )
        # 自动从 GEMINI_API_KEY / GOOGLE_API_KEY env 读取
        self._client = genai.Client()
        self._model = model
        self._enable_thinking = enable_thinking
        self._plan_schema = _build_plan_schema()

    async def generate(
        self, prompt: str, *, model: str = "", **_: Any,
    ) -> str:
        # Planner 默认会传 profile.base_model（如 "claude-haiku-..."），
        # Gemini SDK 拿到这个名字会 404。这里**忽略外部传入的 model**——
        # Gemini client 只负责发到自己的 self._model。
        # 真正的"per-agent 模型分派"是未来 model-budget change 的事。
        used_model = self._model

        # Structured output：response_mime_type=json + schema = list[PlanStep]
        # → Gemini 必须返回符合 schema 的 JSON
        config_kwargs: dict[str, Any] = {
            "response_mime_type": "application/json",
            "response_schema": self._plan_schema,
        }
        if not self._enable_thinking:
            config_kwargs["thinking_config"] = genai_types.ThinkingConfig(
                thinking_budget=0,
            )

        response = self._client.models.generate_content(
            model=used_model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(**config_kwargs),
        )
        return response.text or ""


def _build_plan_schema():
    """
    构造 Gemini structured output 用的 schema：list[PlanStep]，含 Literal
    枚举强制 action / social_intent 词汇。

    与 synthetic_socio_wind_tunnel.agent.planner.PlanStep 字段一致；不直接
    复用 Pydantic 类，因为 Gemini 的 schema 转换对 Literal | None 处理
    不一致——手写更可控。
    """
    return genai_types.Schema(
        type=genai_types.Type.ARRAY,
        items=genai_types.Schema(
            type=genai_types.Type.OBJECT,
            properties={
                "time": genai_types.Schema(type=genai_types.Type.STRING),
                "action": genai_types.Schema(
                    type=genai_types.Type.STRING,
                    enum=["move", "stay", "interact", "explore"],
                ),
                "destination": genai_types.Schema(
                    type=genai_types.Type.STRING,
                    nullable=True,
                ),
                "activity": genai_types.Schema(type=genai_types.Type.STRING),
                "duration_minutes": genai_types.Schema(
                    type=genai_types.Type.INTEGER,
                ),
                "reason": genai_types.Schema(type=genai_types.Type.STRING),
                "social_intent": genai_types.Schema(
                    type=genai_types.Type.STRING,
                    enum=["alone", "open_to_chat", "seeking_company"],
                ),
            },
            required=[
                "time", "action", "activity", "duration_minutes",
                "reason", "social_intent",
            ],
        ),
    )


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
    provider: str = "auto",
    gemini_model: str = "gemini-3-flash-preview",
    anthropic_model: str = "claude-haiku-4-5-20251001",
    enable_thinking: bool = False,
):
    """
    构造 Planner 用的 LLMClient。

    `provider` 选项：
      - "auto"      → 检 env：GEMINI_API_KEY 优先 / ANTHROPIC_API_KEY 次之
      - "gemini"    → 强制 Gemini（gemini-3-flash-preview 默认；thinking 关闭）
      - "anthropic" → 强制 Anthropic Haiku
      - "stub"      → 强制 stub（等价 use_real=False）
    """
    if not use_real or provider == "stub":
        return StubReplanLLM(
            seed=seed,
            variant_name=variant_name,
            target_location=target_location,
            shared_location=shared_location,
        )

    # auto-detect
    if provider == "auto":
        if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
            provider = "gemini"
        elif os.environ.get("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        else:
            sys.stderr.write(
                "error: --use-real-llm with provider=auto requires "
                "GEMINI_API_KEY or ANTHROPIC_API_KEY in env\n"
            )
            sys.exit(2)

    if provider == "gemini":
        if not _HAS_GEMINI:
            sys.stderr.write(
                "error: provider=gemini requires `pip install google-genai`\n"
            )
            sys.exit(2)
        if not (os.environ.get("GEMINI_API_KEY")
                or os.environ.get("GOOGLE_API_KEY")):
            sys.stderr.write(
                "error: provider=gemini requires GEMINI_API_KEY in env\n"
            )
            sys.exit(2)
        return _GeminiClient(
            model=gemini_model,
            enable_thinking=enable_thinking,
        )

    if provider == "anthropic":
        if not _HAS_ANTHROPIC:
            sys.stderr.write(
                "error: provider=anthropic requires `pip install anthropic`\n"
            )
            sys.exit(2)
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.stderr.write(
                "error: provider=anthropic requires ANTHROPIC_API_KEY in env\n"
            )
            sys.exit(2)
        return _AnthropicClient(model=anthropic_model)

    sys.stderr.write(f"error: unknown llm provider: {provider!r}\n")
    sys.exit(2)


__all__ = [
    "StubReplanLLM",
    "make_llm_client",
    "_pick_community_location",
    "_plan_toward",
]
