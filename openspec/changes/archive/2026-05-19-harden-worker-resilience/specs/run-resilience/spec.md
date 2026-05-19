## ADDED Requirements

### Requirement: 直接 LLM call 必须 asyncio.wait_for 兜底

项目里所有 LLM call SHALL 走 OperationPool 路径（模式 A，已被
`asyncio.wait_for(handler, timeout=120s)` 包裹）；如果某条调用路径**不能**
走 OperationPool（如 setup 期一次性 LLM call、reflection 内部短路），它
SHALL 自己用 `asyncio.wait_for(llm_client.generate(...), timeout=60s)`
包裹，且 SHALL 有 fallback 路径在 `asyncio.TimeoutError` 时返回安全默认值
（不允许传播为 worker crash）。

适用对象（已知模式 B 调用点）：
- `synthetic_socio_wind_tunnel/memory/reflection.py::reflect`
- `synthetic_socio_wind_tunnel/memory/importance.py::score_importance`
- `synthetic_socio_wind_tunnel/agent/planner.py::Planner.replan`
- `synthetic_socio_wind_tunnel/data_loader/lanecove.py::_generate_life_history_for_one`
- `synthetic_socio_wind_tunnel/data_loader/lanecove.py::_generate_identity_text_for_one`

每个调用点 SHALL 在超时时 log warning 含 `agent_id` / `call_site` /
`elapsed_s`；调用方 SHALL 看到一个语义合理的 fallback 而非异常。

#### Scenario: reflect 超时回退
- **WHEN** mock llm_client.generate 在 `reflect()` 内部 sleep 90s，
  `asyncio.wait_for` timeout 设 60s
- **THEN** `reflect(...)` SHALL 在 60±2s 内返回；返回值 SHALL 是空
  reflection 或 fallback 摘要；SHALL NOT 抛 TimeoutError 给调用方

#### Scenario: importance 超时回退
- **WHEN** mock llm_client.generate 在 `score_importance()` 内部 hang 70s
- **THEN** `score_importance(...)` SHALL 在 60±2s 内返回默认 importance
  分（如 0.5），并 log warning

#### Scenario: lanecove setup 期超时
- **WHEN** `_generate_life_history_for_one` 在 setup_cache MISS 路径，
  mock llm_client.generate hang 80s
- **THEN** SHALL 在 60±2s 内返回 fallback life_history（如空 list 或
  pre-canned generic 模板）；SHALL 不阻塞同批 1000 agent 中的其它 agent

### Requirement: SIGUSR1 在 setup-phase 写哨兵不污染 partial

`MultiDayRunner._write_partial_at_stop()` SHALL 检测 "per_day 为空 ∧ WAL
没写过任何 entry" 这个 setup-phase 状态。在该状态下收到 SIGUSR1
graceful_stop 时：

- SHALL NOT 写任何 `seed_N_day*.partial.json`
- SHALL NOT 修改既有 partial 文件
- SHALL 在 output_dir 下写一个哨兵文件
  `seed_N.aborted_in_setup.json`，包含 `{"seed": N, "aborted_at":
  "<iso datetime>", "reason": "SIGUSR1 received during setup phase",
  "wal_writes": 0, "completed_days": 0}`
- SHALL 让 `result.metadata["graceful_stop"]` == True、
  `result.metadata["aborted_in_setup"]` == True

外部 audit / `tools/resume_publishable.py` SHALL 识别该哨兵文件作为
"该 cell 还没真正启动过，可安全 resume from latest snapshot or fresh"
信号；不应误判为 INTERRUPTED-with-progress。

#### Scenario: setup-phase SIGUSR1 写哨兵
- **WHEN** worker 启动后 5s（还在 setup_cache load、未进入 tick 循环），
  外部发 SIGUSR1
- **THEN** 进程 SHALL 退出码 0；output_dir 下 SHALL 出现
  `seed_<N>.aborted_in_setup.json`；SHALL NOT 出现 `seed_<N>_day*.partial.json`；
  result.metadata SHALL 含 `aborted_in_setup=True`

