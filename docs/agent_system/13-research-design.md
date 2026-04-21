# Research Design — 实验哲学与实验设计

> **这是项目实验设计的单一事实来源（single source of truth）**。
> 所有其它文档 SHALL 引用本文件，不重复陈述实验协议 / 立场 / 指标。
>
> 由 `openspec/changes/research-design/` 冻结于 2026-04-22。
> 正式 spec：`openspec/specs/experimental-design/spec.md`。
>
> 前置：读 [00-thesis.md](00-thesis.md) 了解 thesis 主边界。
> 基建前置：`multi-day-simulation` change（提供 14 天 protocol 执行能力）。

---

## Part I — Research Posture（研究立场的四轴）

本项目是**探索性研究装置（exploratory research instrument）**，对齐 Hybrid
伦理立场（研究本体为 C / 交付框架为 B / 明确拒绝 A）。

### 1. 认知论轴（生产什么知识）

**生产**：
- **In-simulation effect sizes with CI**——带 scope qualifier（"于 Lane Cove
  atlas / 本模型假设下"）的数字
- **Conditional policy reasoning**——"若本模型 mechanism 成立，则 X 优于 Y"
- **Hypothesis generation for empirical follow-up**——给真实世界 RCT 提供
  假设清单
- **Sensitivity maps**——哪些参数对结果高敏 / 低敏
- **Narrative provocations**——多视角 agent 叙事，作为批判性展示材料

**不生产**：
- Real-world 因果估计（"真实居民接触率 +N%"）——需 RCT
- Prescriptive deployment（"Council 应 …"）——需参与式 + 治理
- 跨社区泛化声明——需多场地

### 2. 验证轴（多严算够）

| 严谨度标准 | 本项目 |
|---|---|
| External validity（外部推广） | **不要求**——明确限定 Lane Cove 2066 |
| Predictive validity（预测真实世界） | **不要求**——探索性不做 predictive modeling |
| **Face validity**（人读着像真的） | **要**——Prolific 问卷即足 |
| **Internal consistency**（seed 稳定 / 跨模型收敛） | **要**——swap test / seed freeze |
| **Theoretical fidelity**（概念落到代码可验证） | **要**——每 rival hypothesis 有显式 operationalization |
| **Construct transparency**（每个假设有说明） | **要**——所有黑盒决策可追溯到 proposal |

### 3. 交付轴（最终物件）

| 等级 | 物件 |
|---|---|
| Primary | 4 个 cross-class variant + 1 个 paired mirror，全走 β 严谨度；五幕结构报告 |
| Secondary | 可复现代码 + 方法学文档 + 审计报告 |
| 降级为"产品外溢" | Dashboard / Planner UI / 第三方 API / 真实部署路径 |

### 4. 伦理轴（我们与工具的关系）

- **Hybrid 立场**：研究本体 C（wind tunnel symmetric）+ 交付框架 B（mirror
  实验 + provocation 文档）+ 拒绝 A（不声明部署 readiness）
- **Mirror 实验等级交付**：至少 1 条 mirror 与正向 variant 等级呈现
- **Ethics Statement**：任何 public-facing artifact 须包含 Research Posture
  Statement

---

## Part II — Rival Hypothesis Framing（四种诊断）

实验不是 "method testing"，而是**四种关于"附近性为什么消亡"的 rival
hypothesis 的 computational contest**。每条 variant 是对应假设的**操作化
falsification probe**。

### 四种诊断 × 四种 cure × 四种理论传统

| Hypothesis | 理论传统 | 干预 variant | Cure 生效意味着 |
|---|---|---|---|
| **H_info**<br>信息不足 | Shannon 信息论<br>+ 注意力稀缺 | **A. Hyperlocal Push**<br>attention-channel 推 hyperlocal 内容 | 病灶在**信号层**，平台是 lever |
| **H_pull**<br>手机吸力过强 | Simon 注意力经济学<br>+ Wu《Attention Merchants》 | **B. Phone Friction**<br>多日跑时减半 `DigitalProfile.screen_time_hour` | 病灶在 **pull 端**，反-技术化是方向 |
| **H_meaning**<br>共享意义缺失 | MacIntyre 共同体<br>+ Putnam 社会资本 | **C. Shared Anchor**<br>10% agent 对绑定共享隐藏任务 | 病灶在 **meaning 层**，社会设计是 lever |
| **H_structure**<br>社区缺连接者 | Granovetter 弱关系<br>+ Burt 结构洞 | **D. Catalyst Seeding**<br>种 5% 高-外向低-常规 connector agents | 病灶在 **结构层**，城市规划是 lever |

