# System Snapshot — 2026-04-25

> 项目当前位置的全景回看。基建已成型；研究待启动。
>
> 本文件是**点位时间快照**——状态会随每次 change 漂移。读它是为了快速
> 理解项目当前状况；具体细节去对应的 canonical 文档（00 / 13 / 18）。

---

## 一句话现状

> **装置 100% / 实验产出 0%**——11 个 capability 全部归档，全栈 smoke
> 跑通，但 agent 拟真度不足；任何 publishable suite 当前都标
> `[unpublishable preview]`，因为 8 项 pre-publication checklist 缺 ≥ 3 项。

---

## 11 个 Capability 全景图

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Synthetic Socio Wind Tunnel                      │
│             Phase 1 (Q1) → 1.5 (Q2) → 2 (Q3) → 治理层               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ▛ Phase 1：CQRS 基建                                                │
│  ▍ atlas       │ 静态布景（OSM → Region）                           │
│  ▍ ledger      │ 动态 entity 状态                                   │
│  ▍ engine      │ Simulation / Collapse / Navigation 写操作          │
│  ▍ perception  │ 主观视角 + 多通道 filter                            │
│  ▍ cartography │ OSM 导入 + RegionBuilder                           │
│                                                                      │
│  ▛ Phase 1.5：thesis 对齐                                            │
│  ▍ attention-channel │ FeedItem + AttentionService + DigitalProfile  │
│  ▍ agent             │ AgentProfile + Planner + AgentRuntime        │
│  ▍ fitness-audit     │ phase1-baseline / phase2-gaps 探针            │
│  ▍ map-service       │ agent 面向 query API                          │
│                                                                      │
│  ▛ Phase 2：实验装置                                                  │
│  ▍ orchestrator      │ tick 循环 + Intent 裁决 + encounter detection │
│  ▍ memory            │ 事件流 + 4-way retrieval + replan 触发器      │
│  ▍ multi-day-run     │ N 天调度 + memory carryover                  │
│  ▍ policy-hack       │ 4+1 rival hypothesis variants                 │
│  ▍ metrics           │ Contest scorer + 5-act report                 │
│  ▍ suite-wiring      │ variant→memory→replan→behavior 因果链装配    │
│                                                                      │
│  ▛ 治理层（纯 spec）                                                 │
│  ▍ thesis-focus       │ 一主三机制 + Chain-Position 门禁             │
│  ▍ research-design    │ Rival Hypothesis + β 严谨度 + 五幕报告       │
│  ▍ validation-strategy│ Validity 取舍 + 8 项 pre-publication checklist│
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 数据流（一行摘要）

```
variant ─push──▶ AttentionService ─inject──▶ NotificationEvent
   │                                                │
   │    on_tick_end: orchestrator.run() per tick    │
   │                                                ▼
   │                                       MemoryService.process_tick
   │                                                │
   │                                       agent.should_replan?
   │                                                │ yes
   │                                                ▼
   │                                         StubReplanLLM
   │                                       (or Anthropic Haiku)
   │                                                │
   │                                                ▼
   │                                       agent.runtime.plan ← new
   │                                                │
   ▼                                                ▼
TickMetricsRecorder.on_tick_end          AgentRuntime.step(tick_ctx)
   │                                                │
   │                                                ▼
   │                                       Ledger.location_id changes
   │                                                │
   └──────────────► per-day rollup ◀────────────────┘
                         │
                         ▼
                    RunMetrics
                         │ × 30 seeds
                         ▼
                    SuiteAggregate
                         │ × 6 variants
                         ▼
                    ContestReport ──▶ report.md (5-act + 4-段每 variant)
```

---

## Capability 关系矩阵

| Capability | 产 | 消费 | 性质 |
|---|---|---|---|
| atlas | Region / OutdoorArea | — | 数据（不可变） |
| ledger | EntityState / WorldEvent | atlas | 数据（可变） |
| engine | SimulationResult | atlas + ledger | 服务（写） |
| perception | SubjectiveView | atlas + ledger + AgentProfile | 服务（读） |
| cartography | Atlas | OSM GeoJSON | 离线工具 |
| attention-channel | FeedItem / NotificationEvent | DigitalProfile | 数字层 |
| agent | AgentProfile / DailyPlan / Intent | personality / digital | 智能体定义 |
| fitness-audit | AuditResult | 各 capability import 探针 | 自检 |
| map-service | KnownDestination / CurrentScene | atlas + ledger | agent 查询 façade |
| orchestrator | TickResult / SimulationSummary | 全栈 | 时间轴主驱动 |
| memory | MemoryEvent / DailySummary / CarryoverContext | TickResult + AttentionService | 经验流 |
| multi-day-run | MultiDayResult / DayRunSummary | orchestrator | N 日调度 |
| policy-hack | Variant / VariantContext / VARIANTS | attention + agent | 干预生成器 |
| metrics | RunMetrics / SuiteAggregate / ContestReport | TickResult + AttentionService + atlas | 观察报告 |
| suite-wiring | StubReplanLLM / suite CLI 装配 | memory + planner + 全栈 | 装配工 |
| thesis-focus | Chain-Position 门禁 | — | 治理（spec） |
| research-design | experimental-design spec | thesis-focus | 治理（spec） |
| validation-strategy | 8 项 checklist + audit 协议 | research-design | 治理（spec） |

