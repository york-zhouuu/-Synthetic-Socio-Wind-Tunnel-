# Tasks — tidy-project-layout

## 1. 拆分 mock_map.py — 生产代码迁入 cartography
- [x] 1.1 新建 `synthetic_socio_wind_tunnel/cartography/lanecove.py`
- [x] 1.2 迁入函数：`create_atlas_from_osm`、`_infill_riverview`、
      `create_demo_knowledge_maps`、`create_ledger_with_demo_knowledge`
      以及相关常量（`_DATA_DIR`、`OSM_DATA_PATH`、`ENRICHED_DATA_PATH`、
      `ATLAS_CACHE_PATH`、`PROJ_CENTER_PATH`）
- [x] 1.3 调整 import：从 `synthetic_socio_wind_tunnel.*` 绝对引用，
      不从 `tools.*` 反向引用
- [x] 1.4 `cartography/__init__.py` 导出新加符号

## 2. 抽离虚构 demo 到 tools/map_explorer/demo_map.py
- [x] 2.1 新建 `tools/map_explorer/demo_map.py`
- [x] 2.2 迁入函数：`create_atlas`（新苑里社区 demo）以及 demo 专属的
      `create_demo_knowledge_maps` 区块（若为虚构场景）
      — 若 demo 知识地图同时用于 Lane Cove，两份都保留、分别命名为
      `lanecove` / `xin_yuan_li` 版本

## 3. 保留 mock_map.py 为 shim
- [x] 3.1 `tools/map_explorer/mock_map.py` 改为 ~15 行 shim：
      发 `DeprecationWarning`，`from ... import *` 两份新模块
- [x] 3.2 `tools/map_explorer/server.py` 引用改到新路径
- [x] 3.3 `tools/map_explorer/__init__.py` 若 re-export，跟随更新

## 4. 重命名 fetch_lanecove_v2 → fetch_lanecove；删除 v1
- [x] 4.1 `git rm tools/fetch_lanecove.py`（旧 v1）
- [x] 4.2 `git mv tools/fetch_lanecove_v2.py tools/fetch_lanecove.py`
- [x] 4.3 全仓库 `grep -r "fetch_lanecove_v2"`，修所有引用
      （至少 `fetch_overture.py` 注释 / Makefile / docs/map_pipeline）

## 5. docs 整理
- [x] 5.1 新建 `docs/archive/`
- [x] 5.2 `git mv docs/项目提案.md docs/archive/`
- [x] 5.3 `git mv docs/project-proposal.md docs/archive/`
- [x] 5.4 `git mv docs/project-proposal-EN.md docs/archive/`
- [x] 5.5 写 `docs/archive/README.md` —— 说明三份是 project-proposal 的
      历史版本（中、中新版、英）；canonical 参见 `../项目Brief.md`
- [x] 5.6 写 `docs/README.md`：
      - 研究背景 / 理论框架 → `项目Brief.md`
      - Agent 系统设计 → `agent_system/01` … `06`
      - 地图管线 → `map_pipeline/01-03`、`map_service_design.md`、
        `architecture.md`
      - 进度报告 → `WIP-progress-report.md`
      - 历史归档 → `archive/`
- [x] 5.7 CLAUDE.md 若引用任何过期 proposal 路径，更新为 canonical

## 6. 公共 API re-export
- [x] 6.1 `synthetic_socio_wind_tunnel/__init__.py`：
      追加 `from synthetic_socio_wind_tunnel.agent import
      AgentProfile, AgentRuntime, Planner, DailyPlan, PlanStep`
- [x] 6.2 同文件追加 `from synthetic_socio_wind_tunnel.map_service import MapService`
- [x] 6.3 `__all__` 同步追加六个符号
- [x] 6.4 `tests/test_agent_phase1.py` 里 import 若可简化，顺手简化
      （这条是 stretch，不强求）

## 7. openspec 配置更新
- [x] 7.1 `openspec/config.yaml` 的 `context` 段追加命名惯例：
      - 生产代码路径不得含 `mock_` / `demo_` / `_v2` / `_old`
      - kebab-case 用于 change 名、spec 名、Markdown 文件名
      - snake_case 用于 Python 模块与文件名
      - Lane Cove 特异代码放 `cartography/lanecove.py`

## 8. 验证
- [x] 8.1 `python3 -m pytest tests/ -q` 期望 112 passed / 1 skipped
- [x] 8.2 `python3 -c "from synthetic_socio_wind_tunnel import (Atlas, Ledger,
      SimulationService, PerceptionPipeline, AgentProfile, AgentRuntime,
      Planner, DailyPlan, MapService); print('public API OK')"`
- [x] 8.3 `python3 -c "from synthetic_socio_wind_tunnel.cartography.lanecove
      import create_atlas_from_osm; create_atlas_from_osm()"` 正常返回
      （可复用 `data/lanecove_atlas.json` 缓存，< 2s）
- [x] 8.4 `python3 -c "from tools.map_explorer.mock_map import
      create_atlas_from_osm"` 发出 `DeprecationWarning`
- [x] 8.5 `make enrich-map` 目标若路径变更，验证仍可跑（本地 or dry run）
- [x] 8.6 `tools/map_explorer/server.py` 若对外暴露演示，启动一次确认
      （可选）

## 9. 归档
- [ ] 9.1 本 change 的 spec delta 审阅通过后，执行
      `/opsx:archive tidy-project-layout` 合并进
      `openspec/specs/cartography/spec.md`
- [ ] 9.2 归档后把两个 commit 推上游：
      - "Tighten project layout: cartography.lanecove + docs index + public API"
      - "Archive tidy-project-layout change"
