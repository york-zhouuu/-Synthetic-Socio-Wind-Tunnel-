# Tasks — run-resilience

为 publishable run（1000 agent × 14 day × 4 variant × 30 seed）补齐抗故障 +
热修复基建。修 D1' Gemini 连接池死锁根因 + 统一 retry / circuit-breaker +
per-day checkpoint + graceful-stop 协议 + pre-flight 1000-agent smoke gate。

**Chain-Position**：`infrastructure`（为所有 publishable run 提供可靠执行
底座；不引入新主边界）

**前置**：`multi-day-simulation` 已 archive（`MultiDayRunner` /
`on_day_end` hook 已存在）
**下游**：D3 / 后续 publishable run 都将 SHALL 走新路径；`make
fitness-audit` 新增 `phase2-gaps.run-resilience` 探针

## 1. 新建 run_resilience 模块骨架

- [x] 1.1 创建 `synthetic_socio_wind_tunnel/run_resilience/` 目录
  + `__init__.py`（空，准备 re-export）
- [x] 1.2 添加 `synthetic_socio_wind_tunnel/run_resilience/retry.py`：
  `RetryPolicy` Pydantic frozen 模型 + `from_env()` classmethod +
  `next_backoff()` + `classify(exc)`
- [x] 1.3 添加 `synthetic_socio_wind_tunnel/run_resilience/circuit_breaker.py`：
  `PerKeyCircuitBreaker` 类 + `AllKeysOpenError` exception；状态机 closed →
  open → half-open；`failure_threshold` / `cooldown_seconds` 从 env 读
- [x] 1.4 添加 `synthetic_socio_wind_tunnel/run_resilience/checkpoint.py`：
  `DayCheckpointWriter` 类 + `IncompatibleCheckpointError` exception；
  `write_partial` 实现原子 `.tmp` + `rename`；`schema_version = "1"`
- [x] 1.5 添加 `synthetic_socio_wind_tunnel/run_resilience/health.py`：
  `HealthAudit` / `HealthAuditReport` Pydantic 模型 + 各阈值常量从 env 读；
  `audit(run_dir, now=...)` 主入口
- [x] 1.6 添加 `synthetic_socio_wind_tunnel/run_resilience/hotfix.py`：
  `HotfixSignalHandler` 类 + `install(runner)` 注册 SIGUSR1；handler 仅
  设置 `runner._graceful_stop_requested = True`，不做 I/O
- [x] 1.7 `synthetic_socio_wind_tunnel/run_resilience/__init__.py` re-export
  `RetryPolicy / PerKeyCircuitBreaker / DayCheckpointWriter / HealthAudit /
  HealthAuditReport / HotfixSignalHandler / AllKeysOpenError /
  IncompatibleCheckpointError`

## 2. RetryPolicy 单元测试

- [x] 2.1 新建 `tests/test_run_resilience_retry.py`：
  - `test_retry_policy_defaults`（构造无参 → 字段值匹配 spec 默认）
  - `test_next_backoff_exponential_with_jitter`（attempt 0/1/5 → 范围断言）
  - `test_classify_connection_error_retryable`
  - `test_classify_401_fatal`
  - `test_classify_429_retryable`
  - `test_classify_500_retryable`
  - `test_classify_400_fatal`
  - `test_from_env_overrides_defaults`（设 env → 字段被覆盖）
  - `test_from_env_invalid_value_falls_back`（恶意值如 "abc" → 用默认 + warn）

## 3. PerKeyCircuitBreaker 单元测试

- [x] 3.1 新建 `tests/test_run_resilience_circuit.py`：
  - `test_initial_state_closed`
  - `test_n_failures_open`（连续 5 次 record_failure → state == open）
  - `test_open_blocks_calls`（state==open 时 should_allow() == False）
  - `test_cooldown_expires_half_open`（mock 时间推进 → state == half_open）
  - `test_half_open_success_back_to_closed`
  - `test_half_open_failure_back_to_open_with_doubled_cooldown`
  - `test_capped_at_30_min`
  - `test_record_success_resets_failure_count`

## 4. DayCheckpointWriter 单元测试

- [x] 4.1 新建 `tests/test_run_resilience_checkpoint.py`：
  - `test_write_partial_atomic`（写盘期间用 mock OSError 模拟中断 → 目标
    路径不存在或合法 JSON）
  - `test_read_partial_round_trip`
  - `test_read_partial_incompatible_schema_raises`
  - `test_cleanup_partials_removes_only_target_seed`
  - `test_cleanup_partials_keeps_final_seed_json`
  - `test_partial_includes_all_required_fields`（seed / day_index /
    simulated_date / run_metrics / ledger_snapshot / memory_dump / provider
    / schema_version / created_at）
  - `test_write_partial_large_memory_dump_warns`（mock 200 MB dump → log
    warning 但仍写）

