# Project Thesis — 主边界与机制链

> **这是项目的 thesis 单一事实来源（single source of truth）**。
> 所有其它文档 SHALL 引用本文件，不重复陈述 thesis 全文。
>
> 由 `openspec/changes/thesis-focus/` 冻结于 2026-04-21。

---

## 一句话 thesis

> **手机注意力在高密度城市中制造物理社区的"隐形附近性盲区"；超在地性
> 反向推送能否把注意力——进而把人——带回"附近"？**

---

## 主边界

**Attention-induced Nearby Blindness**（注意力位移造成的附近性盲区）

| 维度 | 定义 |
|---|---|
| **研究对象** | agent 对 <500m 范围内物理事件的感知强度 vs 对手机推流内容的感知强度 |
| **产出信号** | trajectory 偏离、空间激活度、encounter 密度 |
| **干预入口** | `attention-channel`（feed 注入）——已在 `realign-to-social-thesis` 实现 |
| **可测量变量** | `AttentionState.allocation`、`NotificationEvent.urgency`、`FeedItem.hyperlocal_radius` |

---

## 机制链

主边界不是孤立的；它在四层链条的中段。其余三层**不是并列边界**，而是
机制链上的上下游位置：

```
algorithmic-input   →    attention-main    →   spatial-output    →   social-downstream
    (来源侧)                 (主边界)                (空间侧产出)           (下游验证)

推荐算法偏全球         ────►  agent 注意力     ────►  附近可达路径被         ────►  擦肩而过、
而非 hyperlocal                分配位移到屏幕         忽略、transit 化            无对视、
                                                                                  无社交触发
```

### 四层解读

| 层 | 研究位置 | 可测量变量 | 对应能力 |
|---|---|---|---|
| `algorithmic-input` | **输入侧**（feed 生成器） | feed 中 hyperlocal 内容的比例、算法偏向 | `attention-channel` / 未来 `policy-hack` |
| **`attention-main`** | **主边界**（研究焦点） | AttentionState、notification 接收率、hyperlocal_radius | `attention-channel`（已实现） |
| `spatial-output` | **空间侧产出** | trajectory 偏离、轨迹熵、空间激活热力图 | `orchestrator` + 未来 `metrics` |
| `social-downstream` | **下游验证** | encounter → conversation 转化率、弱关系增量 | 未来 `social-graph` + `conversation` |

---

## Chain-Position 门禁（Phase 2 前置）

**每块 Phase 2 change 的 `## Why` 章节 SHALL 声明**：

```
Chain-Position: <algorithmic-input | attention-main | spatial-output |
                social-downstream | infrastructure | observability>
```

**规则**：

1. 前四个值表示 change 直接服务于主边界机制链的某一层——必须说明它
   在该层是**新增能力 / 增强能力 / 连接上下游** 中的哪一种。
2. `infrastructure`：不在链条上，但为链条提供支撑（如 `memory` /
   `orchestrator` / `model-budget`）——必须说明**为什么不引入新边界**。
3. `observability`：跨层采集与报告（如 `metrics` / `fitness-audit`）——
   必须列出所测量的链上位置。
4. **不允许任何 change 引入新的并列"边界"概念**。任何新 capability 要么
   落在四层之一，要么必须显式归为 infrastructure / observability。

该门禁与现有 `fitness-report.json` 引用门禁**并列生效**——后者保证
change 有 Phase 1 实测缺口锚点，本门禁保证 change 在 thesis 链条上
有明确位置。

---

## Experimental Design Framework

实验哲学、实验协议、严谨度标准、伦理立场、报告结构——canonical 定义在
[`13-research-design.md`](13-research-design.md)；正式契约在
`openspec/specs/experimental-design/spec.md`。

要点摘录（以 canonical 文档为准）：
- **Rival Hypothesis Framing**：4 条 variant 绑定 4 种关于"附近性消亡"
  的 rival hypothesis（H_info / H_pull / H_meaning / H_structure）；
  实验是**诊断 contest**，不是 method testing
- **14-Day Protocol**：Baseline 4d + Intervention 6d + Post 4d；习惯形成
  + decay 同时可测
- **β 严谨度**：30 seed × median+IQR/CI；单 run 数字仅限 preliminary
- **Hybrid 伦理 + 4+1 Mirror**：A + A'（Global Distraction）等级交付；
  其它 3 条 mirror 文档化不实现