---

## 已跑通的"证据链"

```
✓ Lane Cove atlas（OSM → 4794 outdoor_area；89.9% 主连通）
✓ 100 agent × 14 day × 1 seed × 6 variant 全跑通（dev mode）
✓ hyperlocal_push.trajectory_deviation_m < global_distraction（方向正确）
✓ baseline.replan_count = 0；hp.replan_count > 0（因果链通）
✓ contest.json + report.md 自动产出（五幕结构齐全）
✓ Forbidden-word guard 工作；preliminary 标记工作
✓ Reproducibility lock 7 字段（部分实施于 metadata；CLI 全套未实现）
```

---

## 仍开口的 Gap

```
✗ LANE_COVE_PROFILE 占位（phase1-baseline.profile-preset-ground-truthed FAIL）
✗ Stereotype audit（swap / blind / cross-model）三协议未跑
✗ Face validity（Prolific 问卷）未实施
✗ Behavioral baseline（Popular Times / ABS Travel Survey）未校准
✗ AttentionState 完整四元组（physical_world / phone_feed / task / conversation）
   仅有 phone_feed_proxy
✗ social-graph capability 未做（弱关系 / tie strength）
✗ conversation capability 未做（多方对话 / 信息跳数）
✗ Real-LLM cost 控制 / model-budget capability 未做
✗ 14d × 100agent × 1seed perf 60s（spec 35s）— 性能优化未做
```

---

## Pre-publication Checklist 当前状态

```
任何 publishable suite 跑出来现状：

  1. Calibration passed                      ✗ (population + behavioral 都未做)
  2. Stereotype audit passed                 ✗ (三协议都未跑)
  3. Face validity passed                    ✗ (未做 Prolific)
  4. Mirror experiment included              ✓ (suite 含 global_distraction)
  5. Forbidden words check passed            ✓ (metrics 自动 grep)
  6. Reproducibility lock complete           ⚠️ (3/7 字段；其它 CLI 未填)
  7. Ethics Statement included               ⚠️ (research-design Part V 写了；
                                                  CLI 未自动注入 report.md)
  8. Acceptance language compliant           ✓ (metrics + report 措辞 guard)

→ 任一 ✗ 即 [unpublishable preview]；当前 3 项硬 ✗ + 2 项 ⚠️
```

要把 ✗ → ✓，至少需要 **3 个下游 change**：

```
agent-calibration         → 解第 1 项 (calibration)
stereotype-audit          → 解第 2 项 (stereotype)
face-validity-protocol    → 解第 3 项 (face validity)
+ 半个 change             → 完善第 6/7 项 (reproducibility lock + ethics auto-inject)
```

---

## 历史决策点（按时间序）

| 日期 | 决策 | 影响 |
|---|---|---|
| 2026-04-21 | thesis-focus：四重边界 → 一主三机制 | 主边界、Chain-Position 门禁 |
| 2026-04-22 | research-design：Rival Hypothesis | 4 + 1 variant 框架 |
| 2026-04-22 | multi-day-simulation：14 天 protocol | β 严谨度可执行 |
| 2026-04-22 | policy-hack：4 + 1 variants | 干预实施工具箱 |
| 2026-04-23 | metrics：Contest scorer | 评分机 |
| 2026-04-23 | metrics smoke 暴露 wiring 缺口 | suite-wiring 立项 |
| 2026-04-25 | suite-wiring：因果链装配 | hp ≠ gd 方向首次出现 |
| 2026-04-25 | wiring smoke 暴露 agent 拟真度不足 | validation-strategy 立项 |
| 2026-04-25 | validation-strategy：方法学治理 | 8 项 checklist 上锁 |

---

## 三条候选路径

### A. 推 publishable（严肃路径）
1. `agent-calibration` (1-2 周) → 解 checklist 第 1 项
2. `stereotype-audit` (~1 周) → 解第 2 项
3. `face-validity-protocol` (~0.5 周 + 人力) → 解第 3 项
4. 跑一次真 publishable suite → 第一份真证据

### B. Runtime visualization（debug + 理解）
- 静态轨迹热力图（半天）
- Replan 调用链 trace（1-2 天）
- Tick-by-tick 动画（3-5 天）
- 可独立做；不阻塞 publishable

### C. 工程清理
- multi-day perf 优化（60s/seed → < 22s）
- run_variant_suite.py 与 run_multi_day_experiment.py 代码去重
- pytest.mark.slow 注册
- AttentionState 四元组扩展

---

## 参考链路

| 主题 | Canonical 文档 |
|---|---|
| Thesis | [`00-thesis.md`](00-thesis.md) |
| Experimental design | [`13-research-design.md`](13-research-design.md) |
| Multi-day infra | [`14-multi-day-simulation.md`](14-multi-day-simulation.md) |
| Policy hack | [`15-policy-hack.md`](15-policy-hack.md) |
| Metrics | [`16-metrics.md`](16-metrics.md) |
| Suite wiring | [`17-suite-wiring.md`](17-suite-wiring.md) |
| Validity & checklist | [`18-validation-strategy.md`](18-validation-strategy.md) |
| Smoke demo report | [`11-smoke-demo-report.md`](11-smoke-demo-report.md) |
| Project Brief | [`../项目Brief.md`](../项目Brief.md) |
