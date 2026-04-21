## Why

`thesis-focus` 把项目主边界收敛为 `Attention-induced Nearby Blindness`，但**实验设计层面**仍然散落在 Brief v1 的三个 Experiment 描述、smoke demo 的临时脚本、以及 phase-2-roadmap 的泛称（`policy-hack` / `metrics`）。后果：

1. **叙事薄**：现有 "policy hack = push" 默认把 attention 干预窄化为 feed 注入。smoke demo 的 `+302m` 是一次性反应，讲不出"这是科学研究"的故事。
2. **逻辑不紧**：干预只做 hyperlocal push 一维，没有覆盖 attention → behavior → social 这条链条的其它入口；4 个变体也只是同机制的不同风味。
3. **学术定位暧昧**：未说明"探索性项目"到底生产什么知识、以什么严谨度、拒绝什么声明。容易让 reviewer / 答辩者读成 "试 4 种 push"。
4. **伦理立场未冻结**：thesis-focus 提了 Hybrid（C 骨架 + B 皮肤 + 拒绝 A），但没落到实验设计里——没有 mirror experiment 义务、没有 Ethics Statement、没有 dual-use 显式声明。
5. **缺乏 rival hypothesis 结构**：Brief 隐含的"注意力是问题"本身就是一个假设；真正严谨的 ABM 研究应该**让多个关于 '附近性为什么消亡' 的 rival hypothesis 各自操作化**，并用实验结果之间的 contrast 回答大问题，而不是假设一个答案再去测。

本 change 把这些全部落成一份**实验哲学 + 实验设计**的正式规格，作为后续所有实验 change（`policy-hack` / `metrics` / `social-graph`）的 upstream 锚点。代码层无改动。

**Chain-Position**：`observability` + `infrastructure`（研究方法规格本身不属于四层机制链，但它规定了链条如何被观察与解释）。

## What Changes

### 1. 新增 "Rival Hypothesis" 实验框架

实验不再是 "4 种 policy hack 的 try-out"，而是**四种关于"附近性为什么消亡"的 rival hypothesis 的 computational contest**：

| Hypothesis | 理论传统 | 干预 variant | 若 cure 生效意味着 |
|---|---|---|---|
| **H_info** 信息不足 | Shannon 信息论 + 注意力稀缺 | A. Hyperlocal Push | 问题是信号层，平台是 lever |
| **H_pull** 手机吸力过强 | Simon/Wu 注意力经济学 | B. Phone Friction | 问题是 pull 端，反-技术化是方向 |
| **H_meaning** 共享意义缺失 | MacIntyre 共同体 + Putnam 社会资本 | C. Shared Anchor | 问题是 meaning 层，社会设计是 lever |
| **H_structure** 社区缺连接者 | Granovetter 弱关系 + Burt 结构洞 | D. Catalyst Seeding | 问题是结构层，城市规划是 lever |

四条干预**跨 class（不同机制类型）**，不是同一 class 的 4 种风味；每条的成败对应一个 hypothesis 的弱支持/弱证伪。

### 2. 冻结 "14 天协议 + β 严谨度"

所有 primary 实验 SHALL 按 14 天协议运行：

```
Day 0-3   Baseline     (4 d, 无干预) — 建立 natural routine
Day 4-9   Intervention (6 d, 按 variant 每日推送/施加干预)
Day 10-13 Post         (4 d, 停干预) — 测 decay / persistence
```

每 variant × **30 seeds**（β 严谨度：单 run 数字是 luck；cross-seed + IQR/CI 是 Schelling 级别的最低可发表门槛）。

### 3. 冻结 Hybrid 伦理立场 + Mirror 规则

- **Research posture**: Exploratory research instrument；**拒绝**部署 readiness 声明
- **Primary mirror**: 与 A 配对的 A'（Global Distraction）**同等严谨度交付**——4 + 1 结构（4 个正向 variant + 1 个完整 mirror）
- **其它 mirror 的 scenario spec** 进附录（不实现，仅文档化以 preserve dual-use 显式性）

### 4. 冻结"探索性项目"四轴

|轴 | 生产 | 不生产 |
|---|---|---|
| 认知论 | In-sim effect sizes with CI / 条件性政策推理 / 可验证假设 / provocations | Real-world 因果估计 / Prescriptive 部署 / 跨社区泛化 |
| 验证 | Face + Internal consistency + Theoretical fidelity | Predictive validity / External validity |
| 交付 | 研究装置 + 两极实验套件 + 叙事报告 | Dashboard / Planner UI / 真实推送接口 |
| 伦理 | Dual-use 显式 + Mirror 并举 + Ethics Statement | 部署建议 / 操作手册 |

### 5. 戏剧结构化报告模板

实验报告不按 "Method-Result" 段落，按 **Diagnosis-Cure-Outcome-Interpretation**：

```
Act 1: Baseline (Day 0-3) — Lane Cove 盲区的可视化证据
Act 2: Four Doctors (Day 4-9) — 四种诊断平行展开
Act 3: The Contest — cure effectiveness 对比，病因定位
Act 4: Decay (Day 10-13) — 持久性甄别
Act 5: The Mirror — 同一仪器的反向验证
```

### 6. 前置依赖：multi-day-simulation

本 change 的实验协议（14 天 + 多日 memory carryover + 跨日 planner）依赖
尚未实现的多日基建。为 **decouple 研究设计决策 与 工程实现**，本 change **只写规格**，不跑实验；实际跑实验前 MUST 先完成独立 change `multi-day-simulation`。

## Capabilities

### New Capabilities

- `experimental-design`: 实验框架的规格——定义 primary experiment 必须满足的结构（14 天协议、rival hypothesis 绑定、β 严谨度、mirror 规则、叙事报告模板）。所有后续实验 change（`policy-hack` / `metrics` / `social-graph` 的实验实现）SHALL 引用本 spec。

### Modified Capabilities

（无——本 change 不改变已有能力的契约；仅新增实验方法规格）

## Impact

- **文档**：新增 `docs/agent_system/13-research-design.md`（canonical 实验设计文档，与 `00-thesis.md` 对等体例）；更新 `README.md` / `docs/agent_system/00-thesis.md` / `openspec/README.md` 引用
- **新 spec**：`openspec/specs/experimental-design/spec.md` —— 冻结 6 条 SHALL 规则
- **未来 change**：`policy-hack` / `metrics` / `social-graph` 的实验实现 SHALL 在 `## Why` 引用本 spec 的条款
- **代码**：零改动
- **测试**：零改动
- **前置依赖**：`multi-day-simulation`（必须先实现多日基建，本 change 的实验协议才能执行）
