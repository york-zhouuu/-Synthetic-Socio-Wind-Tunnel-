# Design — tidy-project-layout

## Context

Phase 1（Atlas/Ledger/Engine/Perception/Cartography/Agent/MapService）+ map
enrichment（Overture + 住宅语义）已落地。Phase 2（orchestrator / memory /
social-graph / model-budget / policy-hack / conversation / metrics）马上
要开工。开工前有三类欠账会持续放大摩擦：

- 生产入口埋在名字叫 `mock_*` 的文件里（`tools/map_explorer/mock_map.py`）
- `tools/` 目录混有 v1 / v2 两份相同用途的脚本
- `docs/` 累积了多版 proposal，但只有一份是 canonical
- 公共 API `synthetic_socio_wind_tunnel/__init__.py` 没有 export 新加的
  `agent` 与 `map_service` 模块

这些是**纯布局问题**——没有契约错、没有实现错；每处单独看都可以容忍。
叠在 Phase 2 的新模块之上会迅速复利：新模块要么继续沿着错的路径 import，
要么在 Phase 2 内再做一次重排。

## Goals / Non-Goals

**Goals**

- 把"生产代码"和"demo / mock 代码"在**目录层面**分开，名字自解释
- 公共包 API 与 CLAUDE.md 声称的能力一一对应（agent / map_service 可从
  `synthetic_socio_wind_tunnel` 顶层 import）
- 保留历史文档但不占主目录视野
- `tests/` 和 `data/` 零改动（只有 `tests/` 里若有跟 mock_map 相关的 import
  需要跟随迁移）
- 无新外部依赖；所有 CLI 与 Makefile 目标外部行为不变

**Non-Goals**

- 不重写任何模块的内部实现
- 不改变任何 Phase 1 spec 的 Requirement
- 不新增测试；仅保证现有 112 passed / 1 skipped 继续通过
- 不做更大规模的"Python 包化"改造（例如把 tools 提升为正式 subpackage），
  那是 Phase 2 之后独立讨论的题目

## Decisions

### D1. 生产入口搬到 `cartography.lanecove`

**决定**：新建 `synthetic_socio_wind_tunnel/cartography/lanecove.py`，迁入：
- `create_atlas_from_osm(path=..., segment_length=...) -> Atlas`
- `_infill_riverview(region) -> Region`
- `create_demo_knowledge_maps(atlas) -> dict[str, AgentKnowledgeMap]`
- `create_ledger_with_demo_knowledge(atlas) -> Ledger`

**替代方案**：
- *A. 原地留在 `tools/map_explorer/mock_map.py`*：最小改动但名字/目录继续
  误导 Phase 2 读者。否决。
- *B. 升级到 `synthetic_socio_wind_tunnel.lanecove`（顶层模块）*：对外暴露
  场景包，但和现有按"能力"分层（atlas / ledger / engine / ...）的结构不一致。
  否决。
- *C.（选定）放进 `cartography` 包*：`cartography` 已负责"地图构建"
  （importer / builder / conflation），"特定区域的加载与补齐"是它的自然
  下游。CLAUDE.md 的 `cartography` 描述也说"地图构建（离线）"，匹配。

`_infill_riverview` 是一种合成补齐，和 `conflation.py` 性质同类（生产数据
的最后一块"虚构填空"），从 `cartography` 内协同最合适。

### D2. Demo 留在 `tools/map_explorer/demo_map.py`

`create_atlas()`（虚构新苑里社区）以及 `create_demo_knowledge_maps(atlas)`
里针对该虚构区的部分，分离到 `tools/map_explorer/demo_map.py`。它完全独立
于 Lane Cove，从名字就能区分。`server.py` 若提供 demo view，继续用它。

### D3. 旧路径 shim + DeprecationWarning

`tools/map_explorer/mock_map.py` 保留为一行 shim：

```python
# tools/map_explorer/mock_map.py
"""Deprecated. Use synthetic_socio_wind_tunnel.cartography.lanecove and
tools.map_explorer.demo_map instead."""
import warnings
warnings.warn(
    "tools.map_explorer.mock_map is deprecated; "
    "use synthetic_socio_wind_tunnel.cartography.lanecove "
    "or tools.map_explorer.demo_map",
    DeprecationWarning,
    stacklevel=2,
)
from synthetic_socio_wind_tunnel.cartography.lanecove import *  # noqa
from tools.map_explorer.demo_map import *  # noqa
```

让任何残留 import 继续跑、同时在日志中喊话。一次释放（下一个 release）就删。

### D4. fetch_lanecove v1 删除、v2 去 _v2 后缀