### 为什么**恰好这四条**

- 四条 **cross-class**（不同机制类型）——跨 thesis 链条多层覆盖
- 四条覆盖**当代社区研究的四大主流理论**——少任一是 conspicuous omission
- 四条在当前基建上**全部可实施**——不引入新 capability
- 四条**rival**（互斥性诊断）——一条 cure 生效 = 弱支持该 hypothesis +
  弱证伪其它三条

### 每 variant 内部字段（canonical 文档结构）

```
Hypothesis:              H_X（诊断陈述）
Theoretical lineage:     引用作者 + 关键著作
Operationalization:      变成代码后是什么：改哪个 parameter / 注入什么 feed
Success criterion:       什么样的数据算 weak support for H_X
Failure criterion:       什么样的数据算 weak counter-evidence for H_X
Ethical mirror:          对称反向操作的简要 scenario
```

### 报告用词门禁

- ✓ 允许：`evidence consistent with H_X` / `evidence not consistent with H_X`
- ✗ 禁止：`proved` / `falsified` / `confirmed` / `refuted`
- ✗ 禁止：`Lane Cove 居民会 …`（把合成 agent 当真人）

---

## Part III — 14-Day Protocol（实验协议）

### 时间结构

```
14-day simulated period, 288 tick/day (5-min granularity), 4032 total tick

┌────────────────────────────────────────────────────────────────────────┐
│ Day 0  1  2  3  │  4  5  6  7  8  9  │  10  11  12  13                 │
│ ──── Baseline ──│── Intervention ────│──── Post ────                   │
│     4 days      │      6 days        │    4 days                       │
│                                                                         │
│ 无干预           │ 按 variant 每日    │ 停止干预，测                    │
│ 建立 natural     │ 施加 (feed 注入 /  │ decay / persistence            │
│ routine pattern  │ 参数变化 / 任务绑  │ (habit formation 是否遗留？)   │
│                  │ 定 / 种子人群)     │                                 │
└────────────────────────────────────────────────────────────────────────┘
```

### 为什么是 14 天（而非 7 / 30）

- **Lally et al. 2010**（习惯形成文献）：median 66 天、21-66 天为高度可变区间
- 14 天足以看到 3-5 天级的 early habit signal + 4 天 post 看衰减
- 与 Granovetter 原论文的 "一周-两周" 观察期量级一致
- 30 天计算成本线性翻倍，对探索性项目 overkill

### 为什么 Baseline / Post 各 4 天

- 4 天足以让 agent 在无干预下稳定（前 1-2 天是 seed transient）
- Post 4 天足够观察 decay 曲线的初期形态

### Phase 切换

- `MultiDayRunner` 本身不知道 phase——它只推进 day_index
- Phase 判断在**调用方的 `on_day_start` hook** 中：`if day_index < 4:
  baseline (no intervention)` / `elif day_index < 10: apply variant X` /
  `else: post (no intervention)`

### Dev vs Publishable 两档

| 模式 | num_days | seeds | 用途 |
|---|---|---|---|
| **dev** | 3（Baseline 1 + Intervention 1 + Post 1）| 3 | 代码迭代、快速 smoke |
| **publishable** | 14 | 30 | 交付 / 答辩 / 投稿 |

Dev mode 结果**不得**出现在 publishable report 中。

---

## Part IV — β Rigor Standard（严谨度标准）

### β 级别的定义

任何 publishable 的 in-sim effect size SHALL：

| 要求 | 值 |
|---|---|
| 不同 seed 数量 | **≥ 30** |
| 分布报告形式 | **median + IQR [25, 75]** 或 **95% CI** |
| 单 run 数字报告 | 仅限 "preliminary, single-run, not publishable" |

