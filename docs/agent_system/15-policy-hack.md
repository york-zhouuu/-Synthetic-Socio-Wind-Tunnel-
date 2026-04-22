# Policy-Hack — 4 + 1 Rival Hypothesis Variants

> 实验干预生成器工具箱。与 [`13-research-design.md`](13-research-design.md)
> 的 Rival Hypothesis Framing 一一对应；基建层依赖
> [`14-multi-day-simulation.md`](14-multi-day-simulation.md) 的 MultiDayRunner。
>
> 由 `openspec/changes/policy-hack/` 实现（2026-04-22）。正式 spec：
> `openspec/specs/policy-hack/spec.md`。

---

## Four Doctors（四种诊断） + 一个 Mirror

```
┌─────────────────────┬────────────────────────────────┬────────────────────┐
│  Variant            │  Diagnosis (H_*)               │  Chain Position    │
├─────────────────────┼────────────────────────────────┼────────────────────┤
│  A  Hyperlocal Push │  H_info: 信号不足              │  algorithmic-input │
│  B  Phone Friction  │  H_pull: 手机吸力过强          │  attention-main    │
│  C  Shared Anchor   │  H_meaning: 共享意义缺失       │  social-downstream │
│  D  Catalyst Seed   │  H_structure: 社区缺连接者     │  social-downstream │
│  A' Global Distract │  H_info 反向（paired mirror）  │  algorithmic-input │
└─────────────────────┴────────────────────────────────┴────────────────────┘
```

---

## Variant 明细

### A. HyperlocalPushVariant → H_info
**Diagnosis**（Shannon 信息论 + Wu 注意力经济学）：附近可被感知的
hyperlocal 信号不足；推优质本地内容可补足。

**Cure**：intervention 期间每日向"前一半"agents（by agent_id 字典序）
推送 1 条 hyperlocal feed_item，content 从 5 条模板池 seed-bound 选，
`source="local_news"`，`hyperlocal_radius=500m`，指向 `target_location`。

**Success criterion**：target trajectory median delta > 100m 向
target_location；encounter 密度上升。

**Failure**：target 与 control delta IQR 重叠，或效果在 3 天内衰减。

### B. PhoneFrictionVariant → H_pull
**Diagnosis**（Simon 注意力经济学 + Wu《Attention Merchants》）：手机
商业模式过度索取注意力；降低 pull 能让人自发回到附近。

**Cure**：intervention 首日把每 agent 的 `DigitalProfile` 三字段乘以
`friction_multiplier`（默认 0.5）：`daily_screen_hours`、
`notification_responsiveness`、`headphones_hours`；`feed_bias` 改为
`"local"`。Post 首日恢复。

**Success**：intervention 期间 AttentionState.allocation 的
`physical_world` 占比上升；空间探索熵上升；encounter 密度上升。

**Failure**：Friction 无显著行为变化；或效果仅在 friction 期间，
post 立刻回归。

### C. SharedAnchorVariant → H_meaning
**Diagnosis**（MacIntyre 共同体 + Putnam 社会资本）：社区缺共同叙事；
注入一个共享 anchor 可催化弱连接。

**Cure**：intervention 首日选 1 条 task 描述 + 挑 `share_ratio`（默认
10%）的 anchor agents；之后每日用**同一 feed_item_id**把 category="task"
的 feed 注入这组 agents。memory 把它作 `kind="task_received"` 写入，
进 `CarryoverContext.pending_task_anchors`，影响次日 plan。

**Success**：anchor agents 间 encounter density 显著高于 control；tie
formation 高于 baseline。

**Failure**：task 仅停留在 memory，未转化为空间汇聚。

### D. CatalystSeedingVariant → H_structure
**Diagnosis**（Granovetter 弱关系 + Burt 结构洞）：社区缺 bridging
个体；种少量 connector 可涌现弱连接。

**Cure**（发生在 **run 前的 `apply_population`**，不是每日 hook）：
选 `ceil(N × catalyst_ratio)` 个 agent（默认 5%），将其 personality 覆盖
为 connector 预设（高外向 / 低 routine_adherence / 高 curiosity）；
其它字段（年龄、职业、住房）不变。

**Success**：encounter 网络密度 / clustering 上升；degree 分布显现 bridge
节点；弱关系增量显著。

**Failure**：Connector 种子对网络无显著影响。

### A'. GlobalDistractionVariant → H_info（mirror）
**同一 attention-channel 基建、反向操作**：饱和推送 20 条/day 的
`source="global_news"` feed，content 与 hyperlocal 无关。证明工具
dual-use——既可带人回附近，也可加深盲区。

