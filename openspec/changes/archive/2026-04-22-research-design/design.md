## Context

`thesis-focus` 确立主边界（attention-induced nearby blindness）与四层机制链。
Phase 1 / 1.5 基建、smoke demo 已经证明 hyperlocal push 能产生可测量轨迹差异
（+302m）。但从 "smoke demo 的单次跑" 到 "一篇可投稿的 computational social
science 研究" 之间，缺一块**实验哲学 + 实验设计规格**。本 design 定义该规格。

当前散落的决策（应被本 change 统一冻结）：
- 实验协议长度（14 天 vs 单日） → 见 Decision D1
- 实验 variant 结构（同机制多风味 vs 跨机制 rival） → D2
- 实验严谨度门槛（单 run vs cross-seed CI） → D3
- 伦理立场（Enable / Warn / Study / Hybrid） → D4
- 理论传统绑定（4 diagnosis 分别 cite 哪家） → D5
- Mirror 实验规模（3×2 对称 vs 3+1 focus） → D6
- 实验报告叙事结构 → D7

利益相关者：主要 reviewer（学位 / studio / 未来审稿人）；次要 reviewer
（复现者、后续 change 作者）。

约束：
- 代码层零改动（本 change 只规定"什么算实验"）
- 依赖 `multi-day-simulation`（独立并行 change，负责基建）
- 依赖 `thesis-focus` 已冻结的 Chain-Position 门禁

## Goals / Non-Goals

**Goals:**
- 把实验哲学 + 实验设计固化成**可引用的规格**，让未来实验 change 不再
  重复讨论 "跑几天 / 几种 / 几 seed / 怎么写报告"
- 用 **Rival Hypothesis framing** 提升学术定位（从 "intervention testing"
  升格为 "rival theory adjudication"）
- 把 Hybrid 伦理立场**落到实验设计条款**，而非仅在文档里声明
- 给 `policy-hack` / `metrics` / `social-graph` 的实验实现提供对齐锚点

**Non-Goals:**
- 不实现多日基建（属于 `multi-day-simulation`）
- 不实现任何 variant（属于 `policy-hack` 与未来实验 change）
- 不定义任何指标算法（属于 `metrics` change）
- 不改 `00-thesis.md` 的主边界定义（thesis-focus 已冻结）
- 不预先承诺实验会 "通过"——探索性立场允许 null / mixed / negative result
- 不回填已归档 change

## Decisions

### D1：14 天协议（而非单日或 30 天）

**选择**：14 天 = 4 baseline + 6 intervention + 4 post。

**备选**：
- 单日（smoke 现状）：测即时反应，**无法测习惯形成 / 衰减 / 饱和**——学术上不严谨
- 7 天：2 + 3 + 2，压缩但 3 天干预难以建立稳定新 baseline
- 14 天 ✓：Habit formation 文献（Lally et al. 2010）最短有效期约 18 天，
  14 天是 computational social science 可接受的 pragmatic 下限
- 30 天：更可信但计算成本线性翻倍，对探索性项目 overkill

**Why 14**：Lally 等的习惯形成研究显示 median 66 天，但 21-66 天是 "高度可变"
区间；14 天足以看到 3-5 天级的 early habit signal + 4 天 post 看衰减；与
Granovetter 原论文的 "一周-两周" 观察期量级一致。

### D2：Cross-class 4-variant（而非同 class 多风味）

**选择**：A Push / B Friction / C Shared Anchor / D Catalyst Seeding（四条跨机制）。

**备选**：
- 旧方案：4 条都是 push 变体（1a/1b/1c/1e）——**同机制多风味**
  - 问题：叙事薄、方法学上只覆盖 algorithmic-input 一层
- 新方案 ✓：4 条分属 4 个 attention 干预 class（digital push / digital friction /
  social anchor / population structure）
  - 优势：跨 thesis 链条多层覆盖、绑定理论传统、rival hypothesis 结构

**Why 4 而非 3 或 5**：
- 3 条：丢掉 H_structure（Granovetter 线）会是 conspicuous omission
- 5 条：加入 temporal sync 或 framing contrast 会破坏 cross-class orthogonality
  （两者都可降级为附录 scenario）

### D3：β 严谨度（cross-seed × 30 + IQR/CI）

**选择**：每 variant × 30 seeds，报告 median + IQR [25, 75] 或 95% CI。

**备选**：
- α（单 run）：smoke demo 现状，答辩会被问 "luck 吗"
- β ✓（30 seeds）：Schelling 级别，computational social science 最低可发表门槛
- γ（full sensitivity matrix）：seed × model × 参数扫描——对探索性项目 overkill，
  仅在某 provocation 需要时单独跑

**Why 30 而非 10 或 100**：30 是 central limit theorem 的经验下限；100 是 publication
"安全" 级别但计算翻 3 倍；30 是 explore 立场下的 sweet spot。

**Why IQR 而非 only mean**：LLM-driven agent 行为分布往往非高斯（长尾 + 模式混合），
median + IQR 比 mean + SD 更 robust。

### D4：Hybrid 立场（C 骨 + B 皮 + 拒绝 A）

**选择**：
- **C 骨架**：研究本体是 study（wind tunnel symmetric）
- **B 皮肤**：交付包含 mirror experiment + provocations
- **拒绝 A**：不声明部署 readiness / 不写 planner playbook

**备选**：
- 纯 A（enable）：天真，同样工具服务 advertiser / gentrifier / state actor
- 纯 B（warn）：critical design，学术 publishability 弱
- 纯 C（study）：假中立，与 thesis 自带价值判断矛盾
- Hybrid ✓：诚实承认 stance 同时保留研究严谨

