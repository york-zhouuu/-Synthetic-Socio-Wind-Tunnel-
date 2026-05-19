## Why

2026-05-19 D2 attempt 6 在 publishable run 中触发了一连串相互放大的 worker 故障——
SIGUSR1 误判把 4 个 worker 写成假 `seed_N.json` + 删 partials；ps 在 swap thrash
时超时引发 double-spawn；新 worker 同时反序列化 mid-run snapshot 把 swap 推到
49 GB；最终人工 SIGKILL 才止血。当天紧急修了 3 处（CLAUDE.md 已沉淀
`monitor-as-control-plane` / `sigusr1-graceful-stop-corruption` /
`memory-auto-restart` 三条不变量），但同一根因下还有 5 个相邻的高/中危
失败路径未覆盖；任一项再次触发都会重演当日剧本。这次把它们一并形式化进
spec、堵死回路，让"启动 publishable 后丢电脑出门"成为可信场景。

## What Changes

1. **直接 LLM call asyncio 硬超时**——`memory/reflection.py`、`memory/importance.py`、
   `agent/planner.py::replan`、`data_loader/lanecove.py::_generate_*` 走"模式 B"
   （直接 `await llm_client.generate(...)`），httpx timeout 在 SSL handshake /
   半开连接下失效；统一 wrap `asyncio.wait_for(timeout=60s)` + fallback 路径。
   （backlog 1.9）
2. **snapshot 必须保留 run_metrics**——`SimulationCheckpoint` 加
   `run_metrics_state: dict`；`TickMetricsRecorder` 实现
   `to_snapshot_state()` / `from_snapshot_state()`；resume 后 round-trip
   per_day_summaries / 累积 metric 等价。（backlog 1.11）
3. **snapshot atomic write 多进程安全** **BREAKING（写盘路径）**——
   `state_snapshot.py::write_atomic` 把固定 `path.with_suffix(".tmp")` 换成
   `tempfile.NamedTemporaryFile(dir=path.parent, delete=False)` 或 uuid 后缀，
   多 worker / 双胞胎 spawn 时不再互相覆盖损坏 snapshot。
4. **SIGUSR1 setup-phase 哨兵守护**——`MultiDayRunner._write_partial_at_stop`
   检测 "per_day=[] ∧ WAL 没写过" 时不写任何 partial，但要写一个
   `seed_N.aborted_in_setup.json` 哨兵让 audit / resume_publishable
   清楚区分"setup 期被中断"vs"已跑了几天被中断"。
5. **DialogueService 滚动清理**——`_dialogues: dict` 在 day_end hook 里
   evict ≥ 2 simulated-day 前结束的 dialogue（保留 dialogue_id 引用 + 摘要、
   丢 message detail），消除每 14-day worker 100–500 MB 永久泄漏，
   保证 backlog 1.7 B 方案（RSS 自重启）实际生效。

## Capabilities

### New Capabilities

（无——所有改动都是对既有能力的硬化。）

### Modified Capabilities

- `run-resilience`: 新增 "所有直接 LLM call 必须 asyncio.wait_for 兜底"
  要求；新增 "snapshot atomic write 必须多进程安全" 要求；新增
  "SIGUSR1 在 setup-phase 行为定义"（不写假 partial、写
  `.aborted_in_setup.json` 哨兵）；新增 "DialogueService 必须有
  rolling cleanup" 要求。
- `tick-level-resume`: 新增 "snapshot 必须包含 run_metrics_state" 要求；
  新增 "resume 后 round-trip 等价性必须覆盖 per_day_summaries / 累积
  metric" 要求。

## Impact

**代码**：
- `synthetic_socio_wind_tunnel/run_resilience/state_snapshot.py`（atomic write）
- `synthetic_socio_wind_tunnel/run_resilience/checkpoint.py`（partial 也用相同 tmp 模式）
- `synthetic_socio_wind_tunnel/orchestrator/multi_day.py`（SIGUSR1 setup 哨兵、metrics snapshot round-trip）
- `synthetic_socio_wind_tunnel/memory/reflection.py` / `importance.py`（wait_for wrap）
- `synthetic_socio_wind_tunnel/agent/planner.py`（replan wait_for）
- `synthetic_socio_wind_tunnel/data_loader/lanecove.py`（_generate_* wait_for）
- `synthetic_socio_wind_tunnel/conversation/dialogue_service.py`（rolling evict）
- `synthetic_socio_wind_tunnel/metrics/tick_recorder.py`（to/from snapshot state）
- `tools/resume_publishable.py` + `tools/audit_run_health.py`（识别
  `.aborted_in_setup.json` 哨兵）

**测试**：
- 多进程并发写同一 snapshot path 不损坏
- SIGUSR1 在 setup-phase 触发时写哨兵而非污染 partial
- snapshot round-trip 等价性扩展到 run_metrics
- DialogueService evict 后 retrieve 仍能拿回 dialogue_id（保留摘要）
- LLM call timeout fallback 路径有覆盖

**Non-goals**（明确不做）：
- 不重新设计 SIGUSR1 协议本身；仍是 "set flag, exit after current tick"
- 不引入新 capability（如 `run-monitor` / `resource-budget`），所有改动
  归入既有 `run-resilience` + `tick-level-resume`
- 不处理 backlog 1.7 的其它 sub-item（A mmap / C cold prune / D fork / E slots）
- 不修 `tools/run_variant_suite.py` 的 SIGUSR1 graceful_stop 写假 final——
  已于 2026-05-19 修完，本 change 只把它形式化进 spec 验证
- 不动 `monitor-as-control-plane` 在 watchdog / resume_publishable 的实现——
  已于 2026-05-19 落地，本 change 只把它入 spec
