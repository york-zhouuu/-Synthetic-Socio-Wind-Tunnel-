# docs — 项目文档索引

按"读这份是为了弄清什么"分组。CLAUDE.md 只认路的人可以直接从这里导航。

> **2026-05-08 更新**：early docs（3 月编写）已加 `STALE` 标记并标注现行的
> canonical 替代位置；Apr–May 写的 `13-` / `18-` / `19-` / `20-` 是当前
> 权威。openspec/ 下的 specs/ + 已归档的 changes/archive/ 是真正的 source
> of truth；docs 只承担"为什么这么做"的解释职责。

---

## 当前权威（先读这些）

| 主题 | Canonical 文档 |
|---|---|
| Thesis 主论证 | [`agent_system/00-thesis.md`](agent_system/00-thesis.md) |
| 实验设计（Rival Hypothesis / β-rigor / 14d 协议 / 五幕报告）| [`agent_system/13-research-design.md`](agent_system/13-research-design.md) |
| 验证策略（Validity 取舍 / 8 项 pre-publication checklist）| [`agent_system/18-validation-strategy.md`](agent_system/18-validation-strategy.md) |
| **System snapshot**（当前能力 / Gap 列表 / 历史决策点） | [`agent_system/19-system-snapshot.md`](agent_system/19-system-snapshot.md) |
| **Realism roadmap**（agent 拟真度的 6 维 + 5 阶段路径） | [`agent_system/20-realism-roadmap.md`](agent_system/20-realism-roadmap.md) |

---

## 研究背景与总体方案

- **[项目Brief.md](项目Brief.md)** — Canonical（背景层）。项目总体方案、
  理论框架、三大实验设计（Digital Lure / Spatial Unlock / Shared
  Perception）、成本与模型预算的决策理由。**注意**：写于 2026-04-22，
  之后的 4 个 changes（attention-rebalance / social-graph / conversation /
  push-content-individualization）见 19-system-snapshot.md。

## Agent 系统设计（按主题，不是按时间序）

**当前权威**：
- [`agent_system/00-thesis.md`](agent_system/00-thesis.md) — 主论证 +
  Chain-Position 门禁
- [`agent_system/13-research-design.md`](agent_system/13-research-design.md)
  — 实验设计契约
- [`agent_system/18-validation-strategy.md`](agent_system/18-validation-strategy.md)
  — 8 项 publishable checklist + audit 协议
- [`agent_system/19-system-snapshot.md`](agent_system/19-system-snapshot.md)
  — 当前能力快照 + 历史决策点表
- [`agent_system/20-realism-roadmap.md`](agent_system/20-realism-roadmap.md)
  — 拟真度路线图

**历史决策（07–17）**：每个对应一个已 archive 的 openspec change，做"为什么
当时这么决定"的背景解释；具体 spec 在 `openspec/specs/`：

- [`07-审计报告解读.md`](agent_system/07-审计报告解读.md) — fitness audit
- [`08-orchestrator-tick-loop.md`](agent_system/08-orchestrator-tick-loop.md)
  — orchestrator 设计
- [`09-memory-and-replan.md`](agent_system/09-memory-and-replan.md) —
  memory + replan
- [`10-typed-personality.md`](agent_system/10-typed-personality.md) — 8 维
  人格 typed model
- [`11-smoke-demo-report.md`](agent_system/11-smoke-demo-report.md) — 第一次
  端到端 smoke 数据
- [`14-multi-day-simulation.md`](agent_system/14-multi-day-simulation.md) —
  N 日调度
- [`15-policy-hack.md`](agent_system/15-policy-hack.md) — 4+1 variant 框架
- [`16-metrics.md`](agent_system/16-metrics.md) — Contest scorer + 五幕报告
- [`17-suite-wiring.md`](agent_system/17-suite-wiring.md) — variant→memory
  →replan→behavior 装配

**早期 (3 月) — STALE，仅作历史参考**：
- [`01-总体架构.md`](agent_system/01-总体架构.md) — 计划式 LLM agent 总体思路
- [`02-核心模块设计.md`](agent_system/02-核心模块设计.md) — 核心服务契约
- [`03-干预机制与实验指标.md`](agent_system/03-干预机制与实验指标.md) — 早期
  五种干预注入（已被 policy-hack 4+1 变体取代，见 15-）
- [`04-代码改动清单与执行计划.md`](agent_system/04-代码改动清单与执行计划.md)
  — 早期实施计划（已被 openspec/ 取代）
- [`05-补充-路径相遇与广播社交.md`](agent_system/05-补充-路径相遇与广播社交.md)
  — 路径相遇 + 广播多方对话（路径相遇已 ship；广播多方对话部分留 V2，见
  conversation-capability archive）
- [`06-当前进度与下一步.md`](agent_system/06-当前进度与下一步.md) —
  3 月时的进度（已被 19-system-snapshot.md 替代）

## 地图管线

- [`map_pipeline/03-实操指南.md`](map_pipeline/03-实操指南.md) — Canonical
  实操：从选址到 atlas 产出的一步步操作，含 Overture 多源富化流程图
- [`map_pipeline/04-reading-the-atlas.md`](map_pipeline/04-reading-the-atlas.md)
  — Canonical：跑出来的 atlas 怎么读（outdoor_areas / buildings 索引语义）
- [`map_service_design.md`](map_service_design.md) — MapService（agent 面向
  的统一查询接口）设计

**早期 (3 月) — STALE**：
- [`map_pipeline/01-Pipeline总览.md`](map_pipeline/01-Pipeline总览.md) —
  早期 OSM → Atlas 两阶段管线（已被 03 + 04 + cartography 模块取代）
- [`map_pipeline/02-数据模型与代码改动.md`](map_pipeline/02-数据模型与代码改动.md)
  — 早期 Atlas/Ledger 模型 + 改动清单（数据模型仍正确；改动清单失效，见
  openspec/changes/archive/）

## 架构与 Schema

- [`architecture.md`](architecture.md) — **STALE (3 月)**。CQRS 总览仍正确；
  各服务现状以 19-system-snapshot.md 的 capability 矩阵为准。

## 进度与规划

- **[项目状态.md](项目状态.md)** — 顶层 status board（latest）
- **[sessions/](sessions/)** — 按日的工作日志 / smoke 报告（2026-05-10 起）
- **[audit/](audit/)** — 系统审计报告（realism 11 维、deep issues、bug hunt）
- **[limitations-ethics.md](limitations-ethics.md)** — Publishable 限制 +
  伦理边界 + 旧实验数据局限
- **[WIP-progress-report.md](WIP-progress-report.md)** — **2026-04-21
  时点快照（STALE）**。最新进度以 项目状态.md 为准。

## 对外发布物

- **[项目产出物.html](项目产出物.html)** — 6 大产出物公众解释（叙述风格样板）
- **[四个对照组.html](四个对照组.html)** — baseline / hp / gd / pf 公众解释

## 校准 / 评估数据

- [`calibration/`](calibration/) — Lane Cove ABS Census 2021 校准数据
  + stereotype audit 报告
- [`face_validity/`](face_validity/) — Prolific 真人评分协议 + （待跑）
  实测数据

## 可视化资源

- [`figures/`](figures/) — 演示截图（轨迹热图、社交网络、指标时间线）
  由 `tools/visualize_run.py` / `tools/mock_simulation.py --save` 生成

## 历史归档

- [`archive/`](archive/) — 废弃但保留的历史版本（旧版项目提案等）
