# experimental-design — 实验哲学与交付规格

## Purpose

`experimental-design` capability 冻结本项目在**实验方法论**层面的规格：
实验结构（Rival Hypothesis 而非 method testing）、协议时长（14-day
Baseline/Intervention/Post）、publishable 严谨度（β 级：30 seed + CI）、
研究姿态（探索性 + Hybrid 伦理）、mirror experiment 义务（dual-use 显式化）、
以及报告叙事结构（Diagnosis-Cure-Outcome-Interpretation + Act 1-5）。

本 capability 是后续所有实验 change（`policy-hack` / `metrics` /
`social-graph` 等）的 upstream 锚点，**无代码产出**；它规定 publishable
deliverable 必须满足的形式与边界，防止项目滑向 "4 种 push 的 try-out"
或跨越成 deployment-ready 声明。

## Requirements

### Requirement: Primary experiments SHALL adopt Rival Hypothesis structure

所有 primary experiment（即作为 publishable deliverable 的实验）SHALL 将
干预组织为四种关于"附近性消亡"的 rival hypothesis 的 operationalization，
而非 "method testing" 的平列 trial。每个 variant SHALL 在文档中明确绑定一个
hypothesis、对应理论传统、以及 "cure 生效 / 不生效" 对应的弱支持 / 弱证伪
含义。

#### Scenario: Variant 声明其 hypothesis 绑定
- **WHEN** 一个新实验 variant 的文档被创建
- **THEN** 文档顶部 SHALL 以结构化字段列出：`Hypothesis`、`Theoretical lineage`、
  `Operationalization rationale`、`Success criterion (= weak support for H_X)`、
  `Failure criterion (= weak counter-evidence for H_X)`

#### Scenario: 报告措辞禁止过度声明
- **WHEN** 实验报告叙述 variant 的结果
- **THEN** 措辞 SHALL 限于 "evidence consistent with H_X" 或 "not consistent
  with H_X"；**MUST NOT** 使用 "proved / falsified / confirmed" 等决定性措辞

#### Scenario: Primary suite 至少覆盖 4 个 rival hypothesis
- **WHEN** 研究团队设计 primary experiment suite
- **THEN** suite SHALL 至少包含 4 个 variant，绑定到 4 条**跨 attention 干预
  class** 的 rival hypothesis（即 4 条 variant 不得属于同一 class）


### Requirement: Primary experiments SHALL use a 14-day protocol

每个 primary variant 的单次 publishable run SHALL 模拟 14 个 simulated day，
分为三个 phase：
- **Baseline**（Day 0-3，共 4 天）：无干预，建立 natural routine
- **Intervention**（Day 4-9，共 6 天）：按 variant 参数每日施加干预
- **Post**（Day 10-13，共 4 天）：停止干预，测 decay / persistence

#### Scenario: 单 run 时间跨度符合 14 天协议
- **WHEN** 一次 publishable run 启动
- **THEN** orchestrator SHALL 以 `simulated_date` 推进 14 天，每天 288 tick
  （5 分钟粒度），总 tick = 14 × 288 = 4032

#### Scenario: Phase 切换由 date 决定
- **WHEN** `simulated_date` 跨越 Day 3/4 或 Day 9/10 边界
- **THEN** 实验 runner SHALL 自动切换 intervention on/off 状态，无需人工干预

#### Scenario: Dev 迭代模式允许 3 天 × 3 seed 快速 loop
- **WHEN** 研究者标注 run 为 `mode=dev`
- **THEN** runner SHALL 允许 3-day × 3-seed 缩减版；但此模式产出的数据 **MUST NOT**
  出现在 publishable report 中，且报告 MUST 显式标注 "dev mode preliminary"


### Requirement: Publishable effect sizes SHALL use β rigor (cross-seed + CI)

任何声明 "in-sim effect size" 的 publishable 数值 SHALL 由**至少 30 个不同
seed** 的 run 聚合而成，并以 **median + IQR [25, 75] 或 95% CI** 报告。

#### Scenario: 单 run 数字不得作 publishable claim
- **WHEN** 报告或展示中出现一个 numerical effect size
- **THEN** 该数字 SHALL 伴随 seed count ≥ 30 的证据；否则 MUST 显式标注
  "preliminary, single-run, not publishable"

