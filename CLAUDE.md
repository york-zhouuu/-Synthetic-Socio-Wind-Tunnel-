# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## 关键参数（事实校正）

- **agent 数量：1000**（不是 100；100 是 smoke 配置）
- **hyperlocal 推送半径：1000 米**（不是 500m）
- 14 天协议：4 baseline + 6 intervention + 4 post
- β rigor：30 seed for publishable

任何对外文档/报告引用这两个数字时务必用 1000 / 1000m。

## 关键不变量（fix-population-uses-typed-locations 2026-05-12）

- **agent.home_location SHALL 是 `building_type == "residential"` 的 building id**——
  不可以是 outdoor street segment（旧 bug：`_pick_connected_destinations` 只从
  outdoor 单池采样，导致 14 天 dwell 93% 在街上、0% 在 residential）
- agent 居住 / 工作 / POI 三池 SHALL 用 `build_location_pools(atlas, ...)` 构造，
  返回 `LocationPools(home_pool, work_pool, poi_pool, target_location)`，
  通过 `validate(atlas)` 校验三池 disjoint + 同一连通分量
- variant push `target_location` SHALL 来自 poi_pool（community / cafe / park），
  不再是 outdoor street
- dwell acceptance（baseline run）：residential ≥ 40% / street ≤ 20%；
  违反 `tools/audit_dwell_distribution.py` 即报警

## 对外报告与产出物的叙述风格（严格遵守）

参考样板：`docs/项目产出物.html`。任何"对外解释项目"的文档（产出物说明 / progress
report / pitch / 五幕报告 / 给非研发受众的总结）SHALL 按以下风格写：

1. **从日常生活场景切入，不从技术名词切入**。例：用"你认识楼上邻居吗"开头，
   而非"研究 attention-induced nearby blindness"。
2. **主线叙述里禁用技术黑话**——把 hyperlocal_push / encounter density /
   trajectory_deviation_m / variant 这类词翻译成"超在地推送"/"偶遇频率"/
   "走路路线"/"对照组"等中文白话，技术名作为副标题或脚注出现。
3. **每个产出物 / 章节用三段固定结构**：
   - **是什么**：白话描述 + 简短技术注脚
   - **解决什么问题**：用引号引一句"读者会问的问题"
   - **意义**：为什么没了它项目就不完整 / 这块在整个研究里的位置
4. **对照实验组用日常语言重命名**：
   - baseline → "对照组：什么都不推"
   - hyperlocal_push → "实验组（核心）：超在地推送"
   - global_distraction → "镜像组：推全球新闻"
   - phone_friction → "反技术组：减少手机吸引力"
5. **用真实城市名 / 街道名 / 数字让读者落地**——例如"Cowper 街口附近的偶遇密度
   从冷蓝色变成了热橙色"，而不是"location_id=cowper_street_seg_1 的 encounter
   count 提升了"。
6. **用 pullquote / panel / card 等视觉模块强化关键句**，而不是依赖纯文字段落。
7. **不要把"做了什么"和"为什么有意义"混在一起讲**——把现象、假设、方法、产出
   分章拆开，每章一个核心问题。

样板 HTML 的 6 大产出物白话名（之后的报告复用）：

| 技术名 | 对外白话名 |
|---|---|
| 实验证据 / contest.json | **实验答案** |
| 五幕报告 | **研究故事** |
| 可视化 HTML | **地图与图表** |
| 模拟系统代码 | **可运行的虚拟城市** |
| 复现性 lock | **可验证的研究记录** |
| 文档体系 | **研究知识库** |

## Project Overview

Synthetic Socio Wind Tunnel 是一个 AI 多智能体城市社会推演系统，研究 **Attention-induced Nearby Blindness**（注意力位移造成的附近性盲区）——手机注意力如何在高密度城市制造物理社区的"看不见的邻居"，以及超在地性反向推送能否把注意力、进而把人带回"附近"。

主边界是 `attention-main`；其余三层（`algorithmic-input` / `spatial-output` / `social-downstream`）是机制链上的上下游位置，而非平列边界。Canonical thesis 见 `docs/agent_system/00-thesis.md`，是所有 Phase 2 change 的 `Chain-Position` 门禁来源。

