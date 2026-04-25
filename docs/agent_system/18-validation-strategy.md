# Validation Strategy — 方法学治理

> **本文件是项目 validity 框架的 single source of truth**。所有其它
> 文档 SHALL 引用本文件，不重复陈述 validity taxonomy / audit 协议 /
> calibration 阈值。
>
> 由 `openspec/changes/validation-strategy/`（归档于 2026-04-25）冻结。
> 正式 spec：`openspec/specs/validation-strategy/spec.md`。
>
> **前置阅读**：
> - [`00-thesis.md`](00-thesis.md) — thesis 主边界 + Chain-Position 门禁
> - [`13-research-design.md`](13-research-design.md) — 实验哲学 + Rival
>   Hypothesis framing
> - [`16-metrics.md`](16-metrics.md) — Contest scorer + Pre-publication
>   metrics 内部一致性

---

## 为什么要这一层

`metrics` 归档日 smoke + `suite-wiring` 跑通后的诚实拷问揭示：

- **基建已完整**（10 个 capability 归档）
- 但**装置里"被风测试"的 agent 系统拟真度不足**
- **stub-only suite 是套娃**：variants 的行为是 hand-coded → contest
  检测出 hand-coded 信号
- **真 LLM 也不解决**：profile 占位 → LLM 基于 underspecified 输入产
  英文世界刻板模板
- **没有"什么算 thesis 得到 evidence"的明文**

本文件回答两件事：
1. 我们**接受**哪些 validity 类别（什么算证据）
2. 任何 publishable artifact 在产出前**SHALL 通过**的 audit / checklist

下游 change（`agent-calibration` / `stereotype-audit` /
`face-validity-protocol`）按本文件执行；本文件是**纯方法学治理**
——不实施，只规定。

---

## Part I — Validity Taxonomy（接受 4 / 拒绝 1 / Stub 1）

| Validity 类别 | 取舍 | 可操作判据 |
|---|---|---|
| **Construct validity** | ✓ 接受 | 每 variant operationalization 忠实于其 hypothesis；`policy-hack` variant 元数据已含 `success_criterion` / `failure_criterion` / `theoretical_lineage` |
| **Internal consistency** | ✓ 接受 | seed 跨 run 可复现；swap test 稳定；cross-model 收敛 |
| **Convergent validity** | ✓ 接受 | 相同 thesis-层信号在多个 metric 维度同向 |
| **Face validity** | ✓ 接受 | 真人读 agent narrative 觉得"像 Lane Cove 居民"；阈值 ≥ 3.5/5 |
| **Theoretical fidelity** | ✓ 接受 | Granovetter / Putnam / Shannon 等概念有可计算映射 |
| **External (predictive) validity** | ✗ **拒绝** | 不声称合成 agent 对真实居民的 predictive accuracy；不做 RCT 校准 |
| **Ecological validity** | ⏸ Stub | 单场地 Lane Cove；多场地泛化留作未来扩展 |

### 与 Hybrid 立场的对应

```
Hybrid 立场                Validity 取舍
──────────────────         ──────────────────
C 骨架（study）        ↔   接受 Construct + Internal + Convergent
                           + Theoretical fidelity
B 皮肤（mirror）       ↔   接受 Face validity（人读叙事感）
                           + Mirror experiment 强制（research-design 已规定）
拒绝 A（no deploy）    ↔   拒绝 External (predictive)
                           + 拒绝 Ecological multi-site
```

四接受 + 一拒绝 + 一 stub 是 Hybrid 立场的方法学具象化。

---

## Part II — Stereotype Audit（三协议必跑）

任何 publishable run 在生成 contest 前 SHALL 通过以下三协议：

### 1. Swap Test

**做什么**：同 profile 改 `ethnicity_group` → 跑同 seed × 同 variant ×
同 day_index → 测量 trajectory_deviation_m / plan diversity 差异

**对照对至少 1 个**：
- Han Chinese ↔ Anglo-Australian
- Korean ↔ Greek
- Italian ↔ Mandarin

**Acceptance**：
- Stub 路径：差异 ≤ **5%**（绝对值）
- Real LLM 路径：差异 ≤ **10%**

超阈值 → audit FAIL → publishable 不接

### 2. Blind Test

**做什么**：移除 `ethnicity_group` 字段（其它字段保持） → 跑同 scenario
→ 与含-ethnicity 版本对比

