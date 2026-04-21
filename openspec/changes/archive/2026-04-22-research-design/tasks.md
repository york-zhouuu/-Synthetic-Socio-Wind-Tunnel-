# Tasks — research-design

本 change 为**实验哲学 + 实验设计的规格冻结**。不改代码、不跑实验；仅把
决策落到文档与 spec。

**依赖**：无前置；与 `multi-day-simulation`（基建 change）可并行。

## 1. Canonical research-design 文件

- [x] 1.1 创建 `docs/agent_system/13-research-design.md`（与 `00-thesis.md`
  对等体例的 canonical 实验设计文档），内容包括：
  - **Part I: Research Posture** — 探索性项目四轴（认知论 / 验证 / 交付 / 伦理）
  - **Part II: Rival Hypothesis Framing** — 四种诊断（H_info / H_pull /
    H_meaning / H_structure）+ 理论传统绑定（Shannon / Simon-Wu /
    Putnam-MacIntyre / Granovetter-Burt）+ 每诊断的 cure 操作化
  - **Part III: 14-Day Protocol** — Baseline 4d / Intervention 6d / Post 4d
    的结构 + 每 phase 的测量重点
  - **Part IV: β Rigor Standard** — 30 seed × IQR/CI + dev vs publishable 模式
  - **Part V: Ethics + Mirror** — Hybrid 立场 + 4+1 mirror 规则 +
    Ethics Statement + 其它 mirror scenario 附录
  - **Part VI: Report Structure** — Act 1-5 戏剧结构 + Variant 内部
    Diagnosis-Cure-Outcome-Interpretation 四段式

## 2. spec 冻结

- [x] 2.1 归档 `specs/experimental-design/spec.md` 的 6 条 ADDED Requirement
  到 `openspec/specs/experimental-design/spec.md`（archive 时自动由
  openspec 流程完成）

## 3. 上游文档引用更新

- [x] 3.1 `docs/agent_system/00-thesis.md`：在 "Chain-Position 门禁" 章节
  之后新增一段 "Experimental design framework"，单段引用
  `13-research-design.md` 为 canonical
- [x] 3.2 `README.md`：在 "What This Is Not" 前加 "Research Posture" 一段
  （Exploratory instrument / Cloud-chamber analogy [云室 naming TBD] /
  Dual-use explicit / No deployment endorsement）
- [x] 3.3 `openspec/README.md`：在 "Project Thesis" 段后新增 "Experimental
  design" 指针，链接 `13-research-design.md` 与 `openspec/specs/experimental-design/`
- [x] 3.4 `CLAUDE.md` Project Overview：在 thesis 段之后新增一行 "实验
  设计规格见 `docs/agent_system/13-research-design.md`"
- [x] 3.5 `docs/项目Brief.md` §5.4 "实验输出的戏剧结构"：新增 v2 收敛
  banner 指向 `13-research-design.md`（原 §5.4 的 BEFORE/INTERVENTION/
  AFTER/STORIES 四幕被 Act 1-5 五幕替代；v1 保留为历史附录）

## 4. phase-2-roadmap 补丁

- [x] 4.1 `openspec/changes/phase-2-roadmap/proposal.md` `## Why`：在
  7 块能力表下新增一行——"所有实验实现（`policy-hack` / `metrics` /
  `social-graph`）SHALL 引用 `experimental-design` spec 作为前置锚点"
- [x] 4.2 `openspec/changes/phase-2-roadmap/tasks.md`：为 `policy-hack` /
  `metrics` / `social-graph` 各条加一行 "前置：`experimental-design` spec
  + `multi-day-simulation` 基建"

## 5. 附录：其它 mirror scenarios 文档化

- [x] 5.1 `13-research-design.md` 附录 A 新增：
  - **Spatial Gating mirror**（对应 Experiment 2 正向的 Spatial Unlock）
  - **Fragmented Perception mirror**（对应 Experiment 3 的 Shared Perception）
  - **Catalyst Seeding mirror: anti-connector seeding**（对应 variant D 正向）
  - **Phone Attraction Boost**（对应 variant B Phone Friction 的 mirror）
  每条 2-3 句 scenario spec，文档化 preserve dual-use 显式性

## 6. 验证

- [x] 6.1 `openspec validate research-design --strict` 通过
- [x] 6.2 grep 检查：`Rival Hypothesis | Diagnosis-Cure-Outcome-Interpretation`
  在 13-research-design.md 与 experimental-design spec 中各被找到
- [x] 6.3 Read 13-research-design.md 全文自检：6 个 Part 齐全；引用了
  `multi-day-simulation` 作为基建前置
- [x] 6.4 确认未改动任何 `synthetic_socio_wind_tunnel/` 下代码文件
- [x] 6.5 确认未改动任何 `tests/` 下测试文件
