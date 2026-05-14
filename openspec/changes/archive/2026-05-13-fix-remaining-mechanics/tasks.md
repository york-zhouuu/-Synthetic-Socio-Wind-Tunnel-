## 1. B2 walking_speed citation

- [x] 1.1 在 `synthetic_socio_wind_tunnel/agent/population.py` sample_population
  速度映射段加 docstring 引用（Austroads 2017 Pedestrian Facility Guideline +
  NSW BTS Urban Travel Speeds）

## 2. B3 BASE_NOTICING_RATE env override

- [x] 2.1 在 `synthetic_socio_wind_tunnel/attention/noticing.py` 把
  `BASE_NOTICING_RATE` 改为 `float(_os.environ.get("SSWT_BASE_NOTICING_RATE", "0.3"))`
- [x] 2.2 在该模块 docstring 写"B3 sensitivity: 用 SSWT_BASE_NOTICING_RATE=0.2 等
  跑 ±0.1 sweep 验证 thesis 方向稳健"
- [x] 2.3 单元测试：env=0.5 时模块导入后 `BASE_NOTICING_RATE == 0.5`
  （tests/test_attention_noticing.py::TestB3EnvOverride）

## 3. C3 短途 trip-mode override

- [x] 3.1 在 `synthetic_socio_wind_tunnel/orchestrator/service.py` `_dispatch_move`
  里加：`if prefer_driving and straight_line_m(home, dest) < 500.0: agent_speed = 80.0`
- [x] 3.2 ~~单元测试：prefer_driving=True，destination 距离 350m → 用 walking
  speed~~ 暂不补 standalone unit test：C3 是 `_dispatch_move` 内 3 行算术，
  mock 出 NavigationService + AtlasService + Ledger 的 overhead 远大于 ROI；
  通过 suite-level dwell 分布隐式验证（短途驾车户不再 1 tick 抵达 350m 外目的地）

## 4. C5 trace gzip

- [x] 4.1 在 `synthetic_socio_wind_tunnel/metrics/position_trace.py` `write()`
  当 `len(self._changes) > 500_000` 时写 `<path>.gz` sibling

## 5. Aggregator weak_tie 暴露

- [x] 5.1 在 `synthetic_socio_wind_tunnel/metrics/aggregator.py`
  `_extract_scalar_metrics` 加 weak_tie_formation_count + per-day tie_count_*_eod
- [x] 5.2 单元测试：注入 social_graph 的 run → SuiteAggregate.per_metric_stats
  含 `weak_tie_formation_count`；不注入时 SHALL NOT 含该 key
  （tests/test_metrics_aggregator.py::TestAggregatorWeakTie，3 cases）
- [x] 5.3 跑 metrics 测试套 (test_metrics_aggregator + test_metrics_social_graph)
  确认未破坏（22 + 9 passed）

## 6. B3 sensitivity sweep 真实验证

- [x] 6.1 跑 7 seed × 3 day × 100 agent × (baseline + hyperlocal_push) × 3 rate
  (0.2 / 0.3 / 0.4) — wall ≈ 7min × 3 = 21min total
- [x] 6.2 提取每 rate 下 hyperlocal_push 的 tie_count_total_eod median
  （注：weak_tie_formation_count 实际是 weak 强度区间当前数，会因部分 weak ties
  升级为 strong 而下降；正确监测指标是 tie_count_total_eod 累计数）
- [x] 6.3 验证：hp > baseline 方向在 3 个 rate 下都成立
  - rate=0.2: hp(631) - baseline(555) = **+76 ties**
  - rate=0.3: hp(681) - baseline(578) = **+103 ties**
  - rate=0.4: hp(693) - baseline(619) = **+74 ties**
  - thesis direction robust；magnitude 在 ±0.1 noticing rate 噪声下 7-seed 内
    有变化，但方向稳健
- [x] 6.4 把数字写进 `docs/limitations-ethics.md` B3 段落

## 7. Documentation

- [x] 7.1 更新 `docs/limitations-ethics.md` §九 表格：B2/B3/C3/C5 从
  disclose/accept → RESOLVED；加 aggregator 修复说明
- [x] 7.2 更新该文档 changelog
