## Context

`policy-hack` 产 `MultiDayResult` per-seed JSON 含 `variant_metadata` + 每日
commit/encounter 统计。`research-design` 规定 Diagnosis-Cure-Outcome-Interpretation
五幕结构 + β 严谨度（30 seed × median+IQR/CI）。我们有所有**原始数据生成器**，
缺 **从原始数据到 thesis-层 evidence 的加工机**。

Thesis 四层对应的数据源：
- `algorithmic-input` ← `AttentionService.delivery_log`（已存在，per-agent
  feed_item_id + delivered flag）
- `attention-main` ← per-agent `AttentionState`（每 tick 被替换；需捕获）
- `spatial-output` ← Ledger 的 entity.location_id 序列（tick-level；目前
  orchestrator 每 tick 改 Ledger.current_time 并 Move 会改 entity.location_id）
- `social-downstream` ← `TickResult.encounter_candidates`

**缺失**：`AttentionState` 是 ephemeral（不持久化）。需要 hook 在 tick
末读一下存下来。

利益相关者：研究者（跑 suite 看 contest 与 report）；未来 `social-graph` /
`conversation` 作者（要把他们的数据挂入同一 metrics pipeline）。

约束：
- 不跑 simulation（policy-hack + multi-day-run 的职责）
- 不改现有 capability spec（只订阅、只读）
- 不引入 numpy / pandas（项目 lean；Pydantic + stdlib 够用）

## Goals / Non-Goals

**Goals**:
- 从 14 天 × 30 seed × N variant 的 JSON dump 重建 thesis-层 effect size
- 提供一个**机器可产出**的 rival hypothesis contest 表
- 产 Markdown 五幕报告 scaffold（数字自动，叙事待人填）
- 为未来 `social-graph` / `conversation` 预留挂载点（占位字段 + 扩展协议）

**Non-Goals**:
- 不实现 weak tie / info hop 度量（其他 capability 的事）
- 不做 GUI / dashboard（thesis-focus 已归为产品外溢）
- 不做 LLM 叙事打分（Primary deliverable 是数字，叙事人写）
- 不改 policy-hack / multi-day-run / orchestrator 的 spec

## Decisions

### D1：Recorder 是 `on_tick_end` hook；per-run metrics 独立 JSON

**选择**：`TickMetricsRecorder` 订阅 orchestrator 的 `on_tick_end`；
per-tick 累积进 `DayMetricsCollector`；run 结束时把所有天汇总成 `RunMetrics`，
独立 JSON dump（不塞进 `MultiDayResult.metadata`）。

**备选**：
- 直接往 `MultiDayResult.metadata` 里塞——违反 multi-day-run spec 的
  "metadata 是 policy-hack 用的" 分工；路径耦合。
- 完全 post-hoc（不用 hook，只读 ledger 历史）——Ledger 不保留历史轨迹，
  只有最后状态；无法重建 per-tick trajectory。
- ✓ Hook + 独立 JSON：干净分工。`RunMetrics` 跟 `MultiDayResult` 同目录
  下存两份 JSON（或合二为一的 seed dump，由 CLI 决定）

### D2：TickMetricsRecorder 的采样时机

**选择**：每 tick 末采样 per-agent：
- `location_id`（从 `ctx.ledger.get_entity(id).location_id`）
- `AttentionState`（从 `attention_service.get_attention_state(id)`）
- tick 的 encounter count（已在 tick_result）
- tick 的 commit success/fail（已在 tick_result）

**采样粒度**：per-agent × per-tick — 14 天 × 288 tick × 100 agent = 403,200
records。每 record ~300 bytes → ~121 MB in-memory per run。可接受；但
JSON dump 时 per-agent per-tick 会很大。

**优化**：JSON dump 只存 per-day rollup + sparse "interesting tick" list
（变化点、encounter 发生点）。完整 tick-level 数据**保留在内存**供
RunMetrics.from_ticks 时用，JSON 只存聚合后结果。

### D3：轨迹偏离的定义

**选择**：`trajectory_deviation = median_across_seeds( median_across_agents(
  dist(post_phase_home, pre_phase_home)) )` 简化版。

