# Hot-path 分析（dev-mode 100 agent × 1 day）— 2026-05-19

> 数据源：`tests/fixtures/hot_path_profile_baseline.json`
> 生成命令：`python tools/profile_publishable_smoke.py --output ... --seed 42 --agents 100 --num-days 1 --top-n 30`
> 测量：cProfile（stdlib），wall_clock=9.4s，cProfile overhead ≈ 61.5%（裸跑约 5.8s）

---

## 1. Top-10 meaningful 函数（跳过 entry-point wrapper）

| Rank | qualname | cum sec | cum % | calls | per-call ms |
|---|---|---:|---:|---:|---:|
| 5 | `orchestrator.service:run` | 8.49 | 90.85% | 1 | 8488.0 |
| 6 | `orchestrator.service:_fire` | 7.24 | 77.50% | 578 | 12.5 |
| 7 | `smoke_experiment_demo:on_tick_end` | 7.24 | 77.48% | 288 | 25.1 |
| **8** | **`memory.service:process_tick`** | **7.23** | **77.43%** | 288 | **25.1** |
| **9** | **`memory.service:events_at_tick`** | **4.89** | **52.37%** | **28800** | **0.170** |
| **10** | **`memory.service:<listcomp>`** | **4.73** | **50.66%** | **28800** | **0.164** |
| 11 | `orchestrator.service:_run_tick` | 1.24 | 13.25% | 288 | 4.3 |
| 12 | `memory.service:_is_encounter_noticed` | 0.93 | 9.94% | 97604 | 0.010 |
| 13 | `attention.noticing:noticed_pair` | 0.75 | 8.01% | 97604 | 0.008 |
| 14 | `stdlib:random:__init__` | 0.61 | 6.48% | 97811 | — |

---

## 2. 每条函数的诊断 + 优化评估

### Rank 8: `memory.service:process_tick` (77.43%, 288 calls)

**诊断**：每 tick 一次的 memory 总处理入口。本身可能不重，但调用了 #9 / #10 / #12。**它的高 % 主要是 children 的 cumulative，不是 self time**。

**优化**：`unclear-need-more-data` —— 需要 `--profile-time-mode self` 区分自己 vs children。判读暂搁置，看 #9 #10 #12 优化是否拉低这条。

### Rank 9: `memory.service:events_at_tick` (52.37%, **28800 calls**)

**诊断**：源码 `service.py:325-330`：

```python
def events_at_tick(self, agent_id: str, tick: int) -> list[MemoryEvent]:
    store = self._stores.get(agent_id)
    if store is None:
        return []
    return [e for e in store.all() if e.tick == tick]
```

**每次扫全部 events 过滤 tick**——O(N_events_total) per call，每 tick 每 agent 一次。
- 100 agent × 288 tick = 28800 calls
- 14 day publishable × 1000 agent × 288 tick = **4.03M calls**
- 事件累积随时间增长，单 call 成本递增，**总体 O(time² × agents²)**

**优化**：`yes-high-roi` —— 在 `MemoryStore` 加 `_events_by_tick: dict[int, list[MemoryEvent]]` 索引，append 时同步维护，`events_at_tick` 变 **O(1)**。估计：

| Scale | 当前 | 优化后 | 加速 |
|---|---:|---:|---:|
| 100 × 1 day | 4.9s | <0.1s | ~50× |
| 1000 × 14 day | 不可测但巨大 | 同 O(1) | 几百× |

整 run wall-clock 提速：~3-5× （memory.service 现占 77%，干掉这条 + 关联的 listcomp 直接砍掉 ~50% wall）。

**工作量**：~2 hr 改 store + 改 events_at_tick + 测试 round-trip 等价。

### Rank 10: `memory.service:<listcomp>` (50.66%, 28800 calls)

**诊断**：rank 9 内部的 list comprehension。优化 #9 自动消灭这条。

**优化**：合并到 #9。

### Rank 11: `orchestrator.service:_run_tick` (13.25%, 288 calls)

**诊断**：单 tick 主循环，跑 1000 agents 的 movement + dialogue + commit。

**优化**：`unclear-need-more-data` —— 13% 不是 dominant，但 1000-agent scale 下未必。先看 #9 优化后是否成为新 #1。