## 5. HealthAudit 单元测试

- [x] 5.1 新建 `tests/test_run_resilience_health.py`：
  - `test_audit_healthy_returns_healthy`（mock 健康 worker）
  - `test_audit_silent_30min_returns_warning`
  - `test_audit_silent_60min_returns_deadlock`
  - `test_audit_high_close_wait_returns_warning`
  - `test_audit_uninterruptible_state_returns_deadlock`
  - `test_audit_multiple_workers_aggregates_overall_status`
  - `test_audit_no_workers_returns_warning`（空 run_dir）

## 6. HotfixSignalHandler 单元测试

- [x] 6.1 新建 `tests/test_run_resilience_hotfix.py`：
  - `test_install_registers_sigusr1`
  - `test_sigusr1_sets_flag_only`（handler 不做 I/O；仅 flag 改变）
  - `test_double_sigusr1_idempotent`（连发两次 SIGUSR1 → flag 已 True 不重置）
  - `test_sigterm_not_intercepted`（SIGTERM 行为不变；仍抛 KeyboardInterrupt）

## 7. 修改 tier_llm_factory：注入 RetryPolicy

- [x] 7.1 在 `tools/tier_llm_factory.py` 顶部 import
  `synthetic_socio_wind_tunnel.run_resilience.{RetryPolicy,
  PerKeyCircuitBreaker, AllKeysOpenError}`
- [x] 7.2 `build_tier_clients(*, provider, retry_policy=None,
  http_pool_config=None, ...)` 加新参数（默认 None 时从 env 构造）；
  保持现有调用 0 改动
- [x] 7.3 把同一 RetryPolicy 实例传给所有 `_*TierClient` 构造器
- [x] 7.4 把 RESILIENCE_DISABLE=1 旁路逻辑加在 build_tier_clients 顶部：
  early-return 旧路径（不构造新 wrapper），stderr WARN

## 8. 修改 _GeminiTierClient

- [x] 8.1 `_GeminiTierClient.__init__` 新增 `api_keys: list[str] | None`
  参数（默认从 env 读 GEMINI_API_KEYS / GEMINI_API_KEY / GOOGLE_API_KEY）；
  每个 key 各自构造 `genai.Client` 实例
- [x] 8.2 注入自定义 httpx async client（与新版 google-genai SDK 兼容的
  路径——先试 `genai.Client(http_options={...})`；若 SDK 不支持则用
  monkey-patch `client.aio._api_client._async_httpx_client`）；明确
  `max_keepalive_connections=0` / `max_connections=600` / 各 timeout
- [x] 8.3 把现有 `asyncio.wait_for(45s) + 1-retry` 循环替换为
  `RetryPolicy` 驱动的循环；retryable 才退避重试、fatal 立即抛
- [x] 8.4 引入 per-key `PerKeyCircuitBreaker`；`generate` round-robin 选 key
  时 skip open 状态的 key；所有 key 都 open 抛 `AllKeysOpenError`
- [x] 8.5 引入 `_call_count` 累加；达 `recycle_after_calls` 时 `aclose()` +
  rebuild 当前 key 的 httpx async client

## 9. 修改 _DeepSeekTierClient

- [x] 9.1 把 httpx Limits 从 `max_keepalive_connections=100` 改为 0；现有
  multi-key 逻辑保留
- [x] 9.2 把 openai SDK 的 `max_retries=1` 改为 0（让 RetryPolicy 接管 retry）
- [x] 9.3 用 RetryPolicy 替代现有的 retry 路径；fatal 立即抛、retryable 退避
- [x] 9.4 引入 per-key `PerKeyCircuitBreaker`（替代当前简单 round-robin）
- [x] 9.5 引入 `_call_count` + `recycle_after_calls` 重建逻辑

## 10. _AnthropicTierClient

- [x] 10.1 若当前已有 Anthropic tier client 实现：注入 httpx async client +
  RetryPolicy + 单 key circuit breaker；否则跳过（仅在 spec scenario 中以
  "若使用 Anthropic 则同样规则适用" 形式覆盖）

## 11. tier_llm_factory 集成测试

- [x] 11.1 新建 `tests/test_tier_factory_resilience.py`：
  - `test_gemini_client_has_keepalive_zero`（构造后 introspect 内部 httpx）
  - `test_gemini_multi_key_round_robin`
  - `test_gemini_single_key_fallback`（仅 GEMINI_API_KEY，不设 GEMINI_API_KEYS）
  - `test_deepseek_client_has_keepalive_zero`
  - `test_retry_policy_shared_across_clients`（同一 instance）
  - `test_resilience_disable_skips_hardening`（env=1 → 旧路径）

