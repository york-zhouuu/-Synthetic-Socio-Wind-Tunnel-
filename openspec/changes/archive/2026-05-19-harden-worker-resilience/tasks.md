## 1. Snapshot atomic write 多进程安全（30 min）

- [x] 1.1 在 `tests/test_simulation_checkpoint.py::TestAtomicWrite::test_concurrent_writes_no_corruption` 加并发测试（10 轮 barrier+threads）
- [x] 1.2 改 `state_snapshot.py::write_atomic` 用 `tempfile.mkstemp(dir=parent, prefix=name+'.', suffix='.tmp')`
- [x] 1.3 同样改 `checkpoint.py::DayCheckpointWriter.write_partial`；去掉 glob-based stale .tmp 清扫
- [x] 1.4 更新被改测试 `test_cleans_pre_existing_tmp` → `test_succeeds_with_unrelated_tmp_present`；`test_atomic_cleans_pre_existing_tmp` → `test_atomic_leaves_unrelated_tmp_alone`；全部 42 tests 绿

## 2. SIGUSR1 setup-phase 哨兵守护（45 min）

- [x] 2.1 新建 `tests/test_aborted_in_setup_sentinel.py`：4 个测试覆盖 sentinel 写、no partial、output_dir=None no-op、end-to-end metadata
- [x] 2.2 改 `_write_partial_at_stop`：setup-phase no-op + 加 log warning（不再静默返回）
- [x] 2.3 实现 `_write_aborted_in_setup_sentinel`：写 `seed_N.aborted_in_setup.json` 含 seed/aborted_at/reason/wal_writes/completed_days
- [x] 2.4 `run_multi_day` 在 finally 块后检测 setup-phase abort，写 sentinel，metadata 加 `aborted_in_setup=True`
- [x] 2.5 `tools/resume_publishable.py`：cell_state 识别 sentinel；spawn 前 unlink sentinel
- [~] 2.6 `tools/audit_run_health.py`：暂不改（audit 工具是 live-process 检测，sentinel 是 file-state，归 resume_publishable 管）
- [x] 2.7 11 个 test 全绿（含 hotfix integration）

## 3. DialogueService rolling cleanup（1 hr）

- [x] 3.1+3.2 新建 `tests/test_dialogue_service_eviction.py`：8 个测试覆盖 evict / in-progress 保留 / 零 cutoff no-op / idempotent / retrieve_summary / snapshot round-trip / legacy snapshot 兼容
- [x] 3.3 加 `DialogueSummary` frozen dataclass（slots）
- [x] 3.4 加 `_dialogue_summaries` 字段 + `evict_old_dialogues(before_tick)` 方法（caller 计算 cutoff，service 不管 day）
- [x] 3.5 加 `retrieve_summary` 公共 API（live → 实时构造，evicted → cached）
- [x] 3.6 `MultiDayRunner.run_multi_day` 在 day_end 后调 `evict_old_dialogues`，cutoff = `(day_index - DIALOGUE_EVICT_GRACE_DAYS) × ticks_per_day`，default grace = 2
- [x] 3.7 `to_snapshot_state` / `from_snapshot_state` 处理 summaries；legacy snapshot 缺该 key 时 default {}
- [~] 3.8 扫 metrics/ — encounter / dwell 等不读 messages，只用 participants/timestamps，无需改
- [x] 3.9 102 个 dialogue + multi_day 测试全绿（含新增 8 个 eviction 测试）

## 4. 直接 LLM call asyncio.wait_for 兜底（2 hr）

**发现**：5 个调用点都已经在历史 capability 1.9 / 1.13 commit 里 wrapped
了。本 group 改成"加 regression guard 防回退"。

