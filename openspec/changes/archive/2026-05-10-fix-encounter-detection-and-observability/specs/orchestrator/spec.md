## MODIFIED Requirements

### Requirement: 路径相遇检测（基于 TickMovementTrace + Ledger Snapshot）

Orchestrator SHALL 在 tick 末扫描所有 agent 的位置，产出 `list[EncounterCandidate]`：

- 输入两类来源：
  1. **trace-based**：本 tick 移动过的 agent 的 `TickMovementTrace.locations`
     里的每个 sub-step location（已有路径）
  2. **end-of-tick co-presence**：`Ledger.list_entities()` 快照里**每个**
     entity 的 `current_location`——包括 stationary（WaitIntent / 任何
     non-MoveIntent）的 agent
- 把两类来源按 location 分桶聚合到 `location_visitors: dict[str, set[str]]`
  (set 自动 dedup 同 agent × 同 location 的多次 add)
- 对任意两 agent a < b（字典序），若两人共享至少 1 个 location，emit
  `EncounterCandidate(tick, agent_a, agent_b, shared_locations)`。
- `shared_locations` SHALL 为 `tuple(sorted(intersection))`——固定字典序，
  跨运行一致，支撑 determinism Requirement。
- 扫描 SHALL 用按 location 分桶实现（O(total_trace_length + N) 而非 O(N²)）。
- EncounterCandidate MUST NOT 写入 Ledger；通过 `on_tick_end` 交给订阅者。

**语义升级**（fix-encounter-detection-and-observability，2026-05-10）：原版本只看
trace-based 位置，stationary agent 完全不进检测 → 系统性低估 dwell 期 encounter
（参见 `docs/audit/2026-05-09-bug-hunt.md` B9）。新版本"co-presence at end-of-tick"
口径更贴近"两个人此刻在同一物理位置"的直觉，与 thesis 关注的 encounter density
信号对齐。

#### Scenario: 同一街道段交汇
- **WHEN** agent `alpha` 从 `street_1` 移至 `cafe_a`，经过
  `[street_1, street_2, cafe_a]`；同 tick agent `beta` 从 `park` 移至
  `street_2`，经过 `[park, street_2]`
- **THEN** `EncounterCandidate(agent_a="alpha", agent_b="beta",
  shared_locations=["street_2"])` SHALL 出现在本 tick 的 TickResult

#### Scenario: 仅终点重合不算 trace 交集（trace-based 路径）
- **WHEN** agent `alpha` 与 `beta` 不同 tick 先后到达 cafe_a，且 alpha
  本 tick 已离开 cafe_a
- **THEN** 那些 tick 各自 SHALL NOT 产出 encounter（trace 交集跨 tick
  不成立；end-of-tick 同 location 也不重合）

#### Scenario: MoveIntent 第一步就失败
- **WHEN** agent 的第一个 sub-step 即失败（起点即不可达目标）
- **THEN** 该 agent 本 tick 的 `TickMovementTrace.locations` SHALL 为空元组；
  但其 ledger 中的 `current_location` 仍参与 end-of-tick co-presence 扫描

#### Scenario: stationary agent 同 location 共在
- **WHEN** agent `alpha` 与 `beta` 本 tick 都 issue WaitIntent（无 trace），
  且 ledger 中 `current_location[alpha] == current_location[beta] == "cafe_a"`
- **THEN** EncounterCandidate(agent_a="alpha", agent_b="beta",
  shared_locations=["cafe_a"]) SHALL 出现在本 tick 的 TickResult
  （这是 B9 修复的核心 scenario）

#### Scenario: walking-through 与 stationary 共在
- **WHEN** agent `alpha` 在 `cafe_a` 坐着 dwell（WaitIntent，无 trace），
  agent `beta` 经过 cafe_a 作为路径 sub-step（trace 包含 cafe_a）
- **THEN** EncounterCandidate(agent_a="alpha", agent_b="beta",
  shared_locations=["cafe_a"]) SHALL 出现在本 tick 的 TickResult

#### Scenario: 跨多 tick 持续 dwell
- **WHEN** alpha + beta 在 cafe_a 同时 dwell 12 个 tick，皆无 trace
- **THEN** 12 个 tick 每个 tick SHALL 各自产 1 个 EncounterCandidate
  （per-tick co-presence 计数；不去重；下游 reader 自己决定是否聚合到
  per-day pair count）