更精确的版本（未来扩展）：
- baseline-phase 4 天的 location 频次分布作"基线轨迹";
- intervention-phase 6 天的 location 频次 vs 基线的 KL divergence
- post-phase 4 天的 "回归率"

第一版实现：以**Wald-like 简化**——比较 intervention 末日 vs baseline 末日
的 `target_location` 到达率（target/control 两组）。这是 smoke demo 已跑
的语义，易实现易验证。

### D4：Contest 的 "evidence_alignment" 判定

**选择**：
```
alignment = "consistent" if (
    variant_effect_ci_lower > baseline_effect_ci_upper
    AND variant metadata's success_criterion direction matches
)
else "not_consistent" if (
    variant_effect_ci_upper < baseline_effect_ci_lower
    AND failure_criterion direction matches
)
else "inconclusive"
```

判据：CI 不重叠 → 决定性；重叠 → inconclusive。这是 rank-ordered 保守判据，
与 β 严谨度 "median + IQR" 一致。

**不做**：p-value、统计检验——本项目是 exploratory，不是 NHST；
effect size + CI 足够。

### D5：Report scaffold 是 Markdown，Outcome 自动填

**选择**：
```markdown
## Act 2 — Four Doctors

### Variant A: Hyperlocal Push (H_info)

**Diagnosis**: [from variant.metadata_dict()['theoretical_lineage']]

**Cure**: [from variant.metadata_dict()['...']; 列 parameters]

**Outcome** (auto):
- trajectory_deviation: 302m (95% CI [260, 340])
- encounter_density: 3400/day (95% CI [3200, 3700])
- feed_delivery_ratio: 0.87 (IQR [0.81, 0.92])
- mirror A' delta: -180m → evidence that A mechanism runs both directions

**Interpretation** (author fills):
> [待作者：基于 Outcome 数字，对 H_info 的"弱支持 / 弱证伪"判读 ≤ 200 字]
```

**原因**：Outcome 客观数据可 auto；Interpretation 是作者判读（符合
"evidence consistent with" 措辞门禁）+ 叙事质量不能机器化。

### D6：Suite CLI 的 orchestration

**选择**：`tools/run_variant_suite.py` 顺序跑 variants（不并行）：
```
for variant in args.variants:
    for seed in range(args.seeds):
        result = build_single_seed_run(
            variant_name=variant, ..., seed=seed,
        )
        # 同时挂了 TickMetricsRecorder（在 build_single_seed_run 内部）
        run_metrics = RunMetrics.from_recorder(recorder, result)
        dump(result, run_metrics, ...)
    aggregate = SuiteAggregate.from_run_metrics(list)
    dump(aggregate, ...)
contest = ContestReport.from_suite(all_aggregates)
report = ReportWriter.write_markdown(contest, suite_dir)
```

**并行**？单机 Python + process pool 可并行 seed 级（14 天 × 100 agent 每
seed ~10s，并行 4-core 可加速 4×）。但增加复杂度；**第一版串行，
留 `--workers` 参数占位**。

### D7：integrate with build_single_seed_run

Current `tools/run_multi_day_experiment.py::build_single_seed_run` 没有
metrics hook。本 change 需要让它**可选地**附加 `TickMetricsRecorder`。

方案：
- `build_single_seed_run(..., recorder: TickMetricsRecorder | None = None)`
- 函数内部 `if recorder is not None: orchestrator.register_on_tick_end(recorder)`
- Suite CLI 显式构造 recorder 传入

**不破坏**：现有单 variant CLI `run_multi_day_experiment.py` 无 recorder
参数时等价旧行为。

### D8：未来 social-graph / conversation 的挂载协议

**选择**：`RunMetrics` 有两个 `None` 占位字段：

```python
class RunMetrics:
    ...
    weak_tie_formation_count: int | None = None
    info_propagation_hops: dict[str, int] | None = None
```

当 `social-graph` change 实现后：它的 recorder（如 `SocialGraphRecorder`）
也订阅 on_tick_end；在 run 结束时调 `run_metrics.model_copy(update={
"weak_tie_formation_count": ...})` 生成新 RunMetrics。这样 metrics 不需
提前知道 social-graph 的数据结构。

