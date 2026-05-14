# publishable_real_llm_v1 — Rival Hypothesis Contest Report


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
| seed_pool | `[42, 43]` |
| model_version | `real_llm:unknown` |
| prompt_template_hash | `653dd79e09237a9f...` |
| LANE_COVE_PROFILE_hash | `71b4ea04d57a4b9d...` |
| variants_loaded | `baseline=8ba8496a...` |
| code_commit | `fb95b495d33b21bb...` |
| phase_config | `baseline_days=4, intervention_days=,, post_days=6` |


## Act 1 — Baseline

<!-- auto-generated from variant_baseline/aggregate.json; seeds=2 -->

**Diagnosis** (baseline scene): Lane Cove 社区原始状态下 14 天的活动。

**Outcome** (auto-filled):

- encounter density (per-day median): 1585.50 95% CI [1030.22, 2140.77]
- seeds: 2 **[preliminary — below β rigor 30]**

**Interpretation** (author fills):

> 待作者：描述 baseline 状态，对 "附近性盲区" 的直觉观察 ≤ 200 字。


## Act 2 — Four Doctors

### Variant: hyperlocal_push (H_info)

<!-- auto-generated from variant_hyperlocal_push/aggregate.json; seeds=2 -->

**Diagnosis** (theoretical lineage): Shannon 信息论 + Wu《Attention Merchants》：注意力稀缺假设——附近可被感知的信号不足，平台提供高质量 hyperlocal 内容可补足。

**Cure** (operationalization):

- variant name: `hyperlocal_push`
- chain position: `algorithmic-input`

**Outcome** (auto-filled):

- primary metric `trajectory_deviation_m`: 183.98 95% CI [127.93, 240.02]
- encounter (per-day median): 1240.50 95% CI [983.05, 1497.95]
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

<!-- auto-generated from variant_global_distraction/aggregate.json; seeds=2 -->

**Diagnosis** (theoretical lineage): 同 A (HyperlocalPush) — Shannon/Wu attention economy；但反向操作：饱和 global-news 侵占 agent 注意力。证明工具 dual-use 属性。

**Cure** (operationalization):

- variant name: `global_distraction`
- ⚠️ this is a **paired mirror** of `hyperlocal_push`
- chain position: `algorithmic-input`

**Outcome** (auto-filled):

- primary metric `trajectory_deviation_m`: 211.56 95% CI [178.32, 244.79]
- encounter (per-day median): 1255.75 95% CI [761.04, 1750.46]
- mirror delta vs `hyperlocal_push`: 27.58
- evidence alignment: **inconclusive**
- reviewer notes: inconclusive: CI overlap between variant and reference for trajectory_deviation_m [preliminary—seed count < 30]
- **⚠️ preliminary — seed count < 30**

**Interpretation** (author fills):

> 待作者（基于 Outcome 数字，对 `H_info`
> 的弱支持 / 弱证伪判读；对照 success_criterion / failure_criterion）：
>
> - success_criterion: target agents 相比 control 的 trajectory 更固化（熵下降）；encounter 密度下降；附近盲区加深。Evidence consistent with H_info 的反向（即 hyperlocal 信号不足确实是 binding constraint）。
> - failure_criterion: 无论推多少 global-news，agent 行为与 control 无异——说明 routine 主导行为（H_pull 或 H_structure 可能更重要）。

### Variant: shared_anchor (H_meaning)

<!-- auto-generated from variant_shared_anchor/aggregate.json; seeds=2 -->

**Diagnosis** (theoretical lineage): MacIntyre 共同体主义 + Putnam 社会资本：社区缺共同叙事/目标，注入一个共享的 anchor 可催化弱连接。

**Cure** (operationalization):

- variant name: `shared_anchor`
- chain position: `social-downstream`

**Outcome** (auto-filled):

- primary metric `encounter.per_day_median`: 1482.50 95% CI [945.27, 2019.72]
- encounter (per-day median): 1482.50 95% CI [945.27, 2019.72]
- evidence alignment: **inconclusive**
- reviewer notes: inconclusive: CI overlap between variant and reference for encounter.per_day_median [preliminary—seed count < 30]
- **⚠️ preliminary — seed count < 30**

**Interpretation** (author fills):

> 待作者（基于 Outcome 数字，对 `H_meaning`
> 的弱支持 / 弱证伪判读；对照 success_criterion / failure_criterion）：
>
> - success_criterion: 共享 anchor 的 agents 之间 encounter density 显著高于 control；tie formation（未来 social-graph 能测）高于 baseline。Evidence consistent with H_meaning.
> - failure_criterion: anchor agents 的轨迹与非 anchor agents 无差异；task 仅停留在memory，未转化为空间汇聚。Not consistent with H_meaning.

### Variant: phone_friction (H_pull)

<!-- auto-generated from variant_phone_friction/aggregate.json; seeds=2 -->

**Diagnosis** (theoretical lineage): Simon 注意力稀缺 + Wu《Attention Merchants》：手机商业模式过度索取注意力；降低 pull 能让人自发回到附近。

**Cure** (operationalization):