#### Scenario: 跑了 3 天后 SIGUSR1 不写哨兵
- **WHEN** worker 跑完 day 0-2 写过 3 个 partial 后收到 SIGUSR1
- **THEN** SHALL 走既有 graceful_stop 路径写 `day3.partial.json`（当天进度）；
  SHALL NOT 写 `aborted_in_setup.json`；`result.metadata["aborted_in_setup"]`
  SHALL == False

### Requirement: DialogueService 必须有 rolling cleanup

`DialogueService` SHALL 在每次 `on_day_end` hook（或等价的 day 边界）
evict 满足以下条件的 dialogue（位于
`synthetic_socio_wind_tunnel/conversation/dialogue_service.py`）：

- `dialogue.ended_at_day_index < current_day_index - 2`（**结束于 2 模拟天前**）
- AND `dialogue.status` ∈ {`completed`, `aborted`}（不动 in-progress）

evict 操作 SHALL：
- 保留 `dialogue_id`、`participants`、`ended_at_day_index`、`message_count` 摘要
  到 `_dialogue_summaries: dict[str, DialogueSummary]`
- 释放 `Dialogue.messages: list[DialogueMessage]`、长 prompt 上下文等 detail
- 通过 `to_snapshot_state` 序列化时只序列化 summaries，不带 full messages

`DialogueService` SHALL 暴露 `retrieve_summary(dialogue_id) -> DialogueSummary
| None` 给下游 metric / narrative 用；下游若需 full messages SHALL 改为
通过外部 DialogueArchive 持久化路径（backlog 1.12，暂不实施）。

#### Scenario: day 边界 evict 老对话
- **WHEN** 在 day 5 触发 day_end hook，`_dialogues` 含 4 个 dialogue
  分别结束于 day 1 / day 2 / day 3 / day 4
- **THEN** 结束于 day 1 / day 2 的 dialogue SHALL 被 evict 到
  `_dialogue_summaries`；结束于 day 3 / day 4 的 dialogue SHALL 留在
  `_dialogues`；`retrieve_summary` SHALL 对所有 4 个返回非 None

#### Scenario: in-progress dialogue 不被 evict
- **WHEN** day 10 时 `_dialogues` 里有一个开始于 day 1、status 仍是
  `in_progress` 的 dialogue（异常长对话）
- **THEN** day_end hook SHALL NOT evict 它；它的 messages SHALL 仍可访问

### Requirement: 守护脚本不持有 termination 决策权

所有 daemon / watchdog / LaunchAgent / cron / 自动化运维脚本 SHALL NOT
主动发 SIGUSR1 / SIGTERM / SIGKILL / `launchctl bootout` 任何已存活
进程，**除非**有 explicit `--allow-terminate` flag 且其值是
user-supplied。适用对象包括但不限于 `tools/resume_publishable.py`、
`tools/watchdog_wal_deadlock.py`、`tools/audit_run_health.py`。

允许的 constructive 行为：
- spawn missing workers（idempotent，仅当 PID 不存在时）
- 写 structured event log 给 monitor
- 重启 crashed 服务（系统级 supervisor）

禁止的 termination 行为：
- 自动 SIGUSR1 任何进程
- 自动 SIGKILL 任何进程
- 自动删除 cell 数据
- 自动 unload LaunchAgent / disable cron

human via monitor SHALL 是 termination 唯一决策方。

#### Scenario: resume_publishable 看到 RUNNING_STALE 不发 SIGUSR1
- **WHEN** `tools/resume_publishable.py` 巡检发现某 cell 处于
  RUNNING_STALE 状态（pid 存活 + wal_age > stale_secs）
- **THEN** SHALL 在 log 写 warning 含完整诊断信息；SHALL NOT 调
  `os.kill(pid, signal.SIGUSR1)`；entry["action"] SHALL == "report_only"

#### Scenario: spawn-on-missing 仍然允许
- **WHEN** `tools/resume_publishable.py` 巡检发现某 cell 处于
  INTERRUPTED 状态（pid is None + 有 snapshot）
- **THEN** SHALL spawn 一个 fresh resume worker（constructive recovery，
  不违反不变量）；entry["action"] SHALL == "spawn_resume"