### 为什么 30 seed

- 30 是 central limit theorem 的经验下限
- 100 是 publication "安全" 级别但计算翻 3 倍
- 30 是 explore 立场下的 sweet spot

### 为什么 median + IQR 而非 mean + SD

- LLM-driven agent 行为分布往往**非高斯**（长尾 + 模式混合）
- median + IQR 比 mean + SD 更 robust
- 若使用 mean + SD，MUST 附正态性检验（Shapiro-Wilk 或类似）

### 三档严谨度对照（α / β / γ）

| 级别 | 实现 | 何时用 |
|---|---|---|
| α | 单次 run | dev 迭代 / smoke demo / bug repro |
| **β**（本项目标准） | 30 seed × IQR/CI | publishable deliverable |
| γ | full sensitivity matrix（seed × model × 参数） | 某 provocation 特别需要回答 "哪个 assumption 驱动效果" |

### 计算预算

- 14 天 × 100 agent × 1 seed ≈ 17 秒（基于 smoke demo 推算）
- 30 seed × 4 variant × 14 day ≈ 34 分钟（预期）
- 全 suite 上限：60 分钟 wall time

---

## Part V — Ethics + Mirror（伦理与镜像）

### Hybrid 立场（C 骨架 + B 皮肤 + 拒绝 A）

- **C 骨架**：研究本体是 study——wind tunnel 对称可测双向
- **B 皮肤**：交付包含 mirror experiment + provocations，让工具 dual-use
  属性**显式**可见
- **拒绝 A**：不声明部署 readiness、不写 planner playbook、不对真实人群
  做任何干预

### 4 + 1 Mirror 规则

Primary suite = **4 个正向 variant（A/B/C/D）+ 1 个 paired mirror（A'）**，
非 4 × 2 完全对称，也非 3 + 1（4 条诊断必须都在）。

| 配对 | 正向 | Mirror |
|---|---|---|
| **Paired implementation** | A. Hyperlocal Push | **A'. Global Distraction**——推 global news / doom-scrolling，把注意力推离附近 |
| Documented only（附录 A） | B. Phone Friction | B'. Phone Attraction Boost |
| Documented only | C. Shared Anchor | C'. Fragmented Perception |
| Documented only | D. Catalyst Seeding | D'. Anti-connector Seeding |

Mirror 配对的 **A' 与 A 同等 β 严谨度交付**——不得降级为 appendix。

### Ethics Statement（MUST 出现在 public artifacts）

> **Research Posture Statement.** 本项目是探索性研究装置，类比物理学的
> 云室（cloud chamber）——让"注意力位移造成的附近性盲区"这一社会现象
> 在合成 agent 上可观察、可拆解；**不主张任何真实世界部署**。
> 工具本身的对称性使其既可用于促进本地连接，也可用于放大孤立；
> 我们的 mirror experiment 显式展示这一 dual-use 属性。
> 部署需要居民同意、透明治理、反馈机制——这些在本项目 scope 之外。

---

## Part VI — Report Structure（戏剧结构化报告模板）

### Top-level 五幕结构

```
Act 1 — Baseline
    Lane Cove 100 agent × 4 天被动观察；盲区的可视化证据
    热力图 + 轨迹图 + 代表性 agent 日记摘录

Act 2 — Four Doctors
    四种诊断平行展开：每 variant 6 天 intervention
    每 subsection 走 Diagnosis-Cure-Outcome-Interpretation 四段

Act 3 — The Contest
    横向对比 cure effectiveness（轨迹 delta / encounter density /
    tie formation）；病因定位：哪条 hypothesis 得到最强 support

Act 4 — Decay
    停干预 4 天；哪家医生的处方留下持久改变
    habit formation vs 即时反应的分界线

Act 5 — The Mirror
    同一 attention-channel 基建反向操作（A' Global Distraction）
    "四个医生都能治病，也都能制病"
```

### Variant 内部四段式

每 variant subsection：

