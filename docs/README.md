# docs — 项目文档索引

按"读这份是为了弄清什么"分组。CLAUDE.md 只认路的人可以直接从这里导航。

## 研究背景与总体方案

- **[项目Brief.md](项目Brief.md)** — Canonical。项目总体方案、理论框架、
  三大实验设计（Digital Lure / Spatial Unlock / Shared Perception）、
  成本与模型预算的决策理由。新同事/新 AI agent 读这一份即可定位全局。

## Agent 系统设计

系列六篇，从总体到实操。建议按顺序读：

- [agent_system/01-总体架构.md](agent_system/01-总体架构.md) — 计划式 LLM agent
  + 分层模型预算的总体思路
- [agent_system/02-核心模块设计.md](agent_system/02-核心模块设计.md) — 核心
  服务（Simulation / Collapse / Perception / Navigation）的职责与契约
- [agent_system/03-干预机制与实验指标.md](agent_system/03-干预机制与实验指标.md)
  — 五种干预注入（广告/推送/海报/活动/邻里）+ 四类实验指标
- [agent_system/04-代码改动清单与执行计划.md](agent_system/04-代码改动清单与执行计划.md)
  — 早期版本的实施计划；以 `openspec/` 当前状态为准，这份做背景参考
- [agent_system/05-补充-路径相遇与广播社交.md](agent_system/05-补充-路径相遇与广播社交.md)
  — 路径相遇检测、广播式多方对话、信息跳数追踪的细节
- [agent_system/06-当前进度与下一步.md](agent_system/06-当前进度与下一步.md)
  — 阶段性总结（历史视角）；当前进度以 WIP-progress-report.md 为准

## 地图管线

- [map_pipeline/01-Pipeline总览.md](map_pipeline/01-Pipeline总览.md) — OSM
  → Atlas 的两阶段管线（几何 + LLM 富化）总览
- [map_pipeline/02-数据模型与代码改动.md](map_pipeline/02-数据模型与代码改动.md)
  — Atlas / Ledger 模型细节 + 地图导入改动清单
- [map_pipeline/03-实操指南.md](map_pipeline/03-实操指南.md) — 从选址到
  atlas 产出的一步步操作指南，含 Overture 多源富化流程图
- [map_service_design.md](map_service_design.md) — MapService（agent 面向
  的统一查询接口）设计
- [architecture.md](architecture.md) — CQRS 架构总览（Atlas / Ledger /
  Engine / Perception / MapService）的关系图

## 进度与规划

- **[WIP-progress-report.md](WIP-progress-report.md)** — 最新的实施进度
  快照（随迭代更新）

## 可视化资源

- [figures/](figures/) — 演示截图（轨迹热图、社交网络、指标时间线）
  由 `tools/mock_simulation.py --save` 生成

## 历史归档

- [archive/](archive/) — 废弃但保留的历史版本（旧版项目提案等）