- variant name: `phone_friction`
- chain position: `attention-main`

**Outcome** (auto-filled):

- primary metric `attention.phone_feed_proxy`: 0.00 95% CI [0.00, 0.00]
- encounter (per-day median): 1585.50 95% CI [1030.22, 2140.77]
- evidence alignment: **inconclusive**
- reviewer notes: inconclusive: CI overlap between variant and reference for attention.phone_feed_proxy [preliminary—seed count < 30]
- **⚠️ preliminary — seed count < 30**

**Interpretation** (author fills):

> 待作者（基于 Outcome 数字，对 `H_pull`
> 的弱支持 / 弱证伪判读；对照 success_criterion / failure_criterion）：
>
> - success_criterion: Friction 期间 agents 的 AttentionState.allocation 'physical_world' 占比上升；空间探索熵上升；encounter 密度上升。Evidence consistent with H_pull.
> - failure_criterion: Friction 无显著行为变化（allocation 分布 IQR 重叠）；或效果仅在 friction 期间，post 立刻回归。Not consistent with H_pull.

### Variant: catalyst_seeding (H_structure)

<!-- auto-generated from variant_catalyst_seeding/aggregate.json; seeds=2 -->

**Diagnosis** (theoretical lineage): Granovetter 弱关系 + Burt 结构洞：社区缺少 bridging 个体，种入少量 connector 人格可涌现更多弱连接。

**Cure** (operationalization):

- variant name: `catalyst_seeding`
- chain position: `social-downstream`

**Outcome** (auto-filled):

- primary metric `encounter.per_day_median`: 1585.50 95% CI [1030.22, 2140.77]
- encounter (per-day median): 1585.50 95% CI [1030.22, 2140.77]
- evidence alignment: **inconclusive**
- reviewer notes: inconclusive: CI overlap between variant and reference for encounter.per_day_median [preliminary—seed count < 30]
- **⚠️ preliminary — seed count < 30**

**Interpretation** (author fills):

> 待作者（基于 Outcome 数字，对 `H_structure`
> 的弱支持 / 弱证伪判读；对照 success_criterion / failure_criterion）：
>
> - success_criterion: Intervention 期间 encounter 网络密度 / clustering 上升；bridging agents 自发出现；弱关系（未来 social-graph 测）增量显著。Evidence consistent with H_structure.
> - failure_criterion: Connector 种子对 encounter 网络无显著影响（度分布 / 聚类系数不变）；或仅 connector 自己受益。Not consistent with H_structure.


## Act 3 — The Contest

<!-- auto-generated from contest.json; 6 rows -->

| variant | hypothesis | primary metric | effect size | 95% CI | baseline | alignment | mirror Δ |
|---|---|---|---|---|---|---|---|
| `baseline` | — | encounter.per_day_median | 1585.50 | 95% CI [1030.22, 2140.77] | 1585.50 | **inconclusive** | — |
| `hyperlocal_push` | H_info | trajectory_deviation_m | 183.98 | 95% CI [127.93, 240.02] | — | **inconclusive** | — |
| `global_distraction` | H_info | trajectory_deviation_m | 211.56 | 95% CI [178.32, 244.79] | — | **inconclusive** | 27.58 |
| `shared_anchor` | H_meaning | encounter.per_day_median | 1482.50 | 95% CI [945.27, 2019.72] | 1585.50 | **inconclusive** | — |
| `phone_friction` | H_pull | attention.phone_feed_proxy | 0.00 | 95% CI [0.00, 0.00] | 0.00 | **inconclusive** | — |
| `catalyst_seeding` | H_structure | encounter.per_day_median | 1585.50 | 95% CI [1030.22, 2140.77] | 1585.50 | **inconclusive** | — |

**Interpretation** (author fills): 判读哪条 rival hypothesis 得到最强 consistent evidence；指出 inconclusive 条的可能原因（sample size / effect 过弱 / 假设机制不对）。


## Act 4 — Decay

<!-- auto-generated from per_day_time_series encounter_count_per_day -->

| variant | intervention-end median | post-end median | decay ratio |
|---|---|---|---|
| `baseline` | 1658.50 | 1568.50 | 0.95 |
| `hyperlocal_push` | 1225.50 | 1107.00 | 0.90 |
| `global_distraction` | 1247.50 | 1193.00 | 0.96 |
| `shared_anchor` | 1476.50 | 1419.50 | 0.96 |
| `phone_friction` | 1658.50 | 1568.50 | 0.95 |
| `catalyst_seeding` | 1658.50 | 1568.50 | 0.95 |

**Interpretation** (author fills): 哪些 variant 在 post phase 留下持久改变（decay ratio 接近 1）；哪些是一次性反应（decay 接近 baseline）。


## Act 5 — The Mirror

<!-- auto-generated from paired-mirror rows from contest -->

- `global_distraction` vs `hyperlocal_push`: mirror delta = +27.58

**Interpretation** (author fills): mirror 的 effect size 是否对称（工具 dual-use 的强证据）？或 asymmetric（说明 attention channel 有偏好方向）？