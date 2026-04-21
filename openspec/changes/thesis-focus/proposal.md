## Why

`realign-to-social-thesis` 把 `attention-channel` 提升为一级能力；`memory` /
`orchestrator` / `typed-personality` 三次 change 的实施与 2026-04-21 的 smoke
experiment（100 agents × 288 ticks，Lane Cove）共同产出了第一条可测量的
thesis 信号：target 组 100% 到达推送地点、control 组 14% 自然基线、trajectory
median delta +302m。这**直接对应"注意力位移是主机制"这一条 thesis 主边界**。

然而，项目文档仍停留在 Brief v1 的"**四重边界**"平列表述（README §The
Problem、`项目Brief.md` §3.2、`WIP-progress-report.md` Page 2），导致：

1. **答辩风险**：被问"研究的到底是哪个边界"时，文档会把四条线都说一遍——
   失去贡献的特异性。`Attention-induced Nearby Blindness` 本来已是事实主线，
   却在文档层没有升格。
2. **未来 change 失焦**：phase-2-roadmap 的 7 个能力没有"在机制链中的位置"
   标签，容易出现"为做而做"的能力（典型误区：把 `social-graph` 写成独立的
   社交边界研究，而不是 thesis 下游的**验证层**）。
3. **smoke 证据未挂回 thesis**：`delta +302m / 100% vs 14%` 本来是对"注意力
   位移主边界"的直接验证，文档层面没有这条从证据回到 thesis 的引用。

本 change 是 **docs-only 的 thesis 收敛**，不改任何代码、不引入任何能力。
它为未来所有 Phase 2 change 建立"在主线上的位置感"。

（说明：本 change 的动机来自 smoke demo + 归档 change 的既成事实，而非
`fitness-report.json` 的 `fail/skip` 条目——因为 thesis 收敛本身不是
infrastructure capability，不走 `mitigation_change` 锚点。phase-2-roadmap 的
fitness-report 引用门禁继续适用于其它**代码层**的 Phase 2 change。）

## What Changes

### 1. 从"四重边界"收敛到"一主三机制"

**主边界（MAIN）**：`Attention-induced Nearby Blindness`
（注意力位移造成的附近性盲区）

**机制链**：

```
algorithmic-input  →  attention-main  →  spatial-output  →  social-downstream
  (来源侧)             (主边界)            (空间侧产出)         (下游验证)
```

Brief v1 的其余三条边界重新归位：

| Brief v1 | v2 中的位置 | 对应能力 |
|---|---|---|
| 算法信息边界 | **algorithmic-input**：feed 内容来源 | attention-channel / policy-hack |
| 数字注意力边界 | **attention-main**：主研究焦点 | attention-channel（已实现） |
| 空间通勤边界 | **spatial-output**：可测量的产出 | orchestrator + metrics |
| 社交心理边界 | **social-downstream**：闭环验证 | social-graph + conversation |

### 2. 新增 canonical thesis 文件

`docs/agent_system/00-thesis.md` 冻结：
- 主边界定义与可测变量
- 四层机制链图
- 与现有能力的对应关系
- smoke demo 已产出的证据锚点
- `Chain-Position` 门禁条款

所有其它文档 SHALL 引用此文件，不再各自表述 thesis 全文。

### 3. 新增 `Chain-Position` 门禁

phase-2-roadmap 现有门禁是"每块 Phase 2 change 的 `## Why` SHALL 引用
`fitness-report.json` 条目"。本 change **在其之上叠加一条**：

> 每块 Phase 2 change 的 `## Why` SHALL 声明其 `Chain-Position` 属于
> 以下之一：`algorithmic-input` / `attention-main` / `spatial-output` /
> `social-downstream` / `infrastructure` / `observability`。
>
> 前四者必须说明自己在主边界链上服务的位置；后两者必须解释为什么不在
> 链条上（即只是基础设施 / 可观测性支撑，不引入新的平行边界）。

**不在链条上的 change MUST NOT 引入新的并列"边界"概念**——任何新 capability
要么落在四层之一，要么是 infrastructure / observability。

### 4. 同步 8 处文档

- `README.md`（顶层 thesis 段）
- `docs/项目Brief.md`（§3 加 v2 收敛章节，v1 保留为历史附录）
- `docs/WIP-progress-report.md`（Page 2 边界分类）
- `CLAUDE.md`（Project Overview 一句话）
- `openspec/README.md`（顶部加 thesis 指针）
- `openspec/changes/phase-2-roadmap/proposal.md`（`## Why` 接入 thesis chain）
- `openspec/changes/phase-2-roadmap/tasks.md`（前置说明加入 Chain-Position 门禁）
- `docs/agent_system/03-干预机制与实验指标.md`（五类干预按 chain 归类）

## Non-goals

- **不**改任何代码、任何 `specs/*/spec.md` 契约
- **不**撤销或改写任何已归档 change
- **不**引入新能力（orchestrator / memory / attention-channel 等已实现能力不动）
- **不**限定 `metrics` / `social-graph` 的具体技术方案——只钉它们在 thesis
  链条上的位置
- **不**回填历史 change 的 `Chain-Position`——新门禁**只对未来 change 生效**
- **不**删除 Brief v1 的四重边界原文——保留为"开题期表述"的历史附录

## Impact

- **文档**：8 个文件更新 + 1 个新增（`docs/agent_system/00-thesis.md`）
- **未来 change**：新增 `Chain-Position` 门禁——下一块 change（无论是
  `social-graph` / `metrics` / `policy-hack` / `conversation` / `model-budget`）
  开 proposal 时必须声明自己在链条上的位置
- **答辩**：thesis 从"四重边界"变成"一主三机制 + 链上位置"，一句话答辩
  "这是一个关于注意力位移制造附近性盲区的研究，主边界是 attention，
  其它三层是机制链上的上下游"
- **代码**：零改动
- **测试**：零改动
