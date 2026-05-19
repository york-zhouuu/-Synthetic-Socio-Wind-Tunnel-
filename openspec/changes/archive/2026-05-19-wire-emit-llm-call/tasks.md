## 1. TDD red

- [x] 1.1 新建 `tests/test_emit_llm_call_subprocess.py`:
  - `test_dev_smoke_writes_llm_jsonl_with_success_records` (subprocess
    real dev smoke with `LLM_SAMPLE_RATE=1.0` → llm.jsonl 有 lines)
  - `test_emit_llm_call_includes_required_fields` (验证每行 schema)
- [x] 1.2 跑 → 红

## 2. 实现 tier client wrapping

- [x] 2.1 加 `tier` / `provider` 参数到每个 tier client 构造函数 +
  存为 `self._tier` / `self._provider`
- [x] 2.2 `build_tier_clients` 传递 tier/provider 到构造
- [x] 2.3 每个 `generate()` 包：
  - `t0 = perf_counter()`
  - try _run_with_retry → emit success
  - except → emit exhausted（exc_class）+ raise
- [x] 2.4 跑 G1 → 转绿（success path）

## 3. do_something fallback emit

- [x] 3.1 在 do_something 的 3 个 except 路径加 emit_llm_call(
  status="fallback") — AllKeysOpenError / Exception / unparseable
- [x] 3.2 跑 G1 → 转绿（fallback path）

## 4. Regression + archive

- [x] 4.1 跑既有 instrumentation / retry / multi_day tests → 全绿
- [x] 4.2 跑全量 regression
- [x] 4.3 archive + commit + push