**与 A 共享 target 选择逻辑**：前一半 agents by agent_id 字典序。

---

## 框架：Variant + PhaseController + Adapter

```python
from synthetic_socio_wind_tunnel.policy_hack import (
    HyperlocalPushVariant, PhaseController, VariantRunnerAdapter,
)

variant = HyperlocalPushVariant(target_location="cafe_main")
controller = PhaseController(baseline_days=4, intervention_days=6, post_days=4)
adapter = VariantRunnerAdapter(variant, controller, seed=42)

# D variant 在此时改 population；其它 variant 返回原 list
profiles = adapter.setup_run(profiles, Random(42))

# 构造 orchestrator + runner（用改后的 profiles 构造 runtimes）
...

adapter.attach_to(runner)
result = runner.run_multi_day(
    start_date=date(2026, 4, 22), num_days=14,
    on_day_start=adapter.on_day_start,
)
adapter.augment_result_metadata(result)  # variant metadata 落到 MultiDayResult.metadata
```

### Variant 生命周期

```
run 前:
  variant.apply_population(profiles, rng)   ← 仅 D 实际改

每日 (by day_index):
  0..baseline_days-1   baseline         (no-op)
  baseline_days        intervention 首日  variant.apply_intervention_start(ctx)
                                          variant.apply_day_start(ctx)
  baseline_days+1..    intervention 中期  variant.apply_day_start(ctx)
  baseline_days+inter  post 首日        variant.apply_intervention_end(ctx)
  其余 post            (no-op)
```

B (Phone Friction) 用 `apply_intervention_start` 缓存 + 施加；
`apply_intervention_end` 恢复。其它 variant 只用 `apply_day_start`。

---

## CLI

```bash
# 3 天 dev smoke
python3 tools/run_multi_day_experiment.py \
    --variant hyperlocal_push \
    --num-days 3 --agents 10 --seeds 1 \
    --mode dev --phase-days 1,1,1

# 14 天 publishable（30 seed）
python3 tools/run_multi_day_experiment.py \
    --variant hyperlocal_push \
    --num-days 14 --agents 100 --seeds 30 \
    --mode publishable --phase-days 4,6,4
```

合法 `--variant` 值：`baseline` / `hyperlocal_push` / `global_distraction` /
`phone_friction` / `shared_anchor` / `catalyst_seeding`。

`baseline` 保留为 "no variant applied"——与 multi-day-simulation archive
时一致。

每 seed 产 JSON dump 含 `metadata.variant_metadata` + `metadata.phase_config` +
`metadata.seed`，供未来 `metrics` change 消费。

---

## 与 experimental-design spec 的对应

| experimental-design 条款 | policy-hack 实现 |
|---|---|
| Rival Hypothesis 结构 | 每 variant 绑定一个 H_* + 理论传统 + 判据 |
| 4 个 cross-class variant | A/B/C/D 跨 algorithmic-input / attention-main / social-downstream |
| 14-day Baseline/Intervention/Post | `PhaseController(4, 6, 4)` 默认 |
| β 严谨度（30 seed + CI） | `MultiDayResult.combine(...)` 由 multi-day-run 提供；policy-hack 只保证 variant 可复现 |
| Paired mirror（4+1） | `GlobalDistractionVariant.is_mirror=True`, `paired_variant="hyperlocal_push"` |
| Diagnosis-Cure-Outcome-Interpretation | 每 variant 的 docstring + `metadata_dict()` 按此结构 |

---

## 零 LLM 承诺

所有 4 + 1 variant 的 `apply_*` 方法不调任何 LLM：
- A / A': content_templates + seed-bound RNG 选模板
- B: 参数乘法
- C: task_templates + seed-bound RNG 选任务
- D: personality 预设覆盖

Feed content 跨 seed 有多样性，跨 run 完全 reproducible。

---

## 后续扩展（超出本 change scope）

- 参数扫描（如 HyperlocalPush 的 daily_push_count ∈ {1, 5, 20}）→
  未来 `metrics` 或专门的 ablation change
- 其它 3 mirror（B' Phone Attraction / C' Fragmented Perception /
  D' Anti-connector Seeding）→ `experimental-design` spec 附录 A 已文档化
- 真实 LLM 生成 feed 内容 → 未来扩展，会破坏当前 reproducibility 保证
- 组合 variant（A + D 同跑）→ 研究设计决定保持 rival 横向对比，不做组合
