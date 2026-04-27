## Why

`docs/agent_system/20-realism-roadmap.md` 把"agent 拟真"拆成 6 个 fidelity
维度。三个维度构成**baseline 真实感地基**——少一个 sim 就一眼假：

- **F1 时空真实**：rush hour 双峰 / 周末区分 / POI 时段热度
- **F2 个体差异**：现 19 维 calibrated profile，scripted_plan **只读 2 维**（`work_mode` + `home_location`），其它 17 维白做
- **F3 routine 锚定**：`build_scripted_plan(profile, ..., date, rng)` 每天传新
  rng，**agent 没"自己的"routine**，14 天像随机游走

三者**互相 entangled**——分开做等于改 3 次 `scripted_plan.py`。本 change
合一次解决，作为 realism roadmap Stage 1。

**Chain-Position**: `infrastructure`（不动 thesis 主链 / Planner / Atlas
公共契约；只动 scripted_plan + 加 LifePattern）

**前置**：`agent-profile-enrich`（已 archive，提供 13 维身份字段）

## What Changes

### 1. `AgentProfile` 加 `LifePattern` 字段（新模型）

每个 agent **采样一次**就锁定的"我的"routine 锚：

```python
class LifePattern(BaseModel):
    preferred_cafe: str | None              # 偏好咖啡馆 location_id
    preferred_leisure_park: str | None      # 偏好绿地
    preferred_errand_destination: str | None # 偏好杂货 / 药店
    morning_commute_minute: int             # 7-9am window 内的 offset
    evening_return_minute: int              # 17-19pm window 内的 offset
    weekend_outing_destination: str | None  # 周末固定出游地

class AgentProfile(BaseModel):
    ...
    life_pattern: LifePattern | None = None  # Optional, 向后兼容
```

`sample_population` 时为每个 agent 生成 LifePattern；`personality.routine_adherence`
控制后续 plan 生成时多大概率用 LifePattern 偏好（高坚持 → 锚紧 / 低坚持 → 多探索）。

### 2. `scripted_plan` 重构 — 三维同步升级

**F1 时空真实**：
- 加 `weekday/weekend` 分支：`date.weekday() < 5` 走当前 commute/remote/shift/
  nonworking 4 模式；周末走新的 `_weekend_day_shape`（无通勤；errand + leisure
  + family time 主导）
- ABS Travel Survey 时间分布锚（暂用 prior，未下载 ABS 时 fallback）：
  morning departure 6:30-9:30 doubly stochastic（高斯叠加均匀），不是均匀
  采样
- Popular Times 加权 destination 采样（`data/calibration/lanecove_popular_times.json`
  存在时启用，否则 fallback uniform）

**F2 个体差异**：scripted_plan 读 8 个新维度做 conditioning：
| 字段 | 影响 |
|---|---|
| `family_composition == couple_kids_under_15` | 加 3pm school pickup step + 18:30 home anchor |
| `unpaid_child_care_hours == "30plus"` | errand 时段集中 9-15pm，避开 commute |
| `vehicles_at_dwelling == "0"` | commute step 加 train station as via-point |
| `community_tenure_5yr == "new_<1yr"` | leisure POI diversity ↑（探索期）|
| `community_tenure_5yr == "established_5plus"` | LifePattern 锁定强 |
| `english_proficiency == "not_well"` | 偏好 own-language community POI（mild）|
| `personality.routine_adherence > 0.7` | 用 LifePattern.preferred_* 100% |
| `personality.openness > 0.7` | leisure venue 多样化 |

**F3 routine 锚定**：
- `build_scripted_plan` 接收 `life_pattern: LifePattern` 参数（若 `agent.profile.life_pattern`
  非 None 则自动用）
- 高 routine_adherence agent 14 天内 cafe / leisure / weekend 目的地保持一致
- 低 routine_adherence agent 偶尔偏离 LifePattern 探索

### 3. `tools/measure_group_alignment.py`（新 CLI）

为 verification 服务——跑完 sim 后 dump 拟真度数字：

```bash
python3 tools/measure_group_alignment.py --suite-dir <suite>
# 输出：
# - per-hour encounter time series（rush hour 存在性）
# - weekday/weekend total ratio
# - per-agent venue repeat 率（LifePattern 锚效果）
# - Popular Times EMD（待数据；先 fallback "no data"）
```

输出 `data/realism/baseline_metrics.json`，给后续 stage 当 anchor。

### 4. 测试

- `tests/test_life_pattern.py`：
  - LifePattern 同 seed reproducibility
  - sample_population 给每个 agent 生成 LifePattern
  - High routine_adherence → repeat venue（>60% 同 cafe）
  - Low routine_adherence → diverse（<30% 同 cafe）
- `tests/test_scripted_plan.py` 扩展：
  - weekday/weekend 不同 day-shape
  - 8 个 profile 维度 conditioning（每维至少 1 case）
  - `family_composition == couple_kids_under_15` 含 school pickup step
  - `vehicles_at_dwelling == "0"` 含 transit via-point
  - 时间分布不再是均匀（rush hour 分位数特征）
- `tests/test_realism_emergence.py`（新建）：
  - 跑 100 agent × 7 day baseline
  - assert hourly encounter 有 morning peak（7-9am ≥ 1.5× 12-13pm）
  - assert weekday total > weekend total × 1.15
  - assert ≥ 30% high-adherence agents 14 天 cafe 重复率 > 60%

## Non-goals

- **不**改 `Planner`（LLM 路径）—— 这是 990 个 Haiku 档 agent 的 scripted 路径优化
- **不**做 perception grounding（Stage 2 范畴）
- **不**做 attention 个体化（Stage 3 范畴）
- **不**做 household coupling（Stage 4 范畴）
- **不**做 POI capacity（Stage 5 范畴）
- **不**做 ABS Travel Survey 实际下载（用 prior + 数据到了再补）
- **不**强制 Popular Times 抓取——graceful fallback 让 sim 还能跑
- **不**改 `Atlas` / `AgentRuntime` / `Orchestrator` 公共 API

## Capabilities

### Modified Capabilities

- `agent`: AgentProfile 加 LifePattern 字段；scripted_plan 行为契约扩展
  （从 4 day-shape → 8 个维度 conditioning + per-agent 锚 + weekday/weekend）

### New Capabilities

（无）

## Impact

- **修改文件**：
  - `synthetic_socio_wind_tunnel/agent/profile.py`（+ LifePattern model + AgentProfile field）
  - `synthetic_socio_wind_tunnel/agent/population.py`（sample_population 生成 LifePattern）
  - `synthetic_socio_wind_tunnel/agent/scripted_plan.py`（核心重构）
- **新增文件**：
  - `tools/measure_group_alignment.py`
  - `tests/test_life_pattern.py`
  - `tests/test_realism_emergence.py`
- **不改**：Planner / AgentRuntime / Orchestrator / Atlas / cartography 公共契约
- **预计周期**：5-7 day
- **下游影响**：
  - 解锁 Stage 2-5（依赖 baseline 有 routine + rush hour）
  - 真 LLM publishable run 应该看到更强 hp/gd 信号（baseline 不再是噪声）
  - 案例页面立刻视觉变化（rush hour 时间序列 + per-agent 14d 轨迹）
- **回滚**：删 LifePattern + git revert scripted_plan + agent.life_pattern 自动 None
- **Realism roadmap 进度**：Stage 1/5 ✓