### Requirement: graceful_stop 不写假 seed_N.json 不删 partials

`tools/run_variant_suite.py` 在 per-seed 主循环里 SHALL 检查
`result.metadata.get("graceful_stop", False)`：

- 若 True：SHALL NOT 写 `seed_N.json`、SHALL NOT 写
  `seed_N_positions.json`、SHALL NOT 调用
  `DayCheckpointWriter.cleanup_partials`；SHALL 只 print 一行汇报
  "GRACEFUL_STOP after K day(s) — seed_N.json NOT written, partials
  preserved for resume"；SHALL NOT append `run_metrics` 到 aggregate
- 若 False（正常完成）：SHALL 走原路径——写 seed_N.json + 写
  positions + cleanup_partials + append run_metrics

audit 工具 SHALL 把 "graceful_stop 后没有 seed_N.json 但有
day_*.partial.json" 识别为 INTERRUPTED（可 resume）而非 DONE。

#### Scenario: graceful_stop=True 时跳过所有写
- **WHEN** worker 跑完 day 0-9 后收到 SIGUSR1，`result.metadata.graceful_stop`
  == True
- **THEN** `seed_N.json` SHALL NOT 存在；`seed_N_positions.json` SHALL NOT
  存在；`seed_N_day0..9.partial.json` SHALL 完整保留；aggregate.json 中
  对该 seed 的贡献 SHALL 为空（不在 runs list）

#### Scenario: graceful_stop=False 时正常写
- **WHEN** worker 跑完 day 0-13，`result.metadata.graceful_stop` == False
- **THEN** `seed_N.json` SHALL 存在并含完整 14 day result；`day_*.partial.json`
  SHALL 被 `cleanup_partials` 清除（final 是 source of truth）

### Requirement: worker 必须有 RSS 阈值自重启机制

`MultiDayRunner` SHALL 在 `run_multi_day` 注册一个 on_tick_end hook
（`_init_memory_management_hooks`），在 hook 里：

- 当环境变量 `RSS_RESTART_MB > 0` 时，每
  `RSS_CHECK_EVERY_N_TICKS`（默认 50）tick 量一次 self RSS（用
  `resource.getrusage` 或等价跨平台 API）
- 当 RSS > `RSS_RESTART_MB` MB 时，SHALL 设置
  `self._graceful_stop_requested = True`，让既有 graceful_stop 路径自然
  退出（写 partial + 退出 0）
- 当环境变量 `GC_EVERY_N_TICKS > 0`（默认 200）时，每 N tick 跑一次
  `gc.collect()` 并 log freed cycles

外部 launcher / LaunchAgent SHALL 在下次巡检 tick 看到 PID 不存在 +
有 snapshot/partial → spawn replacement（complement 的 constructive
recovery 行为）；effect 是每 worker RSS oscillates around threshold
而不是单调爬升。

`RSS_RESTART_MB=0`（默认 off）SHALL 完全禁用 RSS 监控，保持向后兼容。

#### Scenario: RSS 超阈值触发 graceful_stop
- **WHEN** `RSS_RESTART_MB=100`、worker 跑到 RSS 120 MB（mock
  `resource.getrusage` 返回 120 MB）
- **THEN** 下一次 RSS check tick SHALL 设 `_graceful_stop_requested=True`；
  worker SHALL 在当前 tick 末尾退出；写出 partial；退出码 0

#### Scenario: 默认 off 不动行为
- **WHEN** `RSS_RESTART_MB` unset 或 == 0
- **THEN** worker SHALL 不发生 RSS-driven graceful stop；
  `_graceful_stop_requested` SHALL 永远是 False（除非外部 SIGUSR1）

#### Scenario: gc.collect 周期触发
- **WHEN** `GC_EVERY_N_TICKS=10`、worker 跑到 tick_global=20
- **THEN** `_init_memory_management_hooks` 注册的 hook SHALL 已经调用过
  `gc.collect()` 至少 2 次；log SHALL 含 "[gc] tick_global=10" / "[gc]
  tick_global=20" 字样