## 12. MultiDayRunner 接入 checkpoint + resume_from

- [x] 12.1 `synthetic_socio_wind_tunnel/orchestrator/multi_day.py`：
  `MultiDayRunner.__init__` 新增 `output_dir: Path | None = None` /
  `checkpoint_writer: DayCheckpointWriter | None = None` / `resume_from:
  int = 0` 三个参数（默认值保持向后兼容）
- [x] 12.2 `MultiDayRunner.run_multi_day` 主循环：每 day 结束在 `on_day_end`
  hook 触发前调 `checkpoint_writer.write_partial(...)`（若 output_dir 提供）；
  写盘失败 log warning 但继续跑
- [x] 12.3 主循环按 `resume_from` 推进起点：day_index 从 resume_from 起到
  num_days-1；`resume_from > num_days` 抛 ValueError
- [x] 12.4 新增 public attribute `_graceful_stop_requested: bool = False`；
  主循环在每 tick 后检查；True 时不再启动下一 tick，写当前已完成 day 的
  partial，返回截断的 MultiDayResult

## 13. MultiDayRunner 测试扩展

- [x] 13.1 扩展 `tests/test_multi_day.py`：
  - `test_per_day_partial_written`（14 天 run → 14 个 partial 文件存在）
  - `test_partial_write_failure_does_not_stop_run`（mock OSError on day 5）
  - `test_no_partial_when_output_dir_none`（向后兼容）
  - `test_resume_from_5_yields_9_day_summaries`
  - `test_resume_from_zero_unchanged_behavior`
  - `test_resume_from_exceeds_num_days_raises`
  - `test_graceful_stop_truncates_run`（中途置 flag → 返回截断 result）
  - `test_graceful_stop_writes_partial_of_last_complete_day`

## 14. tools/audit_run_health.py CLI

- [x] 14.1 新建 `tools/audit_run_health.py`：
  - argparse: positional `run_dir`, `--json`, `--watch <interval>`
  - 调用 `HealthAudit().audit(run_dir)`
  - human-readable 输出格式
  - 退出码 0 / 1 / 2 按 spec
- [x] 14.2 新建 `tests/test_audit_run_health_cli.py`：subprocess 运行
  CLI，断言退出码 / stdout 含期望字段

## 15. tools/preflight_full_smoke.py CLI

- [x] 15.1 新建 `tools/preflight_full_smoke.py`：
  - 硬编码 1000 agent / 1 day / 全 4 variant / 1 seed / 500 num_protagonists
  - argparse: `--provider <gemini|deepseek|anthropic>`、`--output-dir <path>`
  - 内部调用 `run_variant_suite.run_seed_with_metrics` 4 次（每 variant 一次）
    或直接 reuse `run_variant_suite.py` 子进程
  - 跑完后调 `HealthAudit().audit(...)` 一次；overall != healthy → 退出 1
- [x] 15.2 新建 `tests/test_preflight_full_smoke.py`：mock 子调用、验证
  argparse + 退出码逻辑（不真跑 1000 agent，仅测试 CLI 装配）

## 16. run_variant_suite.py 集成 resilience flag

- [x] 16.1 `tools/run_variant_suite.py` argparse 新增：
  - `--resume`（store_true）
  - `--resume-from-day <int>`（默认 None）
  - `--skip-preflight`（store_true）
- [x] 16.2 实现 `--resume` 自动检测：scan variant dir 找最近
  `seed_{N}_day{D}.partial.json`；构造 `MultiDayRunner(resume_from=D+1,
  ...)`；已有 `seed_{N}.json` 时 skip
- [x] 16.3 实现 `--resume-from-day` 覆盖：传入值优先于自动检测
- [x] 16.4 实现 publishable mode 强制 preflight：检测 `agents==1000 and
  num_days==14`（事实 publishable），自动调 `tools/preflight_full_smoke.py`
  作为前置；preflight 失败 → 整 suite 退出 != 0；`--skip-preflight` 被
  忽略且 stderr WARN
- [x] 16.5 完整 variant run 完成后调 `DayCheckpointWriter.cleanup_partials`
  清理该 seed 的 partial 文件
- [x] 16.6 在 worker 进程入口注册 `HotfixSignalHandler.install(runner)`

## 17. run_variant_suite 集成测试

- [x] 17.1 新建 `tests/test_run_variant_suite_resume.py`：
  - `test_resume_from_partial_continues`（fixture: 已有 day 5 partial →
    suite 跑 day 6-13）
  - `test_resume_no_partial_starts_from_zero_with_warning`
  - `test_resume_with_explicit_day_overrides_auto_detect`
  - `test_skip_preflight_ignored_in_publishable_mode`
  - `test_cleanup_partials_after_seed_complete`
