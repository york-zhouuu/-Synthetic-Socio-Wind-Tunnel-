## Context

`metrics` 归档日 smoke + suite-wiring 跑通后的拷问表明：
- 基建已造完（10 个 capability 归档）
- 但**装置里"被风测试"的 agent 系统**底子薄：profile 占位、scripted
  plan 随机、无认知深度、无 face validity 检查、无 stereotype audit
- 任何当前形态下跑的 publishable suite 都是 theatre

研究伦理 + 方法学层面"什么算 thesis 得到 evidence"也没明文。
`experimental-design` 规定了**报告结构**与**β 严谨度**；不规定**evidence
type taxonomy**。

本 change 把这一层补完——纯方法学治理；下游 change 按本 change spec
执行真正的 calibration / audit / face-validity 工作。

## Goals / Non-Goals

**Goals**
- 冻结 6 种 validity 类别 + 取舍（接受哪几种、显式拒绝哪几种）
- 冻结 stereotype audit 协议（swap test / blind test / cross-model）
- 冻结 face validity 协议（Prolific 问卷 / acceptance 阈值）
- 冻结 calibration target（ABS Census + Popular Times 的对照变量与
  分布距离阈值）
- 冻结 pre-publication checklist（8 项 must-pass）
- 给下游 `agent-calibration` / `stereotype-audit` 等 change 提供 upstream
  锚点

**Non-Goals**
- 不实施任何 audit / calibration（下游 change 的事）
- 不爬数据 / 不跑 Prolific 问卷
- 不改已归档 capability spec
- 不写 Python 代码

## Decisions

### D1：6 种 validity，接受 4 拒绝 1 留 1 stub

**接受**（每条都给可操作判据）：
1. **Construct validity** — 每 variant 的 operationalization 是否忠实于
   绑定的 hypothesis（H_info / H_pull / H_meaning / H_structure）。
2. **Internal consistency** — seed 跨 run 可复现；swap test 稳定；
   cross-model 收敛
3. **Convergent validity** — 相同 thesis-层信号在多个 metric 维度同向
4. **Face validity** — 真人读 agent narratives 觉得"像 Lane Cove 居民"
5. **Theoretical fidelity** — Granovetter 弱关系 / Putnam 社会资本 /
   Shannon 注意力稀缺 等概念**有可计算映射**；不是概念漂浮在文档里

**拒绝**（必须明文）：
6. **External validity (predictive)** — 不声称合成 agent 对真实居民
   的行为有 predictive accuracy；不做 RCT 校准

**留 stub**（明文 "未来扩展"）：
- **Ecological validity**（多场地泛化）—— 单场地 Lane Cove；不做

**为什么这样切**：避免堆所有 validity 类别都要做（空头支票）；也避免
只做 internal（自我证明）。4-2 的取舍等同 Hybrid 立场（C 骨：study；
B 皮：mirror；拒绝 A：no real-world claim）的方法学具象化。

### D2：Stereotype audit 三协议必跑

**Swap test**：
- 同 profile 改 `ethnicity_group` （e.g., Han Chinese → Anglo-Australian）
- 跑同 seed × 同 variant × 同 day_index 的 stub-LLM run
- 测量 trajectory_deviation 与 plan diversity 的差异
- **Threshold**：差异 > 5%（绝对值）→ stereotype 风险高 → audit fail
- 真 LLM 跑：threshold 提到 10%（LLM 本身就有些性别 / 文化判断；
  超 10% 视为 stereotyping）

**Blind test**：
- 移除 `ethnicity_group` 字段；其它 profile 字段不变
- 跑同 scenario
- 测量 trajectory / encounter 是否与"含 ethnicity"版本接近
- 若 blind 与含-ethnicity 版本在 seed 池上**收敛**（>80% 重合），则
  ethnicity 字段在 LLM prompt 里影响小——可保留
- 若发散，则 ethnicity 字段在 LLM prompt 里**主导**——存在偏见，
  audit fail

**Cross-model convergence**：
- 同 scenario / 同 seed / 同 variant 用 Haiku + Sonnet（必要时 Opus）
- 测量 trajectory_deviation 与 contest alignment 是否一致
- 若 Haiku 与 Sonnet 给相反的 evidence_alignment（一个 consistent
  一个 not_consistent）→ 模型层面不稳定 → publishable 不接