- [x] 4.1 新建 `tests/test_direct_llm_timeout_guard.py`：源码扫描式 regression test，断言 5 个文件中每个 `.generate(` 都在 `wait_for(` 200 字符窗口内 + 每个 `wait_for(` 在 1500 字符窗口内有 `TimeoutError` 处理
- [~] 4.2 `memory/reflection.py::reflect` — **已有** 60s wait_for + fallback `return []`
- [~] 4.3 `memory/importance.py::score_importance` — **已有** 30s wait_for + fallback `return self._default_on_failure`
- [~] 4.4 `agent/planner.py::Planner.replan` — **已有** 30s wait_for + fallback `current_plan.model_copy()`
- [~] 4.5 `data_loader/lanecove.py:756 _generate_life_history_for_one` — **已有** 300s wait_for + fallback `return []`
- [~] 4.6 `data_loader/lanecove.py:1005 _generate_identity_text_for_one` — **已有** 120s wait_for + fallback `_fallback_identity_text(profile)`
- [~] 4.7 没新增统一 helper（每个调用点 timeout 数值不同：30s/30s/60s/120s/300s——各自合理；统一 wrapper 反而拉平失去 per-site 语义）
- [x] 4.8 8 个 regression test 全绿（每个文件 2 个：has-wait_for + has-TimeoutError）

## 5. snapshot 包含 run_metrics_state（2-3 hr）

**发现**：capability 1.11 + 1.12 已经实施（schema v2 加
`tick_metrics_recorder_state`、v3 加 `dialogue_service_state`）。
`TickMetricsRecorder.to_snapshot_state` / `from_snapshot_state` 已存在；
`MultiDayRunner._write_snapshot` 已经包进 snapshot；`restore_into`
已经从 snapshot 灌回。只缺"Worker A→B resume 后续累积"的明确 scenario。

- [~] 5.1 测试覆盖已在 `tests/test_metrics_recorder.py::TestRecorderSnapshotRoundtrip`（4 个 test）
- [~] 5.2 `metrics/recorder.py::TickMetricsRecorder` to/from_snapshot_state — **已有**
- [~] 5.3 `SimulationCheckpoint` 已经 schema v3（含 v2 的 `tick_metrics_recorder_state`）
- [~] 5.4 `SimulationCheckpoint.read` 已处理 v1/v2 → v3 fallback（missing key default {}）
- [~] 5.5 `MultiDayRunner._write_snapshot` + `_write_final_snapshot_on_graceful_stop` 已 to_snapshot_state — **已有**
- [~] 5.6 `restore_into` 已 from_snapshot_state — **已有**
- [x] 5.7 加 `test_resume_appends_to_existing_buckets`：Worker A 跑 day 0-1 → snapshot → Worker B from-snapshot 跑 day 2-3 → 断言 `snapshot()` 4 个 day-summaries
- [x] 5.8 29 个 metrics + resume + subsystem 测试全绿

## 6. 形式化 CLAUDE.md 三条不变量进 scenario 测试（30 min）

- [x] 6.1 新建 `tests/test_harden_invariants.py`：6 个 regression test 覆盖
  - **monitor-as-control-plane**：`resume_publishable.py` 源码无 `os.kill` / `signal.SIG*`；RUNNING_STALE 分支 entry["action"]=="report_only"
  - **sigusr1-graceful-stop-corruption**：`run_variant_suite.py` 含 graceful_stop gate + `GRACEFUL_STOP after` log + cleanup_partials 在 else 分支
  - **memory-auto-restart**：RSS over 阈值 → `_graceful_stop_requested=True`；GC_EVERY_N_TICKS=10 跑到 tick 20 → gc.collect 调 2 次；env 全 0 → 不注册 hook
- [x] 6.2-6.4 6/6 全绿

## 7. 文档与回归（30 min）

- [x] 7.1 跑相关 test files：116 + 38 + 48 = 202 个 test 全绿；全量 `pytest tests/` 487 pass, 1 pre-existing fail (`test_deepseek_tier_client.py::test_deepseek_max_tokens_per_tier`, 393216 vs 1024，无关本 change)
- [x] 7.2 `docs/backlog.md`：1.9 ✅ + 1.11 ✅，1.7 1.7 状态行补充本 change
- [x] 7.3 `CLAUDE.md` 增加 "harden-worker-resilience 2026-05-19" section，引用 5 个 regression test 文件
- [x] 7.4 `openspec validate harden-worker-resilience` → "is valid"
- [x] 7.5 跑 `openspec archive harden-worker-resilience` 把 deltas merge 进正式 spec