### D5：理论传统绑定（4 hypothesis → 4 lineage）

**选择**：
- H_info → Shannon / Wu（注意力稀缺 + 信息论）
- H_pull → Simon / Wu（注意力经济学）
- H_meaning → MacIntyre / Putnam（共同体 + 社会资本）
- H_structure → Granovetter / Burt（弱关系 + 结构洞）

**备选**（考虑后不采用）：
- H_info 绑 Castells（信息社会学）——太宏观，不生成可证伪预测
- H_pull 绑 Morozov（技术批评）——偏评论，非机制学
- H_meaning 绑 Habermas（公共领域）——尺度错配
- H_structure 绑 Schelling（隔离模型）——已用作 ABM 方法学先例，绑定会重复

**Why 可以重复用 Wu**：Wu 的 Attention Merchants 同时承载信息稀缺（H_info）
与注意力经济（H_pull）两层——这是**同一思想史脉络的两种 reading**，本身值得
在论文中展开。

### D6：4 + 1 Mirror（而非 4 × 2 或 3 + 1）

**选择**：4 个正向 variant + 1 个完整 mirror（A'：Global Distraction）+
3 个其它 mirror scenario 仅进附录文档化。

**备选**：
- 4 × 2（每条都 mirror）：工程 × 2，每条 mirror 都需独立 validation
- 3 + 1（只做 3 个正向 + 1 mirror）：放弃一条诊断——不可接受，破坏 rival 结构
- **4 + 1 ✓**：保留所有 diagnosis + establish dual-use 原则（一条透彻的 mirror
  足够建立 "所有干预对称" 的 principle）

### D7：Diagnosis-Cure-Outcome-Interpretation 报告结构

**选择**：实验报告按 Act 1-5 戏剧结构（Baseline → Four Doctors → Contest →
Decay → Mirror），每 variant 内部按 Diagnosis-Cure-Outcome-Interpretation 四段。

**备选**：
- 传统 IMRaD（Introduction / Method / Results / Discussion）：学术通用但叙事扁
- Diagnosis-Cure-Outcome-Interpretation ✓：与 rival hypothesis framing 同构，
  reviewer 读每个 variant 都立刻明白它 "在测哪条假设、假设被如何操作化、结果
  对假设意味着什么"

## Risks / Trade-offs

**[Risk 1] Rival hypothesis framing 可能导致 over-claiming**
→ 缓解：spec 明确 "cure 生效 = 弱支持、不生效 = 弱证伪"；不允许任何报告章节
声明 "H_X proved" 或 "H_X falsified"；只能使用 "evidence consistent with" /
"not consistent with"。

**[Risk 2] 14 天 × 30 seed × 4 variant = ~1 小时 CPU，可能阻塞迭代**
→ 缓解：spec 规定 "dev 迭代时可用 3 seed × 7 day 模式；publishable 运行才强制
30 seed × 14 day"；两模式在 spec 中显式分离。

**[Risk 3] LLM stereotyping 污染 D variant（catalyst seeding）**
→ 缓解：catalyst seeding 的 personality 生成器 MUST 在 profile 绑定 seed，
profile 文本 MUST 经过 swap-test（同 profile 改 ethnicity 后行为差异阈值）。
审计失败则 D variant 不得作为 publishable result。

**[Risk 4] 理论传统绑定被 reviewer 认为牵强**
→ 缓解：每 hypothesis 的文档必须包含 "theoretical rationale" 一节，2-3 句
解释为什么这条 variant 的操作化 faithful 于对应传统；reviewer 分歧在此讨论，
不影响实验运行。

**[Risk 5] Hybrid 立场在 publishable venue 被 reviewer 要求 "更 decisive"**
→ 缓解：不妥协——探索性立场是 deliberate choice，proposal 会引用本 design
D4 作为学术立场声明；若 reviewer 要求部署声明则拒稿优于动摇立场。

**[Risk 6] Multi-day 基建未按时就绪**
→ 缓解：本 change 只写规格、不跑实验；multi-day-simulation 是独立 change，
可并行推进。若 multi-day 延期，本 change 的规格仍可发表/引用。

## Migration Plan

无代码变更，不涉及 migration。

文档层面：
1. 本 change archive 时，specs/experimental-design/spec.md 写入 openspec/specs/
2. `docs/agent_system/13-research-design.md` 新增，作为 canonical 体例文档
3. README / 00-thesis.md / openspec/README 增引用（单行指针，无复述）

## Open Questions

1. **Q1**：`social-graph` 能力是否在 `research-design` archive 之前必须存在
   才能定义 H_meaning / H_structure 的 cure 有效性判据？
   倾向：不必——spec 可预先定义 "outcome 指标包含 encounter density 与 tie
   strength"；具体算法在 `social-graph` + `metrics` 落地时给。
2. **Q2**：是否需要一个 "pilot 3-day × 3-seed" 步骤在 full 14×30 之前？
   倾向：需要——作为 dev loop；spec 应显式允许并鼓励。
3. **Q3**：Baseline 的 "无干预" 到底是什么？Lane Cove agent 在 day 0 本身
   就有默认 plan、有 attention_channel 的 global feed。baseline 是 "零
   push" 还是 "typical daily push noise"？
   倾向：**零 hyperlocal push + 默认 global news feed 保留**——模拟真实
   居民的 "base level of digital feed"；spec 须明确。