**Acceptance**：≥ 80% seed 重合（trajectory_deviation_m 差异在 IQR
之内）→ ethnicity 字段对 LLM prompt 影响有限——可保留

否则 → ethnicity 字段在 LLM prompt 主导 → audit FAIL

### 3. Cross-Model Convergence

**做什么**：同 scenario / 同 seed 跑 2 个 model（Haiku + Sonnet）

**Acceptance**：contest 行的 `evidence_alignment` 字段一致；不一致
（一个 consistent / 一个 not_consistent）→ 模型层不稳定 → publishable
不接

**Stub-only 路径**：cross-model 标 N/A 并 disclose；其它两条仍跑

---

## Part III — Face Validity Protocol

### 流程

| 步骤 | 内容 |
|---|---|
| 样本采集 | M = 10 条 agent narrative 抽样，每 variant 至少 1 条代表 agent |
| 审阅者 | N = 20 真人，优先 Lane Cove / Sydney resident（Prolific 或同等） |
| 评分 | 5-Likert 三题：(1) 像真实居民写的吗？(2) 行为符合 Lane Cove 日常吗？(3) 最不像的一段为什么？ |
| Acceptance | M=10 条平均得分 ≥ **3.5/5** AND ≤ 20% 评分 ≤ 2 |

### 频率

- 每个 publishable suite 必跑一次
- LLM 版本变化 / `LANE_COVE_PROFILE` 变化 / prompt template 变化 → 重跑

### 成本

约 $100（20 人 × $5）。

---

## Part IV — Population Calibration Target

下游 calibration change（如 `agent-calibration`）SHALL 校准
`LANE_COVE_PROFILE` 至以下规格：

### Source

ABS Census 2021 Lane Cove SA2

### 6 维度对照

1. Age distribution（5 岁分组）
2. Gender ratio
3. `housing_tenure`（own / mortgage / rent / public housing）
4. `income_tier`（low / mid / high；按当地中位数定义）
5. `ethnicity_group`（按 ancestry 字段聚合）
6. `work_mode`（commute / remote / shift / not-working）

### 距离指标

- 离散字段：chi-squared
- 连续字段：Kolmogorov-Smirnov

### Acceptance（双轨）

- **Strict**：6 维全 p > 0.10
- **Best-effort**：≥ 4 维 p > 0.10 + publishable artifact 显式 disclose
  缺哪几维

完成 strict 后 → fitness-audit `phase1-baseline.profile-preset-ground-truthed`
状态变 PASS。

---

## Part V — Behavioral Baseline Calibration Target

`build_scripted_plan` 或其继任 SHALL 对照真实出行 / POI 数据校准：

### Source 1：ABS Travel Survey 2021 (Sydney)

- 对照：journey-to-work origin-destination 矩阵 + departure-time
  distribution
- Sim 中：agent first commute step 起点 → destination + 时间分布
- 距离指标：OD chi-squared；时间 KS
- Acceptance：OD chi² p > 0.10

### Source 2：Google Popular Times（top-20 Lane Cove POI）

- 对照：每 POI 周一-周日 24h hourly visit distribution
- Sim 中：相同 POI baseline 14-day run hourly visit count
- 距离指标：Earth Mover's Distance per POI
- Acceptance：≥ **80%** POIs 的 EMD < **0.20**

### 实施成本

`populartimes` Python package + ABS data download；约 3 day（爬 + parse
+ 比较脚本）。

---

## Part VI — Reproducibility Lock（七字段）

每 publishable run 的产物（`MultiDayResult.metadata` + `report.md` 顶部）
SHALL 含：

| # | 字段 | 例 |
|---|---|---|
| 1 | `seed_pool: list[int]` | `[42, 43, ..., 71]` |
| 2 | `model_version: str` | `"claude-haiku-4-5-20251001"` 或 `"stub:v1"` |
| 3 | `prompt_template_hash: str` | sha256 of `_PLAN_PROMPT_TEMPLATE`；stub 路径下 `"stub:<variant_name>"` |
| 4 | `LANE_COVE_PROFILE_hash: str` | sha256 of profile config |
| 5 | `variants_loaded: dict[str, str]` | variant_name → variant code hash |
| 6 | `code_commit: str` | `git rev-parse HEAD` |
| 7 | `phase_config: dict` | `{"baseline_days": 4, "intervention_days": 6, "post_days": 4}` |

任一字段变化 → **不能直接对比**新旧 run（视为不同实验配置）；任何
cross-run claim SHALL 显式 disclose 哪些字段变了。