```
### [A] Hyperlocal Push — H_info（信息不足）

Diagnosis:    H_info 假设陈述 + 理论传统引用
Cure:         操作化细节（feed 生成器 / 参数）
Outcome:      数据（median + IQR + 95%CI）+ 可视化
Interpretation:  对 H_info 的 weak support/counter 程度；与其它三条的 contrast
```

### 不使用 IMRaD 的理由

传统 Introduction / Method / Results / Discussion 结构扁平、难叙事；
戏剧结构 + 四段式 与 rival hypothesis framing **同构**，reviewer 读每个
variant 都立刻明白 "它在测哪条假设、假设被如何操作化、结果意味着什么"。

### 叙事元素允许

Narrative provocation 是声明的产出类型之一：
- Agent 轨迹故事、多视角罗生门日记、代表性 heatmap 片段
- MUST 明示 provenance（agent_id / seed_id / tick_range），保 traceability
- 不得从 narrative 推 prescriptive 结论

---

## Appendix A — Other Mirror Scenarios（文档化未实现）

Preserve dual-use 显式性。以下三组 mirror 不作为 primary 交付物实现，但作
scenario spec 存档：

### A.1 Phone Attraction Boost（B' — 反 Phone Friction）
- **Operationalization**: 多日跑时**提高** `DigitalProfile.screen_time_hour`
  1.5×、增加 notification delivery 频率、降低 hyperlocal radius filter
- **Prediction**: 物理轨迹更固化、encounter 密度下降、附近性盲区加深
- **Ethical significance**: 证明"让人更忙 / 更 distracted"是 trivial
  manipulation——这不是创新，而是 status quo 的 baseline（已经发生）

### A.2 Fragmented Perception（C' — 反 Shared Anchor）
- **Operationalization**: 给原本可能互遇的 3 个 agent 分配**互斥**的
  个性化任务；强化 perception filter 的个体化（algorithmic personalization
  最大化）
- **Prediction**: 同空间 agent 轨迹对交集下降、conversation 转化率归零
- **Ethical significance**: 直接暴露 filter bubble 的社区级外部性——
  个性化是 "design virtue"，同时是 "community vice"

### A.3 Anti-connector Seeding（D' — 反 Catalyst Seeding）
- **Operationalization**: 种 5% agent 具有**极高** routine_adherence +
  **极低** extraversion + 严格 private feed_algorithm_bias（"封闭者"
  人格）
- **Prediction**: 网络密度下降、bridge nodes 消失、聚类系数上升
- **Ethical significance**: 证明"沉默人口"的复制是 easy 的——高密度社区
  当前的结构性困境是否本质上由少数 "封闭者" 锚定？

### 为什么不做这三条 mirror

- **工程成本**：每条都需独立 validation 与同等 β 严谨度
- **学术贡献递减**：A' 已建立 dual-use 原则；B'/C'/D' 的 marginal 贡献
  有限
- **文档化已足**：写下 scenario spec 本身就是 dual-use 的显式声明

---

## Appendix B — 参考链路

| 资产 | 位置 |
|---|---|
| Thesis 主边界 | [`00-thesis.md`](00-thesis.md) |
| 实验 spec（正式契约） | `openspec/specs/experimental-design/spec.md` |
| 基建能力 | `openspec/changes/multi-day-simulation/`（14 天 protocol 执行） |
| 场地（已冻结） | `data/lanecove_atlas.json` |
| 基础证据（Phase 1.5 smoke） | `tools/smoke_experiment_demo.py` + [`11-smoke-demo-report.md`](11-smoke-demo-report.md) |
| Chain-Position 门禁 | `00-thesis.md` "Chain-Position 门禁" 章节 |
| Project Brief（v1 历史） | [`../项目Brief.md`](../项目Brief.md)（§5.4 以前的"四幕剧"已被本文件 Part VI 替代） |

---

## Appendix C — Future Naming Consideration

"Wind Tunnel" 是项目历史品牌；**云室（cloud chamber）** 在方法论自描述
上更合身（详见与 thesis-focus 对话的 design 记录）。最终定稿时考虑
subtitle：`Synthetic Socio Wind Tunnel: A Cloud Chamber for Urban Social
Phenomena`。本文件在此留档，正式改动留待定稿前统一 sweep。