**扩展协议**：
- 未来 recorder 应返回 `dict[str, Any]` 的 `additional_fields`；metrics
  aggregator 会把它们 merge 进 RunMetrics.extensions 字段
- 具体协议在 social-graph change 里定义；metrics 只规定**接口要预留**

## Risks / Trade-offs

**[Risk 1] TickMetricsRecorder 每 tick 做 per-agent query 性能爆炸**
→ 缓解：采样降级——tick_sample_interval 参数（默认每 tick 全采样；
大规模 > 1000 agent 时降为每 6 tick 采样 = 30min 真实时间粒度）；spec
scenario 覆盖性能门禁

**[Risk 2] 14 天 × 100 agent × 30 seed suite 跑完总时间 > 60min**
→ 缓解：spec 规定 suite 总 wall time ≤ 60 min（多 day 已验证单 seed ≤ 20s；
4 variant × 30 seed ≈ 40 min；metrics overhead < 10% → 44 min）；超时
失败

**[Risk 3] baseline 运行没有 variant_metadata**
→ 缓解：ContestReport 必须支持 baseline 参与 contest（作为 null variant）；
baseline 的 variant_metadata dict 为 `{"name": "baseline", "hypothesis": None}`

**[Risk 4] trajectory_deviation 的 "target_location" 定义仅适用 A / A'**
→ 缓解：trajectory_deviation 是**per-variant**计算——A/A' 用 target_location；
B/C/D 用 variant-specific 指标（B: screen time allocation；C: anchor-agent
co-location；D: network clustering）。每 variant 的 `primary_effect_size`
在 variant 内部声明（加到 Variant 基类扩展？或 contest.py 按 variant.name
分派）。

**决定**：分派函数 `primary_effect_size_for(variant_name, run_metrics)`
在 `metrics/contest.py`；不污染 Variant 基类

**[Risk 5] 报告 Markdown 的"Outcome 自动填"会把数字编错**
→ 缓解：Outcome 段带 `<!-- auto-generated; variant_name=X seeds=30 -->`
注释 trace；测试 scenario 验证数字与 aggregate JSON 一致

**[Risk 6] Contest 判据过严 → 大量 "inconclusive"**
→ 缓解：inconclusive 本身是有价值结果——说明 sample size 或 effect 太
弱。spec 允许 ContestReport 汇报全 inconclusive 的 suite 而不 fail。

**[Risk 7] 内存占用 per-tick per-agent × 14 天**
→ 缓解：D2 的 "per-day rollup + sparse interesting ticks" 策略；RunMetrics
的 JSON dump 默认不含 full tick-level trace，只存聚合。完整 trace 需要
时用 `--dump-trace` CLI flag

## Migration Plan

1. 实现 metrics module（models + recorder + aggregator + contest + report）
2. 扩展 `build_single_seed_run` 接受 `recorder` kwarg
3. 新 `run_variant_suite.py` CLI
4. 公共 API re-export
5. Fitness-audit auto PASS（probe 已存在）
6. 文档 + 五幕报告 template 示例

**回滚**：删 metrics 目录 + revert CLI 小改即可。不改 existing capability。

## Open Questions

1. **Q1**: `per-variant primary_effect_size` 分派表在本 change 写死，还是
   让每 variant 声明？
   倾向：本 change 写死 dispatch 表——variant 声明 success_criterion
   文本已足；effect_size 的具体**算法**是 metrics 的知识。
2. **Q2**: Baseline run 是否也跑 TickMetricsRecorder？
   倾向：**必须**——Contest 的 baseline reference 就是这个数据。CLI
   应强制 `--variants` 里包含 `baseline`（或自动加）。
3. **Q3**: 是否要实现 "real-world calibration" 指标（e.g. 与 Google
   Popular Times 对照）？
   倾向：不在本 change。留给未来 `validation-strategy` change（见
   earlier 讨论中的 Q1/Q2/Q3 伦理 + LLM stereotype 审计）。
4. **Q4**: `ReportWriter` 产出的 report.md 语言（中文 or 英文）？
   倾向：中文（项目文档整体基调）；英文段可作者自行翻译
