# Change: tidy-project-layout

## Why

前置了 OpenSpec + 地图富化管线后，仓库里积压了一些"遗留现场"，叠加到
Phase 2（orchestrator / memory / social-graph / ...）之前现在是最便宜的
修复时机：

1. **`tools/map_explorer/mock_map.py` 是生产入口** —— 在一个叫 `mock_map`
   的文件里，实际承担 Lane Cove 真实 atlas 加载（`create_atlas_from_osm`
   988 行混着一个虚构 demo `create_atlas()`）。任何后续 agent/orchestrator
   模块都必须从"mock"目录 import，误导性极强。
2. **`tools/fetch_lanecove.py` 已经死掉**：被 `fetch_lanecove_v2.py` 全量替代
   （v2 是 `fetch_overture`、`mock_map` 依赖路径），但 v1 还躺着。
3. **4 份 proposal 级文档**（`项目提案.md` / `项目Brief.md` /
   `project-proposal.md` / `project-proposal-EN.md`）只有 `项目Brief.md`
   被 CLAUDE.md 引用；其它三份在仓库里看不清谁是 canonical。
4. **公共 API 不完整**：`synthetic_socio_wind_tunnel/__init__.py` 没有 re-export
   `agent.*` 与 `map_service.*`。这两个 Phase 1 模块在 CLAUDE.md 被列为核心
   服务，但外部代码 `from synthetic_socio_wind_tunnel import X` 拿不到。
5. **docs/ 无入口**：10 个文件 + 3 子目录，没有 README，新读者得自行拼装顺序。

没有任何一条单独是紧急的；合在一起做 Phase 2 起点会干净很多。

## What Changes

- **重组生产地图加载到 cartography 包内**
  把 `tools/map_explorer/mock_map.py` 中的生产函数拆出来成为
  `synthetic_socio_wind_tunnel/cartography/lanecove.py`：
  - `create_atlas_from_osm()`、`_infill_riverview()`、
    `create_demo_knowledge_maps()`、`create_ledger_with_demo_knowledge()`
  - 虚构 demo `create_atlas()`（新苑里社区）留在 `tools/map_explorer/demo_map.py`
  - `tools/map_explorer/server.py` 的 import 路径同步更新

- **删除过期工具脚本**
  - 删 `tools/fetch_lanecove.py`（v1）
  - 把 `tools/fetch_lanecove_v2.py` 重命名为 `tools/fetch_lanecove.py`

- **收束 proposal 文档**
  - 保留 `docs/项目Brief.md`（CLAUDE.md 指向、中文最全）作为 canonical
  - 把另外 3 份项目提案类文档移到 `docs/archive/`（保留历史但不占主目录视野）

- **补齐公共 API**
  - `synthetic_socio_wind_tunnel/__init__.py` 追加 re-export：
    `AgentProfile`、`AgentRuntime`、`Planner`、`DailyPlan`、`PlanStep`、`MapService`
  - 更新 `__all__`

- **新增 `docs/README.md` 索引**
  按"研究背景 / Agent 系统 / 地图管线 / 进度报告"分组，给出每份文档一句话说明

- **统一命名约定**
  在 `openspec/config.yaml` 的 `context` 里加一段命名惯例提示
  （kebab-case 文件名、模块 snake_case、生产代码 ≠ `mock_*`）

## Capabilities

### New Capabilities
<!-- 无 -->
（本 change 不引入新能力；纯粹是文件布局与公共 API re-export）

### Modified Capabilities
- `cartography`: Lane Cove 生产入口从 `tools/map_explorer/mock_map.py::create_atlas_from_osm`
  迁到 `synthetic_socio_wind_tunnel.cartography.lanecove.create_atlas_from_osm`；
  这是**唯一 spec 层面的变动**（入口路径）。Atlas 构造契约、富化流水线契约、
  连通度门禁都保持不变。

## Impact

### 受影响代码
- `tools/map_explorer/mock_map.py` 被拆 + 大部分迁出
- `tools/map_explorer/server.py` 更新 import
- `tools/map_explorer/__init__.py` 若暴露符号则更新
- `synthetic_socio_wind_tunnel/__init__.py` 增加 re-export
- `tools/fetch_lanecove.py` 被 v2 覆盖替换
- `docs/archive/` 新增；`docs/项目提案.md` / `project-proposal.md` /
  `project-proposal-EN.md` 位置迁移

### 不受影响（保持兼容）
- Atlas / Ledger / Engine / Perception / Agent / MapService 的模型与契约
- `make enrich-map` 行为（Makefile 目标内部命令路径更新但语义不变）
- `data/` 所有文件
- 测试测定的全部指标（连通度 ≥85%、富化门禁等）
- OpenSpec 归档的 `enrich-lanecove-map` 内容

### 迁移风险
- 外部脚本若直接 `from tools.map_explorer.mock_map import create_atlas_from_osm`
  会断。因为 `tools/` 不是正式包，这类 import 本来就脆弱；但我们保留一个**一行**
  的旧路径兼容 shim（`tools/map_explorer/mock_map.py` 里 `from ... import *`
  并打 `DeprecationWarning`）以保护过渡期。

### Non-goals
- **不**改任何模块的内部实现（只移动文件、调 import）
- **不**改任何已归档 spec 或 Phase 1 spec 的 Requirement 措辞
- **不**动 `data/`、`openspec/`、`tests/` 的测试内容（除了必要的 import 路径更新）
- **不**删除 `docs/项目提案.md` 等历史版本，只归档
- **不**引入新依赖