### D3：Face validity 协议

**目标**：低成本检测 agent narratives "读着像 Lane Cove 居民" vs
"读着像 LLM 编造"

**实施**：
- Prolific（或同等）招 N=20 真人，**优先 Sydney 本地居民**（resident-of
  qualification）
- 给每人看 M=10 条采样 agent 的日记摘录（per-day_summary）+ 一条
  intervention day 的 plan 描述
- 5-Likert 题：
  1. "这段日记读起来像真实居民写的吗？" (1=完全不像 - 5=完全像)
  2. "这位 agent 的行为符合 Lane Cove 居民的日常吗？" (同 1-5)
  3. （挑出最不像的一段）开放回答："为什么？"
- **Acceptance**：M=10 条平均得分 ≥ 3.5/5 且 ≤ 20% 评分 ≤ 2

**成本**：~$100（20 人 × $5）

**频率**：每个 publishable suite 必跑一次；suite 重大变更（变 LLM 版本 /
变 prompt template / 变 LANE_COVE_PROFILE）后重跑

### D4：Population calibration target

**Source**：ABS Census 2021 Lane Cove SA2

**对照变量**（六维必须，其它 nice-to-have）：
1. Age distribution（5 岁分组）
2. Gender ratio
3. `housing_tenure`（own / mortgage / rent / public）
4. `income_tier`（low / mid / high—按当地中位数定义）
5. `ethnicity_group`（按 ancestry 字段聚合）
6. `work_mode`（commute / remote / shift / not-working）

**距离指标**：每维 chi-squared（离散）或 Kolmogorov-Smirnov（连续）
**Acceptance**：6 维全部 p > 0.10（弱拒绝零假设——分布无显著偏离）

**当 acceptance 不达**：calibration change 必须重做采样器；不是 best-effort

### D5：Behavioral baseline calibration

**Source 1**：ABS Travel Survey 2021（Sydney）
- 对照：journey-to-work origin-destination + departure-time
- 在 sim 里：agent first-step plan 起点 → 工作地点 destination + 时间
  分布

**Source 2**：Google Popular Times（爬 top-20 Lane Cove POI）
- 对照：每 POI 周一-周日 24h 的访问 hour-by-hour 分布
- 在 sim 里：相同 POI 在 baseline 14-day run 的 hourly visit count

**距离指标**：每 POI 的 hour-distribution earth mover's distance；
journey-to-work 的 OD 矩阵 chi-squared

**Acceptance**：
- 80% POIs 的 EMD < 阈值（e.g., 0.20，等同分布"近似匹配"）
- OD 矩阵 chi-squared p > 0.10

**实施成本**：populartimes Python package + ABS data download；
~3 day（爬 + parse + 比较脚本）

### D6：Reproducibility lock

每 publishable run 的产物 SHALL 在 metadata 里 freeze：
- `seed_pool: list[int]`（30 条）
- `model_version: "claude-haiku-4-5-20251001" | "stub"`
- `prompt_template_hash: str`（sha256 of `_PLAN_PROMPT_TEMPLATE` + replan
  template）
- `LANE_COVE_PROFILE_hash: str`（sha256 of profile config）
- `variants_loaded: dict[str, version_str]`
- `code_commit: str`（git rev-parse HEAD）

写入 `MultiDayResult.metadata` 与 `report.md` 顶部。

变化任一项 → 不能直接对比新旧 run；需要重跑。

### D7：Pre-publication checklist 8 项

任何 publishable artifact（report.md / contest.json / poster / paper
draft）发布前 SHALL 全部为 ✓：

| 项 | 验证方式 |
|---|---|
| 1. Calibration passed | Population D4 + Behavioral D5 acceptance |
| 2. Stereotype audit passed | D2 三协议 |
| 3. Face validity passed | D3 Prolific 问卷 |
| 4. Mirror experiment included | 至少 1 个 paired mirror（A' Global Distraction）等级交付 |
| 5. Forbidden words check passed | metrics 已有 guard；artifacts 全文 grep |
| 6. Reproducibility lock complete | D6 七字段全填 |
| 7. Ethics Statement included | research-design Part V 的 Ethics Statement 完整 |
| 8. Acceptance language compliant | 仅 "evidence consistent with / not consistent with"；无 "proved / falsified" 等 |