实验哲学与实验设计规格见 `docs/agent_system/13-research-design.md`（rival hypothesis framing / 14 天协议 / β 严谨度 / Hybrid 伦理 / 五幕报告结构），正式契约在 `openspec/specs/experimental-design/spec.md`。

技术上采用 CQRS（命令查询职责分离）架构，核心理念是"剧组模型"——将静态布景（Atlas）与动态道具状态（Ledger）分离。

## Project Structure

```
synthetic_socio_wind_tunnel/
├── synthetic_socio_wind_tunnel/              # 核心模块
│   ├── __init__.py          # 公共 API 导出
│   ├── core/                # 共享类型 (Coord, Polygon)
│   ├── atlas/               # 🎭 静态地图 (只读)
│   │   ├── models.py        # Region, Building, Room, DoorDef, ContainerDef
│   │   └── service.py       # Atlas 查询服务
│   ├── ledger/              # 📋 动态状态 (读写)
│   │   ├── models.py        # EntityState, ItemState, DoorState, EvidenceBlueprint
│   │   └── service.py       # Ledger CRUD
│   ├── engine/              # ⚙️ 写操作
│   │   ├── simulation.py    # SimulationService (移动、开门)
│   │   ├── collapse.py      # CollapseService (薛定谔细节生成)
│   │   └── navigation.py    # NavigationService (路径规划)
│   ├── perception/          # 📷 读操作
│   │   ├── models.py        # ObserverContext, SubjectiveView
│   │   ├── pipeline.py      # PerceptionPipeline
│   │   ├── exploration.py   # ExplorationService (认知地图)
│   │   └── filters/         # 环境、听觉、嗅觉、技能滤镜
│   └── cartography/         # 🗺️ 地图构建 (离线)
│       ├── importer.py      # GeoJSON 导入
│       └── builder.py       # 编程式构建
├── tests/                   # 测试代码
└── docs/                    # 设计文档
```

## Commands

```bash
# 安装依赖
pip install -e ".[dev]"      # 开发环境
pip install -e ".[full]"     # 完整功能 (LLM + Web)

# 运行测试
python -m pytest tests/ -v

# 验证导入
python -c "from synthetic_socio_wind_tunnel import *; print('All imports OK')"

```

## Architecture Concepts

### CQRS 分离
- **Atlas (布景组)**: 只读静态地图，定义墙、门、容器
- **Ledger (道具组)**: 读写动态状态，管理位置、物品、证据

### 核心服务
- **SimulationService**: 写操作（移动、开门、发现线索）
- **CollapseService**: 薛定谔细节生成（首次检查时生成内容）
- **PerceptionPipeline**: 读操作（主观视角渲染）
- **ExplorationService**: 认知地图（角色探索记录）
- **NavigationService**: 路径规划（门感知路由）

### 关键特性
- **空间预算系统**: 容器有容量限制
- **证据蓝图系统**: 剧情必需证据保证出现
- **罗生门效应**: 同一场景不同角色看到不同内容
- **多模态感知**: 视觉、听觉、嗅觉

## Key Files for Modifications

- `synthetic_socio_wind_tunnel/engine/simulation.py` - 移动和交互逻辑
- `synthetic_socio_wind_tunnel/engine/collapse.py` - 细节生成逻辑
- `synthetic_socio_wind_tunnel/perception/pipeline.py` - 感知渲染
- `synthetic_socio_wind_tunnel/perception/filters/` - 添加新滤镜
- `synthetic_socio_wind_tunnel/atlas/models.py` - 静态数据模型
- `synthetic_socio_wind_tunnel/ledger/models.py` - 动态数据模型

## Documentation

- `docs/项目Brief.md` - 项目总体方案、理论框架、三大实验设计
- `docs/agent_system/` - Agent 系统架构设计（01~06）
- `docs/map_pipeline/` - 地图构建方案（OSM 导入 + 编程式构建）
- `docs/WIP-progress-report.md` - 当前进度汇报

## Testing

```bash
# 运行所有测试
python -m pytest tests/ -v

# 运行特定测试
python -m pytest tests/test_atlas.py -v
python -m pytest tests/test_ledger.py -v
python -m pytest tests/test_perception.py -v
python -m pytest tests/test_cartography.py -v
python -m pytest tests/test_agent_phase1.py -v
```