---

## Part VII — Pre-Publication Checklist（8 项）

任何 publishable artifact（report.md / contest.json / poster / paper
draft）发布前 SHALL 在 metadata 或文档头部按以下 8 项标注 ✓/✗：

| # | 项 | 验证方式 |
|---|---|---|
| 1 | Calibration passed | Population Part IV + Behavioral Part V acceptance |
| 2 | Stereotype audit passed | Part II 三协议 |
| 3 | Face validity passed | Part III Prolific 问卷 |
| 4 | Mirror experiment included | ≥ 1 个 paired mirror（A' Global Distraction）等级交付 |
| 5 | Forbidden words check passed | artifact 全文无 `proved / falsified / confirmed / refuted` |
| 6 | Reproducibility lock complete | Part VI 七字段全填 |
| 7 | Ethics Statement included | research-design Part V 完整段 |
| 8 | Acceptance language compliant | 仅 "evidence consistent with / not consistent with"；无 "X confirms Y" 等 |

任一 ✗ → artifact SHALL 标 `[unpublishable preview: K/8 checklist items
failed]` banner，禁止发布或宣称 "evidence"。

### 模式区分

- `mode=dev`：preliminary / smoke / iteration → checklist N/A，可标
  `[dev preview]`
- `mode=publishable`：8 项全 pass 才能去掉 preview 标记

类似 `metrics` 的 `degraded_preliminary_not_publishable` 与 `multi-day-run`
的 `dev` / `publishable` 双档区分。

---

## Part VIII — 与现有 spec / docs 的关系

```
            00-thesis (主边界 + Chain-Position 门禁)
                    │
                    ▼
            13-research-design (Rival Hypothesis + β 严谨度)
                    │
                    ▼
            18-validation-strategy ← 本文件
                    │
                    │ 规定 audit 阈值 + checklist
                    │
        ┌───────────┼───────────┬─────────────┐
        ▼           ▼           ▼             ▼
   agent-       stereotype-  face-        behavioral-
   calibration  audit        validity-    calibration
                              protocol     (下游 change)
                    │
                    ▼ 八项全 pass
                    │
            publishable artifact 可去 preview banner
```

本文件**不实施**任何 audit / calibration——这是治理层。下游 change
执行具体协议时引用本文件的 acceptance 阈值。

### 与 metrics spec 的分工

`metrics` 已实现：
- `MultiDayResult.metadata.replan_count` / `phase_config` / `variant_metadata`
- `ContestReport` 的 evidence_alignment 三档
- `ReportWriter` 的禁用词 guard（contest notes 段）
- `degraded_preliminary_not_publishable` 标志

`validation-strategy` 在其上叠加：
- 8 项 checklist 的 ≥ 5 项**不在 metrics 范围**（calibration / stereotype
  audit / face validity / mirror / reproducibility lock 7 字段）
- 这些项的实现需要下游 change 完成；metrics 提供的是**已部分覆盖**的
  内部一致性 + 措辞 guard

---

## Appendix A — Open Questions（design 留底）

1. **Q1** Prolific 找不到足够 Lane Cove 居民？
   倾向：spec 定 "Sydney resident"；提交问卷时尽力 filter Lane Cove
   suburb；不达就放宽并 disclose

2. **Q2** Cross-model audit 必须 3 model 还是 2？
   倾向：2 够（Haiku + Sonnet）；Opus 太贵；2 同向收敛即接受

3. **Q3** Reproducibility lock 的 prompt_template_hash（含 stub 情况）？
   倾向：stub 路径下 hash = `"stub:<variant_name>"`；真 LLM 路径下
   hash = sha256 of 实际 prompt template literal

4. **Q4** 本 change 是否预设具体下游 change 顺序？
   倾向：不预设；由后续 change 各自 propose

---

## 参考链路

| 资产 | 位置 |
|---|---|
| 正式 spec | `openspec/specs/validation-strategy/spec.md`（归档 sync 后） |
| 上游 thesis | [`00-thesis.md`](00-thesis.md) |
| 上游 research-design | [`13-research-design.md`](13-research-design.md) |
| 同级 metrics（部分 coverage） | [`16-metrics.md`](16-metrics.md) |
| 同级 suite-wiring（CLI 装配） | [`17-suite-wiring.md`](17-suite-wiring.md) |
| 提案 / design 详细决策 | `openspec/changes/archive/2026-04-25-validation-strategy/`（归档后） |
