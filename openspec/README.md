# OpenSpec for Synthetic Socio Wind Tunnel

本目录按能力（capability）维度组织项目的契约。参考原始文档见
`docs/项目Brief.md`、`docs/agent_system/*`、`docs/map_pipeline/*`。

## Project Thesis（每块 change 开工前必读）

项目研究的**主边界**：`Attention-induced Nearby Blindness`（注意力位移
造成的附近性盲区）。其余三层（`algorithmic-input` / `spatial-output` /
`social-downstream`）是机制链上的上下游位置，不是平列边界。

Canonical thesis + `Chain-Position` 门禁：
[`docs/agent_system/00-thesis.md`](../docs/agent_system/00-thesis.md)。

每块 Phase 2 change 的 `## Why` SHALL 声明 Chain-Position（见 00-thesis.md
的"Chain-Position 门禁"章节）。

## Experimental Design（每块实验 change 必读）

实验哲学、14 天协议、β 严谨度、Hybrid 伦理立场、五幕报告结构——canonical
在 [`docs/agent_system/13-research-design.md`](../docs/agent_system/13-research-design.md)；
正式契约（6 条 SHALL）在 `specs/experimental-design/spec.md`（归档后）。

所有实验实现 change（`policy-hack` / `metrics` / `social-graph` 等）的
`## Why` SHALL 引用 `experimental-design` spec。基建执行能力见
`changes/multi-day-simulation/`。

## 已冻结能力（Phase 1 — 已实现）

位于 `specs/<capability>/spec.md`：

| 能力 | 模块路径 | 说明 |
|---|---|---|
| [core](specs/core/spec.md) | `synthetic_socio_wind_tunnel/core/` | 坐标、多边形、WorldEvent、错误码 |
| [atlas](specs/atlas/spec.md) | `synthetic_socio_wind_tunnel/atlas/` | 只读静态布景（Region/Building/Room/Street/Connection/BorderZone） |
| [ledger](specs/ledger/spec.md) | `synthetic_socio_wind_tunnel/ledger/` | 可变世界状态与每 agent 认知地图 |
| [simulation](specs/simulation/spec.md) | `synthetic_socio_wind_tunnel/engine/simulation.py` | 移动、开门、拾取等写操作 |
| [navigation](specs/navigation/spec.md) | `synthetic_socio_wind_tunnel/engine/navigation.py` | 门感知的 A* 路径规划 |
| [collapse](specs/collapse/spec.md) | `synthetic_socio_wind_tunnel/engine/collapse.py` | 薛定谔细节生成 + 证据蓝图 |
| [perception](specs/perception/spec.md) | `synthetic_socio_wind_tunnel/perception/` | 主观视角管线 + 认知可见性 |
| [cartography](specs/cartography/spec.md) | `synthetic_socio_wind_tunnel/cartography/` | OSM 导入 + 编程式 RegionBuilder |
| [agent](specs/agent/spec.md) | `synthetic_socio_wind_tunnel/agent/` | Planner + AgentRuntime + Profile |
| [map-service](specs/map-service/spec.md) | `synthetic_socio_wind_tunnel/map_service/` | agent 面向的统一查询 API |

## 待实现（Phase 2 — 路线图）

见 `changes/phase-2-roadmap/`：

- `memory` — agent 三层记忆（事件流 / 日摘要 / 反思）
- `social-graph` — agent 间关系、弱关系指标
- `orchestrator` — tick 循环、路径相遇、冲突裁决
- `model-budget` — 每 agent 每 tick 的模型层级决策
- `policy-hack` — 统一干预注入（5 类数字干预）
- `conversation` — 广播式多方对话、信息跳数
- `metrics` — 四类实验指标与对比组复现

每块进入实现前 SHALL 各自写独立 change proposal，细化 Scenario。

## 编写规则

见 `config.yaml` 的 `rules` 段：
- Requirement 使用 SHALL/MUST/SHOULD；
- 每条至少配一个 Scenario（WHEN/THEN）；
- 引用代码符号使用 `module.ClassName` 全称；
- 中文为主，专有术语保留英文。
