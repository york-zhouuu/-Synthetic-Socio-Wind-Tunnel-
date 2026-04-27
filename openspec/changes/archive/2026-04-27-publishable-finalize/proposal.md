## Why

Publishable checklist 还差两项 ⚠️：

- **#6 Reproducibility lock**：validation-strategy Part VI 规定 7 个字段
  （seed_pool / model_version / prompt_template_hash / LANE_COVE_PROFILE_hash /
  variants_loaded / code_commit / phase_config）必须 stamp 到每个
  publishable run 的 metadata。当前只有 phase_config 实现，3/7 部分实现。

- **#7 Ethics Statement**：research-design Part V 写了完整 ethics
  statement，但 report.md 不自动注入。

两个都是纯工程小活，逻辑相邻（都是 publishable artifact metadata），合
为一个 change `publishable-finalize`。

**Chain-Position**: `infrastructure`
**前置**：`agent-calibration` + `agent-profile-enrich` + `stereotype-audit`
（已 archive）

## What Changes

### 1. Reproducibility lock 7 字段（validation-strategy Part VI）

新增 helper `synthetic_socio_wind_tunnel/metrics/reproducibility.py`：

```python
def compute_reproducibility_lock(
    seed_pool: list[int],
    use_real_llm: bool,
    variant_names: list[str],
    phase_config: dict,
) -> dict[str, Any]:
    return {
        "seed_pool": seed_pool,
        "model_version": _resolve_model_version(use_real_llm),
        "prompt_template_hash": _hash_prompt_template(),
        "LANE_COVE_PROFILE_hash": _hash_profile(LANE_COVE_PROFILE),
        "variants_loaded": _hash_variants(variant_names),
        "code_commit": _git_rev_parse_head(),
        "phase_config": phase_config,
    }
```

7 字段全填到 `RunMetrics.extensions` + `SuiteAggregate` metadata + report.md
顶部 metadata block。

### 2. Ethics Statement 自动注入（research-design Part V）

`metrics/report.py` 在 publishable banner 之后、checklist 之前注入：

```markdown
## Research Posture Statement

> 本项目是探索性研究装置，类比物理学的云室——让"注意力位移造成的附近性
> 盲区"这一社会现象在合成 agent 上可观察、可拆解；**不主张任何真实世界
> 部署**。工具本身的对称性使其既可用于促进本地连接，也可用于放大孤立；
> 我们的 mirror experiment 显式展示这一 dual-use 属性。部署需要居民同意、
> 透明治理、反馈机制——这些在本项目 scope 之外。
```

文本作为常量存 `metrics/ethics.py`（避免 doc-code 漂移）；report 直接
import 并注入。

### 3. 接入 publishable suite report

- `tools/run_variant_suite.py` 调 `compute_reproducibility_lock` →
  把 7 字段塞进 each run 的 RunMetrics + suite-level metadata
- `metrics/report.py::write_markdown` 加 reproducibility block + ethics
  block；checklist #6/#7 自动从 ⚠️ → ✓

### 4. 测试

- `tests/test_reproducibility.py`：
  - 7 字段全填齐
  - prompt_template_hash 是 stub:variant_name 在 stub mode
  - prompt_template_hash 是 sha256 in real mode
  - LANE_COVE_PROFILE_hash 改 PROFILE 后 hash 变
  - code_commit 当 git 不可用时 fallback 为 "unknown"
- `tests/test_metrics_report.py` 扩展：
  - report.md 含 ethics statement section
  - report.md 含 reproducibility block

## Non-goals

- **不**做 face-validity-protocol（独立 change）
- **不**做 model-budget cost cap（脱离 publishable 收尾范畴）
- **不**实施 seed_pool 自动 audit（spec 只规定 stamp，不规定验证）
- **不**改 agent / Planner / orchestrator 行为契约

## Capabilities

### Modified Capabilities

- `validation-strategy`：Part VI 七字段实施 + Part V Ethics 自动注入
  落地（从 doc 提升到 spec scenario）

### New Capabilities

（无）

## Impact

- **修改文件**：
  - `synthetic_socio_wind_tunnel/metrics/report.py`（注入 ethics + rep
    lock block）
  - `tools/run_variant_suite.py`（计算 + 塞入 7 字段）
- **新增文件**：
  - `synthetic_socio_wind_tunnel/metrics/reproducibility.py`
  - `synthetic_socio_wind_tunnel/metrics/ethics.py`
  - `tests/test_reproducibility.py`
- **不改**：agent / Planner / AgentRuntime / cartography 公共契约
- **预计周期**：0.5 day
- **下游影响**：publishable checklist #6 ⚠️ → ✓；#7 ⚠️ → ✓
- **回滚**：删 reproducibility.py + ethics.py + git revert run_variant_suite +
  metrics/report
