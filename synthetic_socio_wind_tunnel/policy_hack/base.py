"""
Policy-Hack 基础抽象：Variant / PhaseController / VariantContext /
VariantRunnerAdapter。

职责分层：
- `Variant`: 单个干预的行为 + 元数据载体（ABC + Pydantic 混合）
- `PhaseController`: 14 天 protocol 的 baseline / intervention / post 切换
- `VariantContext`: 每日 hook 被调用时变体能访问的运行时数据
- `VariantRunnerAdapter`: 把 variant + controller 挂到 MultiDayRunner 的
  `on_day_start` 钩子，内部负责 phase 判断与阶段转换触发

Variant 生命周期（adapter 触发）：
    run 前       variant.apply_population(profiles, rng)
    day_index=0..(B-1)    （baseline；无调用）
    day_index=B           variant.apply_intervention_start(ctx)  # 首次进入
                          variant.apply_day_start(ctx)            # 每日
    day_index=B+1..(B+I-1) variant.apply_day_start(ctx)           # 每日
    day_index=B+I         variant.apply_intervention_end(ctx)    # 退出
    day_index=B+I..end    （post；无调用）

B = baseline_days, I = intervention_days。

承诺：整个 policy-hack 模块零 LLM 调用（feed 内容模板化 + RNG 可复现）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date as _date
from random import Random
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.agent.profile import AgentProfile
    from synthetic_socio_wind_tunnel.agent.runtime import AgentRuntime
    from synthetic_socio_wind_tunnel.attention.service import AttentionService
    from synthetic_socio_wind_tunnel.ledger import Ledger
    from synthetic_socio_wind_tunnel.orchestrator.multi_day import MultiDayRunner


Hypothesis = Literal["H_info", "H_pull", "H_meaning", "H_structure"]
ChainPosition = Literal[
    "algorithmic-input",
    "attention-main",
    "spatial-output",
    "social-downstream",
]
Phase = Literal["baseline", "intervention", "post"]


# ---------------------------------------------------------------------------
# Phase controller
# ---------------------------------------------------------------------------

class PhaseController(BaseModel):
    """
    14-day protocol 的三段切换。默认 4/6/4；dev mode 用 (1,1,1) 压缩 3 天。
    """

    model_config = ConfigDict(frozen=True)

    baseline_days: int = Field(default=4, ge=0)
    intervention_days: int = Field(default=6, ge=0)
    post_days: int = Field(default=4, ge=0)

    @property
    def total_days(self) -> int:
        return self.baseline_days + self.intervention_days + self.post_days

    def phase(self, day_index: int) -> Phase:
        if day_index < self.baseline_days:
            return "baseline"
        if day_index < self.baseline_days + self.intervention_days:
            return "intervention"
        return "post"

    def is_active(self, day_index: int) -> bool:
        """intervention phase 期间 variant 施加干预。"""
        return self.phase(day_index) == "intervention"

    def is_first_intervention_day(self, day_index: int) -> bool:
        return (self.intervention_days > 0
                and day_index == self.baseline_days)

    def is_first_post_day(self, day_index: int) -> bool:
        return (self.post_days > 0
                and day_index == self.baseline_days + self.intervention_days)


# ---------------------------------------------------------------------------
# VariantContext
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VariantContext:
    """
    Variant 生命周期 hook 收到的运行时上下文。

    frozen 容器阻止 variant 换成员；但容器内的 mutable 对象
    (AttentionService / Ledger / AgentRuntime) 可被调用方法来产生副作用，
    这是 variant 施加干预的唯一合法路径。
    """

    day_index: int
    simulated_date: _date
    phase: Phase
    ledger: "Ledger"
    attention_service: "AttentionService | None"
    runtimes: tuple["AgentRuntime", ...]
    rng: Random
    seed: int


# ---------------------------------------------------------------------------
# Variant base
# ---------------------------------------------------------------------------

class _VariantMeta(type(BaseModel), type(ABC)):  # type: ignore[misc]
    """合并 Pydantic 与 ABC 的 metaclass。"""


class Variant(BaseModel, ABC, metaclass=_VariantMeta):
    """
    干预变体基类。具体 variant 子类 SHALL：
    - 填元数据字段（name / hypothesis / lineage / 判据 / chain / mirror）
    - override `apply_day_start`（必须）
    - 可选 override `apply_population` / `apply_intervention_start` /
      `apply_intervention_end`

    与 `experimental-design` spec 的 Rival Hypothesis framing 对齐。
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    # --- Metadata (spec required) ---
    name: str
    hypothesis: Hypothesis
    theoretical_lineage: str
    success_criterion: str
    failure_criterion: str
    chain_position: ChainPosition
    is_mirror: bool = False
    paired_variant: str | None = None

    # --- Lifecycle hooks ---

    def apply_population(
        self,
        profiles: list["AgentProfile"],
        rng: Random,
    ) -> list["AgentProfile"]:
        """
        一次性 population 改写（run 前）。默认返回原 list。
        D (Catalyst Seeding) override；其它 variant 不用。
        """
        return profiles

    def apply_intervention_start(self, ctx: VariantContext) -> None:
        """
        Intervention 阶段**首日**调用（早于同日的 apply_day_start）。默认
        no-op。B (Phone Friction) 用它缓存 + 施加一次性改动；
        C (Shared Anchor) 用它挑当期 task。
        """

    @abstractmethod
    def apply_day_start(self, ctx: VariantContext) -> None:
        """Intervention 每日开始调用。A / A' / C 的每日 push 在此发生。"""

    def apply_intervention_end(self, ctx: VariantContext) -> None:
        """
        进入 post 阶段**首日**调用（intervention 结束）。默认 no-op。
        B (Phone Friction) 用它恢复原 profile。
        """

    # --- Metadata serialization ---

    def metadata_dict(self) -> dict[str, Any]:
        """序列化为 MultiDayResult.metadata.variant_metadata 用。"""
        return {
            "name": self.name,
            "hypothesis": self.hypothesis,
            "theoretical_lineage": self.theoretical_lineage,
            "success_criterion": self.success_criterion,
            "failure_criterion": self.failure_criterion,
            "chain_position": self.chain_position,
            "is_mirror": self.is_mirror,
            "paired_variant": self.paired_variant,
        }


