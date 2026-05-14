## Context

`fix-systemic-deep-issues` change archived时把 B2/B3/C3/C5 标为 disclose / accept；
回头看，这几项有"低成本可修"的部分：

1. **B2 citation**：源不需新研究，直接引 Austroads 2017 + NSW BTS。
2. **B3 sensitivity**：env override 是 5 行 patch，让 publishable run 能跑
   ±0.1 sweep 验证方向稳健。
3. **C3 短途 walk override**：避免 250 m/min 跑 350m trip 的失真，已知阈值 500m。
4. **C5 trace gzip**：JSON 文本压缩比 ~10x；500K changes 是 publishable 单 seed 量。

另外做 aggregator 时发现：thesis 主要 outcome 之一 `weak_tie_formation_count`
在 per-seed RunMetrics 里有，但 `aggregator._extract_scalar_metrics` 没拉出来，
所以 SuiteAggregate.mean_metrics 字典里永远没这个 key。这个 bug 让 B3
sensitivity sweep 无法用聚合数据验证（contest comparator 用的 trajectory_deviation_m
和 noticing 完全无关）。

## Goals

- B2/B3/C3/C5 从 disclose/accept 升级为 RESOLVED，docs/limitations-ethics.md 同步
- B3 sensitivity sweep 能在 `aggregate.json` 里直接对比 weak_tie_formation_count
- 不破坏现有 metrics 字段或测试

## Non-Goals

- 不重新校准 walking_speed 数值——B2 只补 citation，数值保持 80/150/250/280
- 不改 BASE_NOTICING_RATE 默认值 0.3——只加 env override 通道
- 不引入新 capability spec——`metrics` 已存在，只 modify

## Decisions

### D1: B3 env override 在模块导入时读取

```python
BASE_NOTICING_RATE = float(_os.environ.get("SSWT_BASE_NOTICING_RATE", "0.3"))
```

- Pro：subprocess 模型下每个 `python3 tools/run_variant_suite.py` 重新 import → env var 生效
- Con：同进程内多次 reload 不会重读，但当前 CLI 一进程一 suite，不影响
- 备选：每次 `noticing_prob` 内部读 env → 慢，无意义

### D2: C3 trip-distance 阈值 = 500m

- Pro：在 _dispatch_move 里算 home→dest straight-line 一次即可；Lane Cove
  中心半径 ~1500m，500m 对应 plaza→cafe 这种确实 walking 更合理的距离
- Con：阈值未做敏感度
- 备选：用 ABS travel survey 校准——B2 同款 disclose，未来再做

### D3: C5 gzip 触发阈值 = 500K changes

- 单 seed 14d × 1000agent，按 estimated 280K rate 推 → 500K 是 1.8x 缓冲带
- 文件名 `.gz` sibling，原 JSON 保留 → 工具向后兼容

### D4: aggregator 暴露 weak_tie_formation_count

加到 `_extract_scalar_metrics` 而非新加方法：保持单一 surface area。
同时加 per-day `tie_count_*_eod`（end-of-day cumulative），让 contest comparator
未来也能用 tie 增长作 primary metric（不在本 change 改 dispatch）。

## Risks / Trade-offs

- **B3 env var 名字 `SSWT_BASE_NOTICING_RATE` 拼写门槛** → mitigation: 文档里
  在 limitations-ethics.md 写命令模板
- **C3 500m 阈值未敏感度** → mitigation: 标 first-order，未来 sensitivity
- **gzip 写入失败时** → 主 JSON 已写入；用户得到 plain JSON + warning
  (没强行 raise，因为 publishable 时主流程不应 fatal)
- **aggregator 新字段未在所有 test 路径里设值** → tests 已 pass；未注入
  social_graph 的 run 字段保持 None，被 `_extract_scalar_metrics` skip 掉

## Migration Plan

代码层 fix 已写入；本 change 主要是把它们规范化到 spec + tasks 留档 + archive。

1. proposal/design/tasks/specs/metrics 更新
2. 跑相关单元测试确认未破坏
3. B3 sensitivity sweep 真实验证 weak_tie 单调
4. 更新 docs/limitations-ethics.md
5. archive change

## Open Questions

- 是否把 weak_tie_formation_count 加入 contest comparator 的 dispatch（让某些
  variant primary_effect_size 用它）？→ 不在本 change 范围；留给后续。