- **Diagnosis-Cure-Outcome-Interpretation 报告**：五幕结构 + 每 variant
  四段式

所有后续实验 change（`policy-hack` / `metrics` / `social-graph`）SHALL
引用 `experimental-design` spec 作为前置锚点。

---

## 当前证据（smoke experiment 2026-04-21）

`tools/smoke_experiment_demo.py` on Lane Cove atlas：

```
100 agents × 288 ticks, seed=42
─────────────────────────────────
target 组 AT target_location:  50 / 50  (100%)
control 组 AT target_location:  7 / 50  ( 14% 自然基线)
真实 treatment effect:  86 pp
trajectory median delta: +302m
wall time: 1.2s
```

**这直接对应 thesis 主边界的验证**：

> 注意力位移被反向推送打破后，物理轨迹可观测地向"附近"回归。

**注意**：smoke demo 只完成了链条前半段验证（attention → spatial-output）；
后半段（spatial → social-downstream）尚未闭环，需要 `social-graph` +
`conversation` 能力到位后才能跑。这是 Phase 2 优先级顺序的根据。

---

## 什么不再做（v1 → v2 降级表）

项目 Brief v1（`docs/项目Brief.md` §3.2）曾把以下四者**平列**为"四重
边界"。v2 收敛后：

| Brief v1 "边界" | v2 中的位置 | 降级说明 |
|---|---|---|
| 数字注意力边界 | **attention-main**（升为主边界） | 研究焦点、唯一干预入口 |
| 算法信息边界 | `algorithmic-input`（降为输入侧） | 不单独研究，通过 `policy-hack` 驱动 |
| 空间通勤边界 | `spatial-output`（降为空间侧产出） | 由 `metrics` 测量、不作独立 thesis |
| 社交心理边界 | `social-downstream`（升为下游验证） | 用来闭环 thesis，不作独立假设 |

v1 原文保留为 `docs/项目Brief.md` Appendix A，作为"开题期概念撒网"的
历史记录。

---

## 产品外溢（不属于研究范围）

以下在 Brief v1 中被列为交付物或核心组件，v2 收敛后明确标记为**产品外溢**
（"如果 thesis 验证成立，这套工具可以怎么用"）——**不是研究本身**：

- 城市规划者 / 社会学家面向的控制台 UI（Brief §7.5）
- 参与式设计工作坊接入（Brief §9.5 "引入参与式设计"）
- 反哺现实社区的改造流程（Brief §9.5 "反哺现实"）
- 多场地切换（当前场地冻结为 Lane Cove）

这些条目在 answer session / 未来商业化时可以引用；在研究 deliverable 中
**不单独 gate**。

---

## 参考链路

| 资产 | 位置 |
|---|---|
| 主线实施归档 | `openspec/changes/archive/2026-04-2*-*` |
| 活跃契约 | `openspec/specs/*` |
| 场地底板（已冻结） | `data/lanecove_atlas.json` |
| 适配度审计 | `make fitness-audit` → `data/fitness-report.json` |
| 证据 smoke | `tools/smoke_experiment_demo.py` + `docs/agent_system/11-smoke-demo-report.md` |
| 原始开题 Brief | `docs/项目Brief.md`（v2 在前、v1 作 Appendix A） |
| 方法论框架（Stingray） | `docs/WIP-progress-report.md` Page 3 |

---

## 术语对照（英中 / 学术 → 代码）

| 概念 | 英文 | 代码/契约对应 |
|---|---|---|
| 主边界 | Attention-induced Nearby Blindness | —（无单一类；由 attention-channel 能力整体表达） |
| 数字注意力位移 | Attention Displacement | `AttentionState.allocation` |
| 超在地性推送 | Hyperlocal Push | `FeedItem.hyperlocal_radius` + `NotificationEvent` |
| 附近性盲区 | Nearby Blindness | `digital_attention` perception filter 削减 subjective view |
| 弱关系 | Granovetter weak ties | 未来 `social-graph.tie_strength` |
| 偶遇 | Serendipity | 未来 `metrics.encounter_diversity` |
| 第三空间 | Third Places | Lane Cove POI 数据中 `category ∈ {cafe, pub, park}` |