- [x] 17.2 新建 `tests/test_hotfix_integration.py`：在子进程跑短 run，
  发 SIGUSR1，断言：partial 写盘 + 进程退出 0 + 二次 `--resume` 可
  接续到末尾

## 18. 公共 API re-export

- [x] 18.1 `synthetic_socio_wind_tunnel/__init__.py` 加入：
  - `from synthetic_socio_wind_tunnel.run_resilience import (RetryPolicy,
    PerKeyCircuitBreaker, DayCheckpointWriter, HealthAudit,
    HealthAuditReport, HotfixSignalHandler, AllKeysOpenError,
    IncompatibleCheckpointError)`
- [x] 18.2 加 smoke test：`pytest -k "test_import_run_resilience"`
  验证 `from synthetic_socio_wind_tunnel import RetryPolicy` 成功

## 19. Fitness-audit 探针

- [x] 19.1 新建 `synthetic_socio_wind_tunnel/fitness/audits/run_resilience.py`：
  - 探针 1：`import synthetic_socio_wind_tunnel.run_resilience` 成功
  - 探针 2：`tools/audit_run_health.py` 存在且可执行
  - 探针 3：`tools/preflight_full_smoke.py` 存在且可执行
  - 探针 4：introspection `_GeminiTierClient` 与 `_DeepSeekTierClient` 默认
    构造时 httpx limits.max_keepalive_connections == 0
  - 探针 id：`phase2-gaps.run-resilience`；mitigation_change：`run-resilience`
- [x] 19.2 跑 `make fitness-audit`，确认该条从 fail → pass

## 20. 文档与配置示例

- [x] 20.1 新建 `docs/agent_system/15-run-resilience.md`：
  - 一段故事化背景（D1' 事故 + 为什么这个 capability 存在）
  - 架构图：tier_llm_factory（hardened）→ RetryPolicy ←→
    PerKeyCircuitBreaker；MultiDayRunner ←→ DayCheckpointWriter；
    `HotfixSignalHandler` 注册到 worker；`HealthAudit` 旁路观察
  - CLI 用法示例：preflight / audit_run_health / --resume / SIGUSR1
  - 与 `multi-day-run` / `suite-wiring` spec 的对接
- [x] 20.2 更新 `.env.example`：增加 GEMINI_API_KEYS（注释样例）+ 主要
  RESILIENCE_* 环境变量及默认值注释
- [x] 20.3 更新 `README.md` 的 Development Status：为 orchestrator /
  tier_llm_factory 行补一条 "抗故障 + 热修复（run-resilience）" 状态
- [x] 20.4 更新 `CLAUDE.md`：在 "关键不变量" 段加一条
  `run-resilience 2026-05-15`：publishable run SHALL 走 preflight + 用
  hardened tier client + per-day checkpoint；任何长跑前 SHALL 用
  `audit_run_health.py` 巡检

## 21. 性能 & 回归

- [x] 21.1 跑全部 `pytest tests/`：1267 现有 + 新增 ~30 测试 SHALL 全 pass
- [x] 21.2 跑 `tools/smoke_experiment_demo.py --agents 100`：8/8 PASS 输出
  不变（向后兼容验证）
- [x] 21.3 跑 `tools/preflight_full_smoke.py --provider deepseek` 一次完整：
  - 4 variant 全部完成
  - CLOSE_WAIT peak < ulimit × 60%
  - LLM call 99%+ 成功率
  - wall time < 30 min
- [x] 21.4 手动 SIGUSR1 验证：跑短 (3-day × 100-agent) run → SIGUSR1 中途 →
  partial 落地 + exit 0 → `--resume` 接续 → 最终结果与从头跑等价

## 22. 验证 & 归档准备

- [x] 22.1 `openspec validate run-resilience --strict` 通过
- [x] 22.2 grep 检查：`RetryPolicy` / `DayCheckpointWriter` /
  `HotfixSignalHandler` / `HealthAudit` / `PerKeyCircuitBreaker` 在 spec /
  代码 / 测试三处名字一致
- [x] 22.3 grep 检查：`RESILIENCE_*` 环境变量在 spec 表格 / `.env.example` /
  `from_env` 实现三处一致（无遗漏 / 无错字）
- [x] 22.4 确认所有 ADDED Requirement 至少一个 Scenario 有对应 test
- [x] 22.5 准备 `docs/sessions/2026-MM-DD-run-resilience-shipped.md`（一段
  total summary：修了什么、preflight wall time、新 CLI 用法），等本 change
  全部 task done 后写
