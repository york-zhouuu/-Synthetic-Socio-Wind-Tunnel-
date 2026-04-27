# Tasks — agent-calibration

实施 `validation-strategy` Part IV/V 的 population + behavioral calibration；
解 publishable checklist #1 与 fitness-audit `phase1-baseline.profile-preset-
ground-truthed`。

**Chain-Position**: `infrastructure`
**前置**: 无（独立 fix）
**预计周期**: 1-2 周

## 1. 数据获取（阶段 1，3-4 day）

### 1.1 ABS Census Lane Cove SA2 静态快照
- [x] 1.1.1 手工从 ABS 网站下载 Lane Cove SA2 6 维表（age / gender /
  housing_tenure / income / ancestry / employment）—— GCP DataPack SA2 NSW
- [x] 1.1.2 写一次性转换 helper `tools/convert_abs_census.py`（合并 G09/G17
  split files；ship 在仓库供复跑）
- [x] 1.1.3 输出 `data/calibration/abs_census_lanecove_2021.json`，含
  source URL + downloaded ISO date + 6 维 normalized 分布

### 1.2 ABS Travel Survey 2021 (Sydney) OD 矩阵
- [ ] 1.2.1 手工从 BTS NSW Household Travel Survey 下载 SA2 → SA2 OD +
  departure-time 分布
- [ ] 1.2.2 转 JSON `data/calibration/abs_travel_survey_sydney_2021.json`
- [ ] 1.2.3 记录映射：sim 内 destination → ABS SA2 的近似规则（大概率
  Lane Cove 内部 destination 全部映射到一个 "Lane Cove" SA2）

### 1.3 Popular Times Outscraper 抓取
- [x] 1.3.1 实现 `tools/fetch_popular_times.py`：
  - 读 atlas top-20 POI 名字（按 name + category 过滤；优先 cafe / library /
    park / community_centre）
  - Outscraper Google Maps API：`POST /maps/search-v3` + place_id 解析
    populartimes
  - 必须 `OUTSCRAPER_API_KEY` env；缺则 sys.exit(2) 友好诊断
  - 输出 `data/calibration/lanecove_popular_times.json`
- [ ] 1.3.2 跑一次实际抓取（提交 JSON 到 git）**[blocked: needs API key]**
- [x] 1.3.3 在 `docs/calibration/01-data-sources.md` 记录 Outscraper free
  tier policy + 重抓步骤

### 1.4 Documentation
- [x] 1.4.1 新建 `docs/calibration/01-data-sources.md`：
  - 三份数据源 URL + 下载日期 + 字段映射规则
  - ABS 桶到 sim 桶的对齐表
  - 重抓步骤（环境 var、CLI、预期 JSON 大小）

## 2. 计算层（阶段 2，2-3 day）

### 2.1 calibration 模块
- [x] 2.1.1 新建 `synthetic_socio_wind_tunnel/agent/calibration.py`：
  - `compute_population_distance(samples: list[AgentProfile], abs_data: dict)
    -> dict[str, float]` —— 6 维 chi²/KS p 值
  - `assess_population_calibration(p_values: dict, *, strict_threshold=0.10,
    best_effort_min_dims=4) -> CalibrationStatus`
  - `compute_od_chi_squared(sim_OD: ndarray, abs_OD: ndarray) -> float`
  - `compute_popular_times_emd(sim_visits: dict, popular_times: dict)
    -> dict[str, float]` —— per-POI EMD
  - `assess_behavioral_calibration(...) -> CalibrationStatus`
  - `CalibrationStatus`：Pydantic model `{passed: bool, acceptance_level:
    Literal["strict", "best-effort", "failing"], details: dict}`

### 2.2 单元测试
- [x] 2.2.1 `tests/test_calibration.py`：
  - chi²/KS/EMD 对手造数据数值正确
  - assess_*_calibration 在边界条件（strict / best-effort / failing 切换）
    正确
  - 6 维 → 5 维 → 4 维 → 3 维 时 acceptance_level 正确递降

### 2.3 添加 scipy 依赖
- [x] 2.3.1 `pyproject.toml` 加 `scipy>=1.10` 到 main deps（不是 dev）

## 3. 人口校准（阶段 3，2-3 day）

### 3.1 跑当前 LANE_COVE_PROFILE 的 baseline
- [x] 3.1.1 写 `tools/run_calibration.py --mode population` 跑一次：
  采样 1000 agent → 算 6 维 p 值 → log
- [x] 3.1.2 记录初始 baseline：1/6 (gender pass)；其余 5 维因桶定义不对齐
  全 fail

### 3.2 迭代 LANE_COVE_PROFILE 数值
- [x] 3.2.1 根据 chi² 方向手调 `LANE_COVE_PROFILE`（age 桶从 3 个换成
  ABS 11 桶；ethnicity 从合成键换成 country-of-birth；housing/income/
  work_mode 数值复制 ABS）
- [x] 3.2.2 重跑 → 看变化（5/6 通过）
- [x] 3.2.3 重复直到 ≥ 4/6 维度 p > 0.10：**5/6 best-effort 达成**
- [x] 3.2.4 commit 每次调整时记录调了哪几维 + 影响（commit pending；改动
  在 LANE_COVE_PROFILE + calibration._age_bucket）

## 4. 行为校准（阶段 4，3-4 day）

### 4.1 scripted_plan 三模式重构
- [x] 4.1.1 新建 `synthetic_socio_wind_tunnel/agent/scripted_plan.py`，
  从 `tools/smoke_experiment_demo.py:74` 提取 `build_scripted_plan` 作起点
- [x] 4.1.2 实现 `_commute_day` / `_remote_day` / `_shift_day` /
  `_flexible_day` 四个 day-shape，每个内部有 commute / errand / leisure
  step 类型
- [ ] 4.1.3 时间锚点用 ABS Travel Survey departure-time 分布
  **[partial: placeholder peaks shipped; replace once ABS JSON arrives]**
- [ ] 4.1.4 errand / leisure 目的地按 Popular Times hourly 热度加权采样
  **[partial: uniform now; seam at `_pick_destination`]**
- [x] 4.1.5 公共 API `build_scripted_plan(profile, destinations, date, rng)`
  签名保持
- [x] 4.1.6 加入 `synthetic_socio_wind_tunnel/agent/__init__.py` re-export
- [x] 4.1.7 删除 `tools/smoke_experiment_demo.py:74-114` 的 build_scripted_plan
- [x] 4.1.8 修改 4 个 tools import 路径：
  `tools/smoke_experiment_demo.py`、`tools/run_multi_day_experiment.py`、
  `tools/run_variant_suite.py`、`tools/replan_trace.py`

### 4.2 scripted_plan 测试
- [x] 4.2.1 `tests/test_scripted_plan.py`：
  - 4 类 work_mode 各跑一次，验证 day-shape 大致吻合
  - commute mode 含 home → workplace + return
  - not_working mode 不含 commute
  - 时间分布大致 match ABS departure-time

### 4.3 跑 baseline sim + 行为指标
- [ ] 4.3.1 `tools/run_calibration.py --mode behavioral` 跑 baseline
  14d × 1000 agent **[blocked: needs ABS Travel Survey + Popular Times data]**
- [ ] 4.3.2 收集 OD 矩阵（agent first commute step 起点 → destination 计数）
  **[blocked]**
- [ ] 4.3.3 收集 hourly visit count per POI **[blocked]**
- [ ] 4.3.4 计算 OD chi² + Popular Times EMD **[blocked]**

### 4.4 迭代 scripted_plan 参数
- [ ] 4.4.1 调三类比例（按 work_mode 给 commute / errand / leisure 概率）
  **[blocked]**
- [ ] 4.4.2 调 errand 时段权重（Popular Times 热度高的时段更多 errand）
  **[blocked]**
- [ ] 4.4.3 重跑 → 看 OD/EMD 改善 **[blocked]**
- [ ] 4.4.4 直到 OD p > 0.05 且 ≥ 70% POI EMD < 0.25 **[blocked]**

## 5. CLI + 集成（阶段 5，1 day）

### 5.1 完成 `tools/run_calibration.py`
- [x] 5.1.1 `--mode population` / `--mode behavioral` / `--mode all`
- [x] 5.1.2 输出 `data/calibration/calibration_report.json`，含
  `population` + `behavioral` 两段，每段含 acceptance_level + details
- [x] 5.1.3 `--seed` 参数（默认 42）保证重现性

### 5.2 publishable suite report 接入
- [ ] 5.2.1 改 `tools/run_variant_suite.py` 的 report writer：检查
  `data/calibration/calibration_report.json` 是否存在
- [ ] 5.2.2 若存在：把 calibration 状态写入 report.md 的 checklist #1 +
  专门 section（disclose 未通过维度）
- [ ] 5.2.3 若不存在：fallback 写 ✗（calibration not run）

## 6. 验证（阶段 6，0.5 day）

- [ ] 6.1 全 pytest 通过（558+ tests + 新增 ~20 个）
- [ ] 6.2 `tools/run_calibration.py --mode all` 一次性跑通
- [ ] 6.3 `python3 tools/run_variant_suite.py --variants baseline,hyperlocal_push
  --mode publishable` 端到端：report.md 含 calibration section + checklist #1 ✓
- [ ] 6.4 `openspec validate agent-calibration --strict` 通过
- [ ] 6.5 fitness-audit 重跑 →
  `phase1-baseline.profile-preset-ground-truthed` PASS

## 7. 文档

- [ ] 7.1 更新 `docs/agent_system/19-system-snapshot.md`：
  - 历史决策点表加本 change
  - "仍开口的 Gap" / "Pre-publication Checklist" 状态更新（#1 ✗ → ✓）
- [ ] 7.2 更新 `docs/agent_system/18-validation-strategy.md`：
  - Part IV/V 标记"Implemented in 2026-04-26 agent-calibration"
- [ ] 7.3 `docs/calibration/01-data-sources.md` 完整化（数据源 / 重抓步骤 /
  调参经验）
- [ ] 7.4 给 README 加一段："How calibration works"（30 行；指向 docs/）

## 8. archive sync

- [ ] 8.1 archive 时把 delta specs 合入 `openspec/specs/agent/spec.md` +
  `openspec/specs/validation-strategy/spec.md`
- [ ] 8.2 commit 全部 calibration 数据 + 代码
