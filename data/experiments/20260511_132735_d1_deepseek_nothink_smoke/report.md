# d1_deepseek_nothink_smoke — Rival Hypothesis Contest Report


> ⚠️ **[unpublishable preview]** — at least one hard check fails or has not been run.

<!-- auto-generated from ReportWriter.write_markdown -->

本报告遵循 `experimental-design` spec 的五幕结构 + 每 variant Diagnosis-Cure-Outcome-Interpretation 四段式。数字来自 `SuiteAggregate` / `ContestReport` 自动填；Interpretation 段留作者判读。

## Research Posture Statement

> 本项目是探索性研究装置，类比物理学的云室（cloud chamber）——让"注意力位移
> 造成的附近性盲区"这一社会现象在合成 agent 上可观察、可拆解；**不主张
> 任何真实世界部署**。
>
> 工具本身的对称性使其既可用于促进本地连接，也可用于放大孤立；我们的
> mirror experiment 显式展示这一 dual-use 属性。
>
> 部署需要居民同意、透明治理、反馈机制——这些在本项目 scope 之外。


## Publishable Checklist

- ⚠️ **#1 Calibration**: population=best-effort ✓; behavioral pending (ABS Travel Survey + Popular Times data not yet shipped)
    - population disclose: work_mode below threshold
- ⚠️ **#2 Stereotype audit**: dev mode only — not valid for publishable claim.
- ✓ **#4 Mirror experiment included** (suite contains global_distraction)
- ✓ **#5 Forbidden words check** (auto-enforced)
- ✓ **#8 Acceptance language compliant** (auto-enforced)
- ✓ **#6 Reproducibility lock**: 7 fields stamped
- ✓ **#7 Ethics statement**: auto-injected from `metrics/ethics.py::ETHICS_STATEMENT`
- ✓ **#3 Face validity**: avg=3.91, pct_low=14.5%, n_reviewers=20


### Reproducibility Lock

| field | value |
|---|---|
| seed_pool | `[42]` |
| model_version | `deepseek:v4-pro+...` |
| prompt_template_hash | `stub:baseline` |
| LANE_COVE_PROFILE_hash | `71b4ea04d57a4b9d...` |
| variants_loaded | `baseline=8ba8496a...` |
| code_commit | `7a62a8ebf321a1b4...` |
| phase_config | `baseline_days=4, intervention_days=6, post_days=4` |


## Act 1 — Baseline

<!-- auto-generated from variant_baseline/aggregate.json; seeds=1 -->

**Diagnosis** (baseline scene): Lane Cove 社区原始状态下 14 天的活动。

**Outcome** (auto-filled):

- encounter density (per-day median): 84160.50 95% CI [84160.50, 84160.50]
- seeds: 1 **[preliminary — below β rigor 30]**

**Interpretation** (author fills):

> 待作者：描述 baseline 状态，对 "附近性盲区" 的直觉观察 ≤ 200 字。


## Act 2 — Four Doctors

### Variant: hyperlocal_push (H_info)

<!-- auto-generated from variant_hyperlocal_push/aggregate.json; seeds=1 -->

**Diagnosis** (theoretical lineage): Shannon 信息论 + Wu《Attention Merchants》：注意力稀缺假设——附近可被感知的信号不足，平台提供高质量 hyperlocal 内容可补足。

**Cure** (operationalization):

- variant name: `hyperlocal_push`
- chain position: `algorithmic-input`

**Outcome** (auto-filled):

- primary metric `trajectory_deviation_m`: 187.88 95% CI [187.88, 187.88]
- encounter (per-day median): 83660.50 95% CI [83660.50, 83660.50]
- evidence alignment: **inconclusive**
- reviewer notes: inconclusive: CI overlap between variant and reference for trajectory_deviation_m [preliminary—seed count < 30]
- **⚠️ preliminary — seed count < 30**

**Interpretation** (author fills):

> 待作者（基于 Outcome 数字，对 `H_info`
> 的弱支持 / 弱证伪判读；对照 success_criterion / failure_criterion）：
>
> - success_criterion: target agents 的 trajectory 在 intervention 期间向 target_location 偏移（median delta > 100m）；encounter 密度上升。Evidence consistent with H_info.
> - failure_criterion: target 与 control 之间无显著 delta（IQR 重叠）；或效果衰减在 3 天内。Not consistent with H_info.

### Variant: global_distraction (H_info)

<!-- auto-generated from variant_global_distraction/aggregate.json; seeds=1 -->

**Diagnosis** (theoretical lineage): 同 A (HyperlocalPush) — Shannon/Wu attention economy；但反向操作：饱和 global-news 侵占 agent 注意力。证明工具 dual-use 属性。

**Cure** (operationalization):

