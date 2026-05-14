## Why

完成 `fix-systemic-deep-issues` change 后还有 4 项 B/C 类局限标为 disclose / accept；
本 change 把其中"能修"的部分实修，让 thesis 链路（push → 注意力 → 看见 → 偶遇 → 弱关系）
所有关键参数对 sensitivity sweep 透明、对 publishable run 落到 30 seed 时可信。

- **B2 walking_speed** 缺 citation → reviewers 没法判断 80/250 m/min 哪来的。
- **B3 BASE_NOTICING_RATE=0.3** 没有可调通道 → 没法做 sensitivity sweep
  验证"thesis 方向稳健于 ±0.1 噪声"。
- **C3 prefer_driving** 不分 trip distance → 一个 350m 的近距离 trip 也走车速 250 m/min，
  失真。
- **C5 position_trace JSON** 14d × 1000agent × 15seed 估 ~6.6GB → disk 紧张。
- **Aggregator 静默丢 weak_tie_formation_count** → thesis 主要 outcome metric
  在 `aggregate.mean_metrics` 永远是空字典 → B3 sensitivity 没法用聚合数据验证。

## What Changes

- 在 `synthetic_socio_wind_tunnel/agent/population.py` 速度映射段加 B2 calibration citation
  （Austroads 2017 Pedestrian Facility Guideline + NSW BTS Urban Travel Speeds）
- 在 `synthetic_socio_wind_tunnel/attention/noticing.py` `BASE_NOTICING_RATE` 用
  `os.environ.get("SSWT_BASE_NOTICING_RATE", "0.3")` 包裹，文档说明 B3 sensitivity 用法
- 在 `synthetic_socio_wind_tunnel/orchestrator/service.py` `_dispatch_move` 加
  trip-distance override：`prefer_driving and straight_line_m < 500m` 走 80 m/min
- 在 `synthetic_socio_wind_tunnel/metrics/position_trace.py` `write()` 当
  changes > 500K 时同时输出 `.gz` sibling
- 在 `synthetic_socio_wind_tunnel/metrics/aggregator.py` `_extract_scalar_metrics`
  追加 `weak_tie_formation_count` + per-day `tie_count_*_eod`
- `docs/limitations-ethics.md` 更新 B2/B3/C3/C5 状态从 disclose → RESOLVED，
  并加 aggregator 修复说明

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `metrics`: aggregator 必须输出 `weak_tie_formation_count` 和
  `tie_count_total_eod` / `tie_count_weak_eod` / `tie_count_strong_eod`
  到 `SuiteAggregate.mean_metrics`，使其参与 contest comparator 与 B3 sensitivity
  sweep。

## Impact

- 受影响代码：`agent/population.py`、`attention/noticing.py`、
  `orchestrator/service.py`、`metrics/position_trace.py`、`metrics/aggregator.py`
- 受影响测试：`tests/test_metrics_aggregator.py`（增加 weak_tie 字段断言）
- 文档：`docs/limitations-ethics.md`
- **不影响**：trajectory_deviation_m / encounter_stats 等已暴露的 metric
  fields，向后兼容。
- **B3 sensitivity 验证条件**：3 seed × 0.2/0.3/0.4 rate ×（baseline + hyperlocal_push）
  的 `weak_tie_formation_count` 单调随 BASE_NOTICING_RATE 变化（aggregate.mean_metrics
  里现在能看到该字段）。
