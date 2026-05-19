## 1. TDD 红 — classify 行为 unit tests 先于实现

- [x] 1.1 新建 `tests/test_retry_policy_class_name_classify.py`：
  - `test_classify_openai_apiconnection_error_returns_retryable`
    (用真实 `openai.APIConnectionError(request=None)`)
  - `test_classify_openai_apitimeout_error_returns_retryable`
  - `test_classify_httpx_connecterror_returns_retryable`
    (用真实 `httpx.ConnectError("simulated")`)
  - `test_classify_httpx_readtimeout_returns_retryable`
  - `test_classify_httpx_remoteprotocolerror_returns_retryable`
  - `test_classify_runtime_error_returns_unknown` (regression: random
    exc 不被误判)
  - `test_classify_fatal_http_wins_over_class_name` (priority: 401
    fatal 不被 class-name 命中覆盖)
- [x] 1.2 跑 → 红（`retryable_exc_class_names` 字段不存在或默认空 →
  AttributeError / 全部返回 unknown）

## 2. TDD 红 — _run_with_retry integration tests

- [x] 2.1 新建 `tests/test_run_with_retry_class_name_path.py`：
  - `test_retries_apiconnection_error_2_then_success` (mock op 抛
    APIConnectionError 2 次后成功 → max_attempts=3 应成功 + record_success)
  - `test_exhausts_apiconnection_error_3_times` (mock op 全抛 → 最后
    raise 最后一次 exc + record_failure 恰好 1 次)
  - `test_breaker_record_failure_not_called_during_retry` (mock op
    抛后成功 → record_failure 0 次)
- [x] 2.2 跑 → 红（实现未落地）

## 3. TDD 红 — env override property test

- [x] 3.1 新建 `tests/test_retry_policy_env_class_names.py`：
  - `test_env_override_appends_to_defaults` (设
    `RESILIENCE_RETRY_EXC_CLASS_NAMES=MyCustomError,AnotherErr` →
    union with defaults，12 + 2 = 14 elements)
  - `test_empty_env_uses_defaults` (env 缺失 / 空 → 默认 12 元素)
  - `test_whitespace_trimmed_per_name`
  - `test_malformed_env_falls_back_to_defaults_with_warning` (设
    malformed value → defaults + warning logged)
- [x] 3.2 跑 → 红

## 4. TDD 红 — hypothesis property test

- [x] 4.1 新建 `tests/test_retry_policy_class_name_property.py`：
  - hypothesis 生成 random ASCII class names → 验证不在 default set
    的随机 name 永远返回 unknown / 不被误判 retryable
  - 验证 policy frozen invariant：100 次 classify 后字段不变
- [x] 4.2 跑 → 红

## 5. 实现 RetryPolicy 扩展

- [x] 5.1 在 `synthetic_socio_wind_tunnel/run_resilience/retry.py` 加
  module-level `_DEFAULT_RETRYABLE_EXC_CLASS_NAMES: frozenset[str]`
  常量（12 个 class name）
- [x] 5.2 `RetryPolicy` 加字段 `retryable_exc_class_names:
  frozenset[str] = Field(default_factory=lambda: _DEFAULT_...)`
- [x] 5.3 `classify()` 在 HTTP status 检查**之后**、isinstance 检查
  **之前**插入 class-name 匹配路径：
  ```python
  if type(exc).__name__ in self.retryable_exc_class_names:
      return "retryable"
  ```
- [x] 5.4 `from_env()` 加 `RESILIENCE_RETRY_EXC_CLASS_NAMES` 解析：
  - 逗号分隔、strip 空白、过滤空字符串
  - **union** with `_DEFAULT_RETRYABLE_EXC_CLASS_NAMES`（追加，不替换）
  - malformed → log warning + fallback to defaults
- [x] 5.5 跑 G1-G4 tests 全部转绿

## 6. Regression: backward compat

- [x] 6.1 跑 existing `tests/test_retry*.py`、`tests/test_run_with_retry*.py`
  (or wherever 现有 RetryPolicy tests 住的) → 不回退
- [x] 6.2 跑 `tests/test_run_resilience_retry.py` 全部绿
- [x] 6.3 跑 `pytest tests/ -q --ignore=tests/test_event_to_json_performance.py`
  全量 → 不回退（参照 enforce-worker-rss-cap 基线 1765 passed / 1 xfail
  / 3 skipped）

## 7. E2E smoke 验证

- [x] 7.1 写 `tests/test_retry_e2e_smoke.py`：构造一个 deepseek-stub
  client，inject 一个 fake operation 抛 mock APIConnectionError 2 次
  后成功；run via `_run_with_retry`；断言 retry 序列正确 + circuit
  breaker 没 burn
- [x] 7.2 (可选) 改 `tools/audit_llm_health.py` 加一个 "retry-budget
  visible" probe：grep worker log 看 `[retry] attempt` log line 频率，
  high frequency 是 health signal 而非 issue

## 8. Spec validate + archive

- [x] 8.1 `openspec validate retry-network-blip-tolerance --strict`
- [x] 8.2 把 tasks.md 全部 checkbox 改为 `[x]`
- [x] 8.3 `openspec archive retry-network-blip-tolerance --yes`
- [x] 8.4 commit + push
