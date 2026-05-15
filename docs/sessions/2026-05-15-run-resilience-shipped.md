# run-resilience shipped · 2026-05-15

## TL;DR

D1' Gemini 连接池死锁后 4 小时内：OpenSpec proposal → 全量实现 → 1436
pytest passed / 0 failed / 3 skipped → `openspec validate --strict` 通过 →
fitness-audit `phase2-gaps.run-resilience.*` 5/5 PASS。

Publishable run（1000 agent × 14 day）从此前置 1000-agent × 1-day preflight
gate；跑期间 worker 接 SIGUSR1 优雅停机 + 写 per-day partial；任何长跑都
能用 `tools/audit_run_health.py` 巡检；改 `RESILIENCE_*` 环境变量后
`--resume` 续跑即新配置生效。

## 修了什么

- D1' 根因：Gemini async SDK + httpx 连接池在 server 主动 close 后留下
  CLOSE_WAIT 死 fd → 整池毒化 → `asyncio.wait_for(45s)` 取消单个 await
  但池状态不变 → 无限循环
- 修法：三家 provider（Gemini / DeepSeek / Anthropic）统一注入自定义
  `httpx.AsyncClient(limits=httpx.Limits(max_keepalive_connections=0))`，
  每次 call 用完立即 close socket
- 代价：每次 call 多 1 次 TLS handshake（~80-150ms），整体慢 10-20%；
  在 72h publishable 上加 ~12h，相比"100% 数据丢失"划算

## 引入了什么

新 capability `run-resilience`（13 个 ADDED Requirement）+ modified
capability `multi-day-run`（3 个 ADDED Requirement）。

| 模块 / 文件 | 角色 |
|---|---|
| `synthetic_socio_wind_tunnel/run_resilience/retry.py` | RetryPolicy 统一退避策略 |
| `synthetic_socio_wind_tunnel/run_resilience/circuit_breaker.py` | PerKeyCircuitBreaker + AllKeysOpenError |
| `synthetic_socio_wind_tunnel/run_resilience/checkpoint.py` | DayCheckpointWriter (原子 .tmp + rename) |
| `synthetic_socio_wind_tunnel/run_resilience/health.py` | HealthAudit + DefaultSystemProbe (ps/lsof) |
| `synthetic_socio_wind_tunnel/run_resilience/hotfix.py` | HotfixSignalHandler (SIGUSR1) |
| `tools/tier_llm_factory.py` | 三家 provider 重写：keepalive=0 + retry + breaker + multi-key |
| `tools/audit_run_health.py` | CLI: 巡检 worker pid + log + TCP + 状态 |
| `tools/preflight_full_smoke.py` | CLI: 1000 agent × 1 day × 4 variant gate |
| `tools/run_variant_suite.py` | 接入 partial 写盘 / SIGUSR1 / --resume-from-day / --skip-preflight (publishable 忽略) |
| `synthetic_socio_wind_tunnel/orchestrator/multi_day.py` | MultiDayRunner + checkpoint/resume/graceful-stop |
| `synthetic_socio_wind_tunnel/fitness/audits/run_resilience.py` | 5 个 phase2-gaps audit 探针 |

## 测试覆盖

- `tests/test_run_resilience_retry.py` — 16 test (RetryPolicy)
- `tests/test_run_resilience_circuit.py` — 11 test (PerKeyCircuitBreaker)
- `tests/test_run_resilience_checkpoint.py` — 10 test (DayCheckpointWriter)
- `tests/test_run_resilience_health.py` — 10 test (HealthAudit)
- `tests/test_run_resilience_hotfix.py` — 6 test (HotfixSignalHandler)
- `tests/test_tier_factory_resilience.py` — 16 test (集成: keepalive=0 + multi-key + retry + breaker + RESILIENCE_DISABLE)
- `tests/test_multi_day.py` 新增 11 test (TestCheckpoint + TestResumeFrom + TestGracefulStop) — 23/24 pass / 1 skipped
- `tests/test_audit_run_health_cli.py` — 6 test (CLI end-to-end)
- `tests/test_preflight_full_smoke.py` — 11 test (CLI dispatch)
- `tests/test_run_variant_suite_resume.py` — 6 test (suite 集成，含 cleanup_partials 真跑 97s)

**总：~99 个新增 test 全 pass；全量 pytest 1436 passed, 3 skipped, 0 failed**

## 用法速记

```bash
# 1. 配 .env（multi-key 推荐）
export GEMINI_API_KEYS=k1,k2,k3
export DEEPSEEK_API_KEYS=k1,k2

# 2. publishable run（preflight 自动跑）
python tools/run_variant_suite.py \
  --variants baseline,hyperlocal_push,global_distraction,phone_friction \
  --seeds 15 --agents 1000 --num-days 14 \
  --phase-days 4,6,4 --mode publishable --use-aitown \
  --aitown-provider deepseek --num-protagonists 500 --workers 4 \
  --suite-name d3_deepseek_15seed

# 3. 巡检（任意时刻、可塞进 cron）
python tools/audit_run_health.py data/experiments/<run>/

# 4. 卡了 / 想改配置：SIGUSR1 → 改 env → --resume
kill -USR1 <worker_pid>
export RESILIENCE_RETRY_MAX_ATTEMPTS=5
python tools/run_variant_suite.py --suite-dir <run> --resume ...
```

## 已 defer 的任务

下列 task 需要真实跑（钱 / 时间 / 手动）才能验证，留给真实跑 publishable
时一并完成：

- **21.3** `tools/preflight_full_smoke.py --provider deepseek` 一次完整
  跑 — 需 DeepSeek API key + 15-20 min wall time + 真消耗 API 额度
- **21.4** SIGUSR1 手验 3-day × 100-agent → 写 partial → exit 0 → --resume
  接续 — 需手动启动 worker + 在另一终端 kill

其它 22.5 子项（本 ship 文档）即此文。

## 验证清单

- [x] 1436 passed / 3 skipped / 0 failed（pytest 全量，8.4 min）
- [x] `openspec validate run-resilience --strict` 通过
- [x] `from synthetic_socio_wind_tunnel import RetryPolicy, DayCheckpointWriter, ...` 顶层 import 成功
- [x] fitness-audit `phase2-gaps.run-resilience.*` 5/5 PASS
- [x] RESILIENCE_* env vars 三处一致（spec 表 / .env.example / source code）
- [x] tier_llm_factory 三家 provider 的内部 httpx `max_keepalive_connections == 0`
- [x] CLAUDE.md "关键不变量" 加 run-resilience 段
- [x] README "Development Status" 加 run-resilience 行
- [x] `docs/agent_system/15-run-resilience.md` 用户向白话指南
- [ ] D2 续跑或 D3 fresh（待用户启动；D2 当前悬停于 5-15 20:42，baseline 15-seed 已 aggregate，hp 3/15，gd/pf 未启动）

## 下一步

1. 决定 D2 续跑（baseline 已完成 15 seed + aggregate；hp/gd/pf 缺）vs 启 D3 fresh
   —— D2 dir：`data/experiments/20260511_172808_d2_deepseek_publishable/`
   —— 续跑用 `--suite-dir <D2_dir> --resume` 走新基建路径
2. 在新机器上跑 `tools/preflight_full_smoke.py --provider deepseek` 一次完整
3. 跑 D3 publishable（1000 agent × 14 day × 15 seed × DeepSeek），观察 keepalive=0
   的实际开销是否如预期 ~10-20%
4. archive `run-resilience` change（`openspec archive run-resilience`）