- variant name: `global_distraction`
- ⚠️ this is a **paired mirror** of `hyperlocal_push`
- chain position: `algorithmic-input`

**Outcome** (auto-filled):

- primary metric `trajectory_deviation_m`: 232.04 95% CI [232.04, 232.04]
- encounter (per-day median): 78961.00 95% CI [78961.00, 78961.00]
- mirror delta vs `hyperlocal_push`: 44.16
- evidence alignment: **inconclusive**
- reviewer notes: inconclusive: CI overlap between variant and reference for trajectory_deviation_m [preliminary—seed count < 30]
- **⚠️ preliminary — seed count < 30**

**Interpretation** (author fills):

> 待作者（基于 Outcome 数字，对 `H_info`
> 的弱支持 / 弱证伪判读；对照 success_criterion / failure_criterion）：
>
> - success_criterion: target agents 相比 control 的 trajectory 更固化（熵下降）；encounter 密度下降；附近盲区加深。Evidence consistent with H_info 的反向（即 hyperlocal 信号不足确实是 binding constraint）。
> - failure_criterion: 无论推多少 global-news，agent 行为与 control 无异——说明 routine 主导行为（H_pull 或 H_structure 可能更重要）。

### Variant: phone_friction (H_pull)

<!-- auto-generated from variant_phone_friction/aggregate.json; seeds=1 -->

**Diagnosis** (theoretical lineage): Simon 注意力稀缺 + Wu《Attention Merchants》：手机商业模式过度索取注意力；降低 pull 能让人自发回到附近。

**Cure** (operationalization):

- variant name: `phone_friction`
- chain position: `attention-main`

**Outcome** (auto-filled):

- primary metric `encounter.per_day_median`: 87181.50 95% CI [87181.50, 87181.50]
- encounter (per-day median): 87181.50 95% CI [87181.50, 87181.50]
- evidence alignment: **consistent**
- reviewer notes: evidence consistent with H_pull: primary metric encounter.per_day_median CI above baseline CI [preliminary—seed count < 30]
- **⚠️ preliminary — seed count < 30**

**Interpretation** (author fills):

> 待作者（基于 Outcome 数字，对 `H_pull`
> 的弱支持 / 弱证伪判读；对照 success_criterion / failure_criterion）：
>
> - success_criterion: Friction 期间 agents 的 AttentionState.allocation 'physical_world' 占比上升；空间探索熵上升；encounter 密度上升。Evidence consistent with H_pull.
> - failure_criterion: Friction 无显著行为变化（allocation 分布 IQR 重叠）；或效果仅在 friction 期间，post 立刻回归。Not consistent with H_pull.


## Act 3 — The Contest

<!-- auto-generated from contest.json; 4 rows -->

| variant | hypothesis | primary metric | effect size | 95% CI | baseline | alignment | mirror Δ |
|---|---|---|---|---|---|---|---|
| `baseline` | — | encounter.per_day_median | 84160.50 | 95% CI [84160.50, 84160.50] | 84160.50 | **inconclusive** | — |
| `hyperlocal_push` | H_info | trajectory_deviation_m | 187.88 | 95% CI [187.88, 187.88] | — | **inconclusive** | — |
| `global_distraction` | H_info | trajectory_deviation_m | 232.04 | 95% CI [232.04, 232.04] | — | **inconclusive** | 44.16 |
| `phone_friction` | H_pull | encounter.per_day_median | 87181.50 | 95% CI [87181.50, 87181.50] | 84160.50 | **consistent** | — |

**Interpretation** (author fills): 判读哪条 rival hypothesis 得到最强 consistent evidence；指出 inconclusive 条的可能原因（sample size / effect 过弱 / 假设机制不对）。


## Act 4 — Decay

<!-- auto-generated from per_day_time_series encounter_count_per_day -->

| variant | intervention-end median | post-end median | decay ratio |
|---|---|---|---|
| `baseline` | 79745.00 | 82072.00 | 1.03 |
| `hyperlocal_push` | 83701.00 | 80250.00 | 0.96 |
| `global_distraction` | 73681.00 | 76781.00 | 1.04 |
| `phone_friction` | 96454.00 | 110361.00 | 1.14 |

**Interpretation** (author fills): 哪些 variant 在 post phase 留下持久改变（decay ratio 接近 1）；哪些是一次性反应（decay 接近 baseline）。


## Act 5 — The Mirror

<!-- auto-generated from paired-mirror rows from contest -->

- `global_distraction` vs `hyperlocal_push`: mirror delta = +44.16

**Interpretation** (author fills): mirror 的 effect size 是否对称（工具 dual-use 的强证据）？或 asymmetric（说明 attention channel 有偏好方向）？