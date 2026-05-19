## Why

2026-05-19 实测真实 publishable single worker（PID 30151, seed42
phone_friction at day 11）RSS 在 **16↔37 GB** sawtooth 震荡。**单 worker
吃满 48GB 物理机器**——并发 N>1 必然 swap thrash。

数据驱动诊断（不再推测）：

| 证据 | 量 |
|---|---|
| snapshot 总 size | 3.34 GB |
| 其中 `memory_store_state` | **99.3%** (3318.9 MB) |
| memory_store 里 `kind=encounter` events | **93.5%** (6.88M events @ day10) |
| vmmap DefaultMallocZone 碎片 | **89%** (6.1GB / 7.4GB) |

`gc.collect()` 救不了碎片（pymalloc arena 滞留，不归还 OS）。
`_event_to_json` 之前 change 已证伪 5× speedup（工作量不可缩减）。

**用户硬性 SLA：单 worker publishable 跑 14 day RSS ≤ 10 GB**。撞顶
graceful_stop 自杀重启（已有机制）。

## What Changes

3 件配合，全部数据驱动：

### ❶ Cold prune encounter events (核心)

仿 `DialogueService.evict_old_dialogues` (harden-worker-resilience 已落地)
pattern：

- `MemoryStore.evict_cold_encounter_events(before_tick: int)` — 新方法
- `MemoryService.evict_cold_encounter_events_across_agents(before_tick)`
  — service-level wrapper
- `MultiDayRunner.on_day_end` 内置 hook 调用：
  `before_tick = max(0, day_index - DEFAULT_ENCOUNTER_GRACE_DAYS) * ticks_per_day`
  默认 `DEFAULT_ENCOUNTER_GRACE_DAYS = 2`
- **只 evict `kind=encounter`**——其它 kind 数量小（life_history 9k /
  action 530k / reflection 等更少），语义关键，不动
- evict 是删除，不保留 summary（与 DialogueService 不同；encounter
  数量太大，summary 还是会爆）

估省：day10 时 encounter 6.88M → ~700k (近 2 day)，memory_store
size ~3.3GB → ~0.3GB。

### ❷ malloc_zone_pressure_relief() 碎片回收

既有 `_init_memory_management_hooks` 已含 `gc.collect()`（backlog
1.7-F）。新增配套：

```python
import ctypes
try:
    libc = ctypes.CDLL("libc.dylib")  # macOS
    libc.malloc_zone_pressure_relief(None, 0)
except (OSError, AttributeError):
    logger.warning("malloc_zone_pressure_relief unavailable on this platform")
```

Linux fallback (TODO follow-up):
`ctypes.CDLL("libc.so.6").malloc_trim(0)`。

在 `gc.collect()` 后立即调。估省：6.1GB 碎片中能 release back to OS
那部分；保守估 2-4 GB。

### ❸ 强制 publishable mode RSS hard cap

- `tools/run_variant_suite.py` 在 `mode=publishable` 时检测 env
  `RSS_RESTART_MB` 是否设置：未设 → 默认 **10000**（10 GB）
- 撞顶时既有 `MultiDayRunner._init_memory_management_hooks` 已经
  触发 graceful_stop（harden-worker-resilience landed），自杀写
  partial → resume_publishable.py 在下次 tick 自动 spawn replacement
- env override 仍允许（`RSS_RESTART_MB=5000` / `=0` 关闭）

## Capabilities

### New Capabilities

- `memory-event-eviction`: cold pruning for `kind=encounter` events
  beyond grace window；保留其它 kind 不动；day_end hook trigger；
  retrieve 兼容性约束（evicted events 不可 retrieve）

### Modified Capabilities

- `run-resilience`: 新增 Requirement — publishable mode 默认
  RSS hard cap = 10 GB（撞顶 graceful_stop 自杀重启）；新增 Requirement —
  `gc.collect()` 后 SHALL 调 `malloc_zone_pressure_relief` (macOS)
  释放 pymalloc 碎片回 OS

## Impact

**代码**：
- `synthetic_socio_wind_tunnel/memory/store.py` — 加
  `evict_cold_encounter_events(before_tick)`
- `synthetic_socio_wind_tunnel/memory/service.py` — 加
  `evict_cold_encounter_events_across_agents(before_tick)`
- `synthetic_socio_wind_tunnel/orchestrator/multi_day.py` — day_end
  hook 触发 evict；`_init_memory_management_hooks` 加
  malloc_zone_pressure_relief
- `tools/run_variant_suite.py` — publishable mode 默认设
  `RSS_RESTART_MB=10000`

**测试** (≥ 6 类, test-first):
- Layer 1: encounter eviction round-trip equivalence (handcrafted
  fixture of events crossing day boundary)
- Layer 2: hypothesis property — long-running simulation bounded growth
- Layer 3: malloc_zone_pressure_relief 调用 + fault injection
- Layer 4: dev smoke RSS measurement (with vs without eviction)
- Layer 5: E2E RSS cap enforcement (low cap → graceful_stop triggered)
- Layer 6: fault injection (ctypes unavailable, empty store, all-evicted)

**Non-goals (explicit)**:

- **不**多核 partition (1000 agent across N processes) — 留独立 change
  `partition-agents-across-processes`，2-3 day 架构改动
- **不**改 MemoryEvent 数据模型（frozen dataclass 保留）
- **不**重写 _event_to_json（之前 change 已证伪 + revert）
- **不** incremental snapshot — 留 follow-up
- **不**改 retrieve API 行为——但语义上 evicted events 不可见
- **不**实施 cold-prune for non-encounter kinds（小数量 + 关键语义）

## Empirical 验收

- 跑 dev smoke 100 agent × 1 day with eviction 启用：RSS final 必
  **lower than** without-eviction baseline
- 跑 dev smoke 100 agent × 5 day with cap=2 GB：撞顶必触发
  graceful_stop（验证 cap 真生效，不是空头）
- 重新跑 publishable single worker (seed42 phone_friction resume)：
  RSS sawtooth ceiling 必 **< 10 GB**

**不设具体 speedup floor**——上次 change 错就错在预设 5×。这次 enforce
**RSS 上限**，speedup 是副产品。