# ---------------------------------------------------------------------------
# VariantRunnerAdapter
# ---------------------------------------------------------------------------

class VariantRunnerAdapter:
    """
    Variant + PhaseController → MultiDayRunner 的 on_day_start 回调。

    典型用法：
        variant = HyperlocalPushVariant(...)
        controller = PhaseController()
        adapter = VariantRunnerAdapter(variant, controller, seed=42)

        # D variant 在此处改 population；其它 variant 返回原 list
        profiles = adapter.setup_run(profiles, rng=Random(42))

        # 构造 orchestrator（用修改后的 profiles 构造 runtimes）+ runner
        ...

        adapter.attach_to(runner)
        runner.run_multi_day(
            ...,
            on_day_start=adapter.on_day_start,
        )
    """

    __slots__ = ("_variant", "_controller", "_seed", "_attached_runner")

    def __init__(
        self,
        variant: Variant,
        controller: PhaseController,
        *,
        seed: int = 0,
    ) -> None:
        self._variant = variant
        self._controller = controller
        self._seed = seed
        self._attached_runner: "MultiDayRunner | None" = None

    @property
    def variant(self) -> Variant:
        return self._variant

    @property
    def controller(self) -> PhaseController:
        return self._controller

    def setup_run(
        self,
        profiles: list["AgentProfile"],
        rng: Random,
    ) -> list["AgentProfile"]:
        """Run 前一次性改人群。调用方必须在构造 orchestrator 前使用。"""
        return self._variant.apply_population(profiles, rng)

    def attach_to(self, runner: "MultiDayRunner") -> None:
        """
        记录 runner 引用；之后将 `self.on_day_start` 作为 callback 传给
        `runner.run_multi_day(on_day_start=...)`。

        同一 adapter 只能 attach 一次。
        """
        if self._attached_runner is not None:
            raise RuntimeError(
                "VariantRunnerAdapter already attached; "
                "construct a new one per run."
            )
        self._attached_runner = runner

    def on_day_start(self, current_date: _date, day_index: int) -> None:
        """
        Callback 传给 `MultiDayRunner.run_multi_day(on_day_start=...)`。

        每日决策：
        - 若是 intervention 首日：先 `apply_intervention_start` 再
          `apply_day_start`
        - 若是 intervention 中间 / 末日：`apply_day_start`
        - 若是 post 首日：`apply_intervention_end`
        - 其它：no-op（baseline 全期、post 非首日）
        """
        if self._attached_runner is None:
            raise RuntimeError("call attach_to(runner) before on_day_start")

        ctx = self._build_ctx(current_date, day_index)
        controller = self._controller
        variant = self._variant

        if controller.is_active(day_index):
            if controller.is_first_intervention_day(day_index):
                variant.apply_intervention_start(ctx)
            variant.apply_day_start(ctx)
        elif controller.is_first_post_day(day_index):
            variant.apply_intervention_end(ctx)

    def augment_result_metadata(self, result: Any) -> None:
        """
        把 variant / phase / seed 信息写入 `MultiDayResult.metadata` dict。
        dataclass `frozen=True` 只阻止 field 重赋值；dict 内容仍可原地
        更新——用这个通道把 variant 身份落到 result 里，供下游 `metrics`
        change 消费。

        调用方在 `runner.run_multi_day(...)` 返回之后一次性调用即可。
        """
        metadata = result.metadata  # dict 是 field 的引用；原地 update 合法
        metadata["variant_metadata"] = self._variant.metadata_dict()
        metadata["phase_config"] = self._controller.model_dump()
        metadata["seed"] = self._seed

    # ---- internals ----

    def _build_ctx(
        self, current_date: _date, day_index: int,
    ) -> VariantContext:
        assert self._attached_runner is not None
        orch = self._attached_runner._orchestrator  # type: ignore[attr-defined]
        return VariantContext(
            day_index=day_index,
            simulated_date=current_date,
            phase=self._controller.phase(day_index),
            ledger=orch._ledger,  # type: ignore[attr-defined]
            attention_service=orch._attention_service,  # type: ignore[attr-defined]
            runtimes=tuple(orch._agents),  # type: ignore[attr-defined]
            rng=Random(self._seed + day_index * 17 + 1),
            seed=self._seed,
        )


__all__ = [
    "ChainPosition",
    "Hypothesis",
    "Phase",
    "PhaseController",
    "Variant",
    "VariantContext",
    "VariantRunnerAdapter",
]