#### Scenario: 分布报告使用 median + IQR 而非 mean + SD
- **WHEN** 报告 variant 的 outcome 分布
- **THEN** 默认 SHALL 使用 median + IQR [25, 75]；若使用 mean + SD 则 MUST 附
  Shapiro-Wilk 或类似正态性检验说明为何 Gaussian 假设合理

#### Scenario: Seed 不够时 report 降级
- **WHEN** seed 数 < 30 但研究者仍希望引用数字
- **THEN** 报告 SHALL 以 "preliminary" section 呈现，并列出为何未达 30
  seed 的原因


### Requirement: Research posture SHALL be exploratory with Hybrid ethics

实验交付的**产出类型** SHALL 限于：
- In-simulation effect sizes with confidence intervals
- Conditional policy reasoning（"若本模型 mechanism 成立，则 …"）
- Hypothesis generation for empirical follow-up
- Sensitivity maps
- Narrative provocations

实验 **MUST NOT** 产出：
- Real-world causal estimates（"真实居民接触率 +N%"）
- Prescriptive deployment recommendations（"X Council 应 …"）
- Cross-site generalization claims（"在所有高密度社区 …"）

#### Scenario: 报告段落自检清单
- **WHEN** 研究者 commit 一份 publishable report
- **THEN** 报告 SHALL 在首页包含一份自检清单，逐项确认未跨越上述界线

#### Scenario: 研究性质显式声明
- **WHEN** 任何 public-facing artifact（README、论文、答辩 deck）提及本项目
- **THEN** artifact SHALL 包含一段 Research Posture Statement，涵盖
  "exploratory instrument / cloud-chamber analogy / dual-use explicit /
  no deployment endorsement" 四点

#### Scenario: Deployment readiness 要求被拒绝
- **WHEN** 外部 reviewer / stakeholder 要求本项目产出 deployment-ready guidance
- **THEN** 研究团队 SHALL 以本 spec 第 4 条为依据礼貌拒绝；不得为 publishability
  让步


### Requirement: Primary suite SHALL include one paired mirror experiment

每个 publishable suite SHALL 至少包含**一个**与正向 variant 配对的 mirror
experiment，以同等 β 严谨度交付，显式证明干预工具的 dual-use 属性。

#### Scenario: Mirror 与其 paired 正向 variant 共享基建
- **WHEN** mirror variant 被设计
- **THEN** 它 SHALL 使用与 paired 正向 variant 完全相同的基建（attention-channel
  / perception filter / 等），差异仅在 content / target / polarity 参数

#### Scenario: Mirror 运行与正向同等严谨度
- **WHEN** paired mirror 运行
- **THEN** 它 SHALL 使用同样 30 seeds × 14 days 协议；结果 SHALL 与正向
  variant 并列展示，不得降级为 appendix

#### Scenario: 其它 mirror scenarios 文档化
- **WHEN** primary suite 包含 N 个正向 variant（N ≥ 4）且只 1 个被 paired
- **THEN** 其它 N-1 个 variant 的 mirror scenario SHALL 在 spec 附录中以
  2-3 句描述（文档化但不实现），显式 preserve dual-use 原则


### Requirement: Experimental reports SHALL follow Diagnosis-Cure-Outcome-Interpretation structure

Publishable experiment report SHALL 按照 Act 1-5 戏剧结构组织；每个 variant
内部按 Diagnosis-Cure-Outcome-Interpretation 四段呈现，而非传统 IMRaD。

#### Scenario: Top-level 五幕结构
- **WHEN** 研究者组织一份 primary experiment report
- **THEN** 报告 SHALL 按以下五个 act 章节展开：Act 1 Baseline / Act 2 Four
  Doctors / Act 3 The Contest / Act 4 Decay / Act 5 The Mirror

#### Scenario: Variant 内部四段式
- **WHEN** 报告某一 variant 的详情
- **THEN** 该 variant 的 subsection SHALL 依次包含：Diagnosis（对应 hypothesis
  陈述）/ Cure（干预的具体 operationalization）/ Outcome（数值与分布）/
  Interpretation（证据对 hypothesis 意味着什么）

#### Scenario: 叙事元素被允许并鼓励
- **WHEN** 报告写作时考虑加入叙事元素（agent 轨迹故事、代表性 daily summary
  引用、可视化 heatmap）
- **THEN** spec 明确允许——Narrative provocation 是本项目声明的产出类型之一；
  但叙事元素 MUST 明示来源（agent_id / seed_id / tick_range），以保 traceability