`tools/fetch_lanecove.py`（v1）删除；`tools/fetch_lanecove_v2.py` 重命名为
`tools/fetch_lanecove.py`。所有 `fetch_overture.py` / `Makefile` 的路径
随之更新。v1 里多余的"一体化 overpass"方案已被 v2 的分片式取代；保留 v1
只会误导选型。

### D5. docs 归档 vs 删除

保留 `docs/项目Brief.md` 为 canonical（CLAUDE.md 唯一引用它）。把以下三份
移到 `docs/archive/`（**不是删除**）：
- `docs/项目提案.md`
- `docs/project-proposal.md`
- `docs/project-proposal-EN.md`

理由：历史上 AI 评审 / 改稿生成过多份，每份都有过单独用途；当做学术痕迹
保留有价值。放进 archive 子目录后，`docs/` 主目录从 11 条降到 7 条，可读性
提升；`docs/archive/README.md` 一句话说明它们的来源与废弃原因。

### D6. 公共 API re-export

`synthetic_socio_wind_tunnel/__init__.py` 追加：

```python
from synthetic_socio_wind_tunnel.agent import (
    AgentProfile, AgentRuntime, Planner, DailyPlan, PlanStep,
)
from synthetic_socio_wind_tunnel.map_service import MapService
```

并把这些名字加到 `__all__`。使得：

```python
from synthetic_socio_wind_tunnel import AgentProfile, MapService  # 现在能 work
```

以后 Phase 2 的 orchestrator / memory 等模块引用时从顶层 import，不绕进
`synthetic_socio_wind_tunnel.agent.profile`。

### D7. docs/README.md 作为唯一入口索引

写成扁平目录树 + 一句话说明，分四组：
- **研究背景 / 理论框架** → `项目Brief.md`
- **Agent 系统设计** → `agent_system/01` … `06`
- **地图管线** → `map_pipeline/01`–`03` + `map_service_design.md` +
  `architecture.md`
- **进度报告** → `WIP-progress-report.md`
- **历史归档** → `archive/`

这样 CLAUDE.md / 新同学 / 未来的 AI agent 进入 `docs/` 都能 30 秒定位。

## Risks / Trade-offs

- **[Risk] 旧 import 路径在未纳入测试的脚本中断裂**
  → Mitigation: 保留 `mock_map.py` 一行 shim 打 DeprecationWarning 而不立即删。

- **[Risk] demo_map.py 未来变冷**（虚构新苑里 demo 可能没人在跑）
  → Mitigation: 本 change 不做价值判断；若半年后确认没人用，单独开 change 删。

- **[Risk] `cartography.lanecove` 把"场景特异代码"塞进"能力模块"**
  → Trade-off: Lane Cove 是当前唯一真实参考场景，和 cartography 的依赖也
  最多；如果未来增加另一个场景（例如 Zetland），可再提到
  `synthetic_socio_wind_tunnel.scenarios.lanecove`。届时代码搬家一次即可，
  now is not the time to pre-factor。

- **[Risk] 重命名 fetch_lanecove_v2 打断历史 `git blame`**
  → Mitigation: `git mv` 保留 rename detection；single-commit 迁移。

## Migration Plan

1. 新增 `cartography/lanecove.py`，把函数迁入；`tools/map_explorer/mock_map.py`
   改为 shim；`tools/map_explorer/demo_map.py` 放虚构部分。
2. 更新 `server.py` 与任何引用方 import。
3. `git mv tools/fetch_lanecove_v2.py tools/fetch_lanecove.py` ；删除原 v1。
4. `mkdir docs/archive && git mv 三份过期 proposal → docs/archive/`；写
   `docs/archive/README.md`。
5. 写 `docs/README.md` 索引。
6. 修改 `synthetic_socio_wind_tunnel/__init__.py` re-export + `__all__`。
7. 更新 `openspec/config.yaml` 加一条命名惯例。
8. 全量跑 `python3 -m pytest tests/ -q` 期望：112 passed / 1 skipped。
9. 归档本 change。

**回滚**：每一步都是独立文件操作；git revert 单 commit 即可回退。
shim 与 re-export 都是纯增量，不会移除对外符号。

## Open Questions

1. `mock_simulation.py` 的去留？它是一次性 matplotlib 演示脚本，生成
   `docs/figures/` 下的截图给 presentation 用。本 change 先不动，留给下一次
   清理（可能合并进 `tools/presentation_assets/`）。
2. `tools/map_explorer/static/test_zone.html` 是否废弃？未评估引用路径，
   暂不碰。