### Rank 12-13: `_is_encounter_noticed` + `noticed_pair` (9.94% / 8.01%, 97604 calls)

**诊断**：每对 (agent_a, agent_b, tick) 调一次，检查 attention noticing 算法。

**优化**：`yes-low-roi` —— 97604 calls 但每次 0.01 ms，总成本 0.93s。优化空间小（已经很快）。如果一定要砍：
- cache `noticed_pair` 结果（同 tick 同 pair 多次查时）
- 或 vectorize（numpy bool mask）

**工作量**：~1 day。投入回报比远低于 #9。先做 #9 看整体效果。

### Rank 14: `stdlib:random:__init__` (6.48%, 97811 calls)

**诊断**：每次构造 random.Random instance 引发的初始化。

**优化**：`yes-low-roi` —— 复用 RNG instance 而不是每次新建。但 6.48% 不大。

---

## 3. 结论（这是本 change 的最终交付物）

### 结论 ① — backlog 1.14 KD-tree 假设：**完全推翻**

**1.14 backlog 推测 encounter detection 是 O(N²) 瓶颈**——实际上：

- encounter pair 检测在 `orchestrator/service.py::_detect_encounters` 是
  **location-bucket pair generation**，O(L + Σ visitors²)，非 Euclidean。
- 真正的 spatial nearest-neighbor 查询根本不存在——scipy.spatial.cKDTree
  在本项目用不上。
- profile 显示 encounter-related 函数（`_is_encounter_noticed` /
  `noticed_pair`）合计 **17.95% cum**，**不是** dominant hot path。

**1.14 backlog 1.14 sub-item A（spatial index）SHALL 被标 obsolete。**

### 结论 ② — 真正的 top 候选：`memory.service:events_at_tick` O(N) 全扫

替换 `events_at_tick` 的 list-comprehension scan 为 dict-index lookup。

- 单点改动：~2 hr 工作量
- 影响：整 run wall-clock 估计 3-5× 提速
- 风险：低（MemoryStore round-trip 已有测试，加 index 不改外部 API）
- ROI：极高

**下一个 openspec change 候选**：`index-memory-events-by-tick`。
覆盖 layer 测试方案（类似 accelerate-encounter-detection 的 6 层但更简单——
没有几何模糊性，只有 dict lookup vs list scan 等价性）。

### 结论 ③ — 仍 unclear 的问题（需要后续 profile）

- **dev 100 agent → publishable 1000 agent 的 hot-path 排序是否重排？**
  本 change scope 不揽 1000-agent profile（跑成本 8h）。建议：
  下一个 change 实施 #9 优化前，先跑一次 200-agent × 3-day profile
  作为 mid-scale 验证 fixture（成本 ~30 min）。如果 #9 仍 dominant，
  scale-up 假设成立；如果不是，重新分类。

- **`process_tick` 的 self time vs children time 没区分**。
  cProfile cumulative 包含 children；想知道 process_tick 自己除了调
  events_at_tick 还有什么开销，需要 `--profile-self-time` 模式或 line-profiler。
  建议：下个 change 把 `pyinstrument` 或 line-profiler 加进 dev deps，
  做 self-time 切片。

---

## 4. 给下一个 openspec change 起跑的 input

```
Change name:   index-memory-events-by-tick
Target:        synthetic_socio_wind_tunnel/memory/store.py + service.py
Test scope:    MemoryStore round-trip 等价性 + events_at_tick budget test
Performance:   N=100 dev smoke wall-clock < 7s (current 9.4s); N=1000 publishable
               extrapolated < 8h (current 14h)
红线 (revert triggers):
  R1: MemoryStore.all() 顺序不变
  R2: events_at_tick(t) returns exact same set as scan
  R3: snapshot round-trip 等价
  R4: 既有 1656+ test 不回退
```

---

## 附录：原始 fixture metadata

```json
{
  "scale": "dev",
  "agents": 100,
  "num_days": 1,
  "seed": 42,
  "python_version": "3.11.15",
  "captured_at": "2026-05-19T07:23:13",
  "wall_clock_seconds": 9.4,
  "cprofile_overhead_pct_estimate": 61.5
}
```

cProfile 开销 61.5%（裸跑约 5.8s）—— 下个 change 测真实 speedup
时**关掉** profile 量原始 wall-clock。