任一缺 → artifact 标注 `[unpublishable preview]`，禁止发布。

### D8：本 change 的 spec 是 "treaty" 不是 "code"

**选择**：spec 内容 100% 是 SHALL 规则与协议；不要求实现任何 Python
模块。下游 change 实现具体 audit / calibration 时引用本 spec。

**备选**：写一个 `synthetic_socio_wind_tunnel/validation/` 模块包装
这些 audit 流程
- 否决：本 change 写代码会爬数据 / Prolific API / chi-squared lib，
  膨胀成大 change；分离更清晰

### D9：Acceptance 措辞门禁与 metrics 已有 guard 的关系

`metrics.contest._assert_no_forbidden` 已禁 "proved / falsified /
confirmed / refuted" 在 contest notes。本 change 把这条**扩展**到
**所有 publishable artifacts**——包括 report.md 全文、poster 文本、
paper draft：
- pre-publication checkbox #8 = grep 全文不含禁用词

不在本 change 实现 grep 工具——下游 `pre-publication-audit` change（若
需要）做。本 change 只规定标准。

## Risks / Trade-offs

**[Risk 1] D4 / D5 阈值过严 → 永远过不了**
→ 缓解：下游 calibration change 实施时若发现 6 维全 < 0.10 不可达，
  pre-publication checklist 允许标 "best effort, k/6 dimensions
  passed" 并显式 disclose；但仍需通过 stereotype audit + face validity

**[Risk 2] Face validity Prolific 找不到足够 Lane Cove 居民**
→ 缓解：扩到 "Sydney resident" 一般池；标注扩展样本

**[Risk 3] Stereotype audit 在所有 variants 上都 fail**
→ 缓解：发现 fail 即停 publishable；先做 prompt engineering / profile
  重设；不可"本次 fail 但下次再说"

**[Risk 4] 下游 change 不引用本 spec**
→ 缓解：本 spec 加 requirement：`agent-calibration` / `stereotype-audit`
  proposal 的 `## Why` SHALL cite 本 spec 的对应 section

**[Risk 5] 本 change 的 docs 与现有 docs 矛盾**
→ 缓解：所有引用都是单向的（其它 docs link 18-validation-strategy.md）；
  18-validation-strategy.md 是 SSOT；矛盾时以它为准

**[Risk 6] checklist 8 项 + audit 协议太繁琐 → 阻塞产出**
→ 缓解：dev 模式 / preliminary 模式继续允许 fast iteration；只有
  publishable artifact 才走 8 项；类似 `mode=publishable` vs `mode=dev`

## Migration Plan

1. 写 `docs/agent_system/18-validation-strategy.md` canonical
2. 写 `specs/validation-strategy/spec.md`（含 6+ requirements）
3. 更新 5 处现有 docs 引用
4. archive 时 sync 创建 `openspec/specs/validation-strategy/spec.md`

无代码 / 测试改动。

## Open Questions

1. **Q1**：Prolific 问卷的 "Sydney resident qualification" 是否够严？
   理想是 Lane Cove resident，但 Prolific 池里这个细分太小。
   倾向：spec 定 "Sydney resident"；提交问卷时尽力 filter Lane Cove
   suburb；不达就放宽并 disclose
2. **Q2**：cross-model audit 是否必须 3 模型（Haiku/Sonnet/Opus）还是
   2 够？
   倾向：2 够（Haiku + Sonnet）；Opus 太贵；2 同向收敛即接受
3. **Q3**：reproducibility lock 的 prompt_template_hash 怎么算（含 stub
   情况）？
   倾向：stub 路径下 hash = `"stub:" + variant_name`；真 LLM 路径下
   hash = sha256 of 实际 prompt template literal
4. **Q4**：本 change 是否预设具体下游 change 顺序？
   倾向：不预设；只规定 acceptance；具体先做哪个（calibration /
   stereotype-audit / face-validity）由后续 change 各自 propose
