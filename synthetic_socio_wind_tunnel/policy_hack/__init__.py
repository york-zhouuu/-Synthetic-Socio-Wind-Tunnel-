"""
Policy-Hack — 干预变体工具箱

4 条 primary variant 绑定 4 个 rival hypothesis（见 `experimental-design`
spec + `docs/agent_system/13-research-design.md` Part II）+ 1 条 paired
mirror 证明 dual-use。

主要导出：
- `Variant` / `PhaseController` / `VariantContext` / `VariantRunnerAdapter`
  — 框架层
- 5 个具体 variant 类
- `VARIANTS` registry — CLI dispatch 用

承诺：整模块零 LLM 调用（feed 内容模板化 + RNG 可复现）。
"""

from synthetic_socio_wind_tunnel.policy_hack.base import (
    ChainPosition,
    Hypothesis,
    Phase,
    PhaseController,
    Variant,
    VariantContext,
    VariantRunnerAdapter,
)
from synthetic_socio_wind_tunnel.policy_hack.variants import (
    CatalystSeedingVariant,
    GlobalDistractionVariant,
    HyperlocalPushVariant,
    PhoneFrictionVariant,
    SharedAnchorVariant,
)


VARIANTS: dict[str, type[Variant]] = {
    "hyperlocal_push": HyperlocalPushVariant,
    "global_distraction": GlobalDistractionVariant,
    "phone_friction": PhoneFrictionVariant,
    "shared_anchor": SharedAnchorVariant,
    "catalyst_seeding": CatalystSeedingVariant,
}
"""name → Variant 子类。CLI 按 `--variant <name>` 查表实例化。"""


__all__ = [
    # Framework
    "ChainPosition",
    "Hypothesis",
    "Phase",
    "PhaseController",
    "Variant",
    "VariantContext",
    "VariantRunnerAdapter",
    # Concrete variants
    "CatalystSeedingVariant",
    "GlobalDistractionVariant",
    "HyperlocalPushVariant",
    "PhoneFrictionVariant",
    "SharedAnchorVariant",
    # Registry
    "VARIANTS",
]
