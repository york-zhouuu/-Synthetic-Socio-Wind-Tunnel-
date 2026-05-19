## Context

2026-05-19 实测火焰图（30s py-spy on PID 30151 publishable single
worker）暴露 `memory.service._event_to_json` 是 100% CPU dominant 热点。
之前所有 hot-path 假设全部被实测推翻——KD-tree encounter 不是、
events_at_tick 不是 dominant、LLM call wait 不是。

mechanism: snapshot every 12 ticks × 24/day × N=数十万累积 events ×
Python-loop per-event = O(N²) over time，每 snapshot 占满 30+ 秒 CPU。

本 change scope：仅优化 `_event_to_json` 单函数。测试方案是第一类公民
（按 testing-philosophy.md）。

## Goals / Non-Goals

**Goals:**
- `_event_to_json` 在 N=10_000 MemoryEvent benchmark 上 SHALL 比 baseline
  快 ≥ 5×
- byte-equivalent output：每个 MemoryEvent 经 fast path 与 baseline 产生
  **同一个** dict（字段顺序也一致，因为下游 json.dumps 字段顺序保留）
- 验证机制：dedicated corpus fixture + round-trip property test + E2E
  differential
- 优化后 py-spy 再采样 `_event_to_json` cumulative % SHALL < 10%

**Non-Goals:**
- 不改 MemoryEvent dataclass 定义
- 不引入 msgspec / orjson / msgpack 依赖
- 不实施 incremental snapshot（留 follow-up）
- 不调 snapshot 频率
- 不动 events_at_tick / dialogue serialize（独立 change）

## Decisions

### 决策 1：选 A (asdict + coerce) vs B (typed dispatch) 由 benchmark 实测

**A**: `dataclasses.asdict(ev)` 利用 CPython 3.11+ asdict 的 C-level
field walk → 拿到原始 dict → 后处理 datetime/tuple 转换。

**B**: 不用 asdict，直接对 MemoryEvent 已知字段名手工 dispatch：
- `embedding` → `list(...)` 或保留 tuple
- `occurred_at` → `.isoformat()`
- 其它 → 直接 attribute access
- 跳过 isinstance 分发的开销

**判读**: 先在 Layer 3 benchmark 上跑两个实现 vs baseline，**3 个值
直接比较**，选实际更快者。预测：B 更快（asdict 还要 deep-copy nested
structures, 多分配）；但 A 改动量更小（10 行 vs 30 行）。Layer 3
benchmark 自动选 winner。

### 决策 2：保留 baseline 作 fallback

新实现叫 `_event_to_json_fast`；保留 `_event_to_json_legacy` 是旧实现。
公共入口 `_event_to_json` 用 env `MEMORY_SNAPSHOT_USE_FAST=1` 切换
（默认 1）。失败时 `=0` 切回旧 path 不损失数据，只损失性能。

意义：
- E2E differential test 可以同一进程对比 fast vs legacy（不用切环境）
- Production 出问题时一行 env 回滚
- 不丢 backward compat

### 决策 3：测试 corpus 含 50 个 hand-written events

每个 MemoryEvent kind 至少 5 个 case，覆盖：
- **kind=conversation**：含 partner_id, message_count, summary string
- **kind=reflection**：含 abstract_id, insights list of strings
- **kind=observation**：含 location_id, observer_count
- **kind=encounter**：含 partner_id, shared_location_id（注意 partner_id
  也在 conversation 出现，要确保两 kind 的 partner_id 字段值都正确序列化）
- **kind=daily_summary**：含 summary text + structured fields
- **kind=life_history**：含 long content (10KB+ text)

边界：
- 空 `embedding=()` vs 非空 `embedding=(0.1, 0.2, ..., 1536 floats)`
- `occurred_at` 在 epoch 边界 (1970-01-01)、远未来 (2099-12-31)、含 tzinfo
- unicode content：中文、emoji、控制字符
- `importance=None` vs `=0.0` vs `=1.0`
- nested dict 字段 (如 `metadata`)

Corpus 进 git 作 fixture：固化"什么算正确"的语义。

### 决策 4：Performance budget 用 hand-built MemoryEvent，不跑 dev smoke

Layer 3 benchmark 直接 `N=10000` × `MemoryEvent(...)` 在 list 中，
然后 timeit/perf_counter measure `to_snapshot_state` 内 listcomp 部分。

理由：
- dev smoke wall-clock 主要被 LLM call wait 主导，不便观察纯 serialize
  时间
- 用 hand-built events 量直接的 CPU work，结果 reproducible
- 比较 fast/baseline ratio 而非绝对时间，吸收机器差异

### 决策 5：5× speedup floor 来源

火焰图显示 `_event_to_json` 占 78%，剩 22% 是 list comprehension overhead
+ store iteration。如果 fast path 让 `_event_to_json` 速度提升 N×，
listcomp 整体 speedup ≈ N / (1 + (N-1) × 0.78) ≈ N / (0.22N + 0.78N) → 
roughly capped 由 listcomp open。N=10 → 整体 ~5×，N=∞ → 整体 ~5×。

设 floor=5× 是务实下限。20× 是 stretch goal。

## Risks / Trade-offs

- **[Risk] dataclass.asdict 不能跨 Python 版本保证 dict order** → CPython
  3.7+ 保证 insertion-order dict，asdict 走 fields() 也保 declaration
  order；测试 corpus byte-equal 是兜底
- **[Risk] tuple → list 转换边界**（line 985 占 78%！）→ 火焰图 78% 落
  在该行是因为 isinstance(v, tuple) 几乎每个 field 都进入这条分支
  （embedding 是 tuple）。优化点在**减少 isinstance 检查**而非 list()
  操作本身
- **[Trade-off] 保留 legacy fallback 多 30 行代码** → 值得，为可逆 +
  E2E differential test 提供 control
- **[Risk] 优化后新热点出现** → Layer 5 py-spy 再次采样必跑；若新热点
  >10% → 记进 follow-up change，不阻塞本 change merge

## Migration Plan

1. Layer 1+2 corpus + round-trip tests **先写**（red）
2. Layer 3 benchmark **先写**（red）
3. Layer 6 fault injection mock test 先写（red）
4. 实现 fast path A 和 B 都写
5. benchmark 选 winner
6. Layer 1-6 tests 转绿
7. 跑 dev smoke E2E 验证 `seed_42.json.memory_store_state` byte-equal
8. py-spy 二次采样 → 验证 `_event_to_json` < 10% cum
9. archive

**Rollback**: `MEMORY_SNAPSHOT_USE_FAST=0` 立刻回滚到 legacy。代码 revert
也直接。

## Open Questions

- A vs B 谁更快？Layer 3 benchmark 给答案，不预设
- N=10000 benchmark 的 floor 5× 合不合理？保守值；如果 benchmark 显示
  其实能到 10×，提升 floor；如果只到 3×，重审"该不该 merge"
- 是否要顺手 cache `_MEMORY_EVENT_FIELD_NAMES` 用 frozenset 加速 isinstance
  → 不，B 方案根本不用 isinstance；A 方案 asdict 内部不查 field name
