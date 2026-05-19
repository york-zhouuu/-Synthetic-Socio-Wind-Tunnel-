# runtime-observability Specification

## Purpose
TBD - created by archiving change establish-observability-baselines. Update Purpose after archive.
## Requirements
### Requirement: DayRunSummary 必须包含 runtime observability 字段

`DayRunSummary` SHALL 包含以下 6 个 observability 字段（位于
`synthetic_socio_wind_tunnel/orchestrator/multi_day.py`；向后兼容默认值；
旧 snapshot 读取 SHALL 自动 default 不报错）：

- `rss_mb: float = 0.0` — `psutil.Process().memory_info().rss / 1024 / 1024`
  在 day_end hook 时采样
- `vms_mb: float = 0.0` — `psutil.Process().memory_info().vms / 1024 / 1024`
- `memory_store_event_count: int = 0` — Σ `len(store._events)` across
  all agents at day_end
- `dialogue_count: int = 0` — `len(_dialogues) + len(_dialogue_summaries)`
  at day_end
- `gc_collections: tuple[int, int, int] = (0, 0, 0)` — `gc.get_count()`
  三代计数 at day_end
- `tick_latency_ms_p50: float = 0.0` / `tick_latency_ms_p95: float = 0.0`
  / `tick_latency_ms_max: float = 0.0` — per-tick wall-clock 分布
  统计 within the day

字段 SHALL 出现在 `DayRunSummary.model_dump()` 输出；SHALL 出现在
`seed_N.json` 的 per-day-summaries 数组里；SHALL 是 JSON-serializable。

#### Scenario: 新字段出现在 model_dump
- **WHEN** 构造 `DayRunSummary(...)` 含所有新字段（含 default）
- **THEN** `result.model_dump()["rss_mb"]` SHALL 存在；所有 6 字段
  类型符合上述声明

#### Scenario: 旧 JSON 缺失新字段时仍可加载
- **WHEN** 加载一段不含 observability 字段的 legacy JSON（如
  `seed_N.json` from before this change）
- **THEN** `DayRunSummary` SHALL 不 raise；缺失字段 SHALL 取默认
  值（0 / 0.0 / (0,0,0)）

### Requirement: MultiDayRunner 必须在 day_end hook 内部 instrument

`MultiDayRunner._init_day_end_observability_hooks` (新增方法) SHALL
注册一个 `on_day_end` 内置 hook，在该 hook 内：

1. 调用 `psutil.Process().memory_info()` 取 RSS/VMS
2. 调用 `gc.get_count()` 取三代 GC count
3. 调用 `len()` 求和遍历 memory_service 所有 agent's `_events`
4. 调用 `len()` 取 dialogue_service `_dialogues` + `_dialogue_summaries`
5. 从本 day 累积的 tick wall-clock list 算 p50/p95/max（百分位用
   `statistics.quantiles(method="inclusive")`）

任一调用失败 SHALL **不让 run crash**：try/except → log warning →
字段 default 0 / -1 sentinel。

instrumentation 自身 overhead SHALL < 5% of dev smoke wall-clock（Layer 4
budget test 显式验证）。

#### Scenario: 正常 day_end 写完 observability
- **WHEN** dev mode `--agents 100 --num-days 1` 跑完
- **THEN** result.per_day_summaries[0].rss_mb SHALL > 0；
  `memory_store_event_count` SHALL > 0；`tick_latency_ms_p95` SHALL > 0

#### Scenario: psutil 调用失败时 run 不 crash
- **WHEN** mock `psutil.Process().memory_info` raise OSError
- **THEN** day_end hook SHALL 不 propagate；result.per_day_summaries[0]
  .rss_mb SHALL == 0.0（fallback default）；SHALL log warning

#### Scenario: 性能 overhead < 5%
- **WHEN** dev smoke 跑两次：一次 normal，一次显式关 observability
  (env `OBSERVABILITY_DISABLE=1`)
- **THEN** normal wall-clock 与 disabled wall-clock 比值 SHALL <= 1.05

### Requirement: RSS time-series harness

`tools/dump_runtime_observability.py` SHALL 是 CLI，跑 dev smoke 同时
**每 12 tick** sample `psutil.Process().memory_info().rss`，输出
时间序列 JSON：

```bash
python tools/dump_runtime_observability.py \\
    --output tests/fixtures/rss_timeseries_dev_100agent_1day.json \\
    [--seed 42 --agents 100 --sample-every-n-ticks 12]
```

JSON schema：

```json
{
  "metadata": {"scale": "dev", "agents": 100, "num_days": 1,
                "seed": 42, "sample_every_n_ticks": 12, ...},
  "samples": [
    {"tick_global": 0, "rss_mb": <float>, "vms_mb": <float>,
     "elapsed_seconds": <float>},
    ...
  ]
}
```

`samples` SHALL 升序按 tick_global。

#### Scenario: harness 跑通输出合法
- **WHEN** 跑 `--seed 42 --agents 100`
- **THEN** 输出 path 含 samples 长度 >= 24（288 tick / 12 sample-rate
  = 24 sample）

#### Scenario: RSS 时间序列单调或近单调
- **WHEN** 加载 fixture
- **THEN** samples 数列 rss_mb 末值 SHALL >= 初值（dev smoke 内存
  只增长不大幅下降，确认 instrumentation 拿到合理值）；这是 sanity
  check 不是性能 assertion

