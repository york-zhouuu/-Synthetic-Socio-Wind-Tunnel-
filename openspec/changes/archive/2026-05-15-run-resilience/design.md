## Context

D1' 事故（2026-05-15）暴露了三个项目级风险：

1. **Scale-only 连接池死锁**：google-genai async SDK 在 macOS kqueue 下，长跑
   过程中 LLM provider 关闭老 TCP 连接时 httpx async transport 不把 fd 标记
   为 broken，残留为 CLOSE_WAIT。当池子里所有 slot 都被毒化，新 task 拿不到
   slot 也无法刷新池——`asyncio.wait_for` 取消单个 await 但**池状态不变**，
   下一个 task 继续死锁。50/100/200-agent smoke 一律触发不到（百万级 LLM
   call 才饱和），1000-agent × 14d 跑几小时就撞。
2. **重试逻辑碎片化**：`_GeminiTierClient` 用 `asyncio.wait_for(45s)` + 手写
   1-retry；`_DeepSeekTierClient` 用 openai SDK `timeout=45 max_retries=1`；
   Anthropic 路径完全靠 SDK 默认值（理论上 timeout=600s × max_retries=2 ≈
   30 min worst-case）。retryable / fatal 分类无统一定义；per-key 熔断未实现，
   单 key 抢 4 worker 时毒化叠加 4 倍速。
3. **14-day 全有或全无**：死锁 / 崩溃 / Ctrl-C 发生在 `seed_{N}.json` dump
   之前就是 100% 数据丢失。MultiDayRunner 的 `on_day_end` hook 已存在但
   未被利用为 checkpoint 写盘点。

**当前活跑**：D2 publishable run（DeepSeek × 15 seed × 14 day × 1000 agent）
预计 60-80h wall time；D1' 同样的根因在 DeepSeek + openai SDK 路径上理论上
也存在（CLOSE_WAIT 2212 已在 D1' phone_friction worker 累积），不修就是
赌运气。

**Stakeholders**：项目维护者（York），D2 + D3 publishable run 数据消费者
（论文 / 五幕报告 / poster），未来切其它 provider（Anthropic 直连）的 contributor。

## Goals / Non-Goals

**Goals**：

- 完全阻断 D1' 的连接池毒化路径（fd 不再累积，CLOSE_WAIT 接近 0）
- 任何长跑 run 的最坏损失 ≤ 1 模拟天（per-day checkpoint）
- 三个 provider 的 retry / circuit-breaker / pool 行为契约级一致
- 单条配置改动（环境变量）→ 重启 worker 即生效，不必改代码（热重载）
- Pre-flight 1000-agent × 1-day full smoke 阻断 scale-only bug 进入 publishable
- 所有新增能力 testable（每条 SHALL 至少一个 Scenario）

**Non-Goals**：

- 不重写 `tier_llm_factory`：在现有类上增量改、保留 `build_tier_clients()`
  签名向后兼容
- 不引入新 LLM provider
- 不动 Atlas / Ledger / Perception / Collapse（CQRS 主链零变更）
- 不做 multi-machine / distributed coordinator（multi-key + 单机 multi-worker
  足够 D2 / D3）
- 不做"无人值守自动 hotfix"——本 change 仅保证 kill + 修配置 + restart 的
  损失最小化；bug 诊断 + 补丁仍是手工活
- 不引入新依赖（httpx / pydantic 都是既有）

## Decisions

### D1 · 连接池修复策略：`max_keepalive_connections=0` 而非切回 sync + ThreadPool

**选择**：在 Gemini / DeepSeek / Anthropic 三个 async client 注入自定义
`httpx.AsyncClient(limits=httpx.Limits(max_keepalive_connections=0))`，禁止
socket 复用——每次 call 用完立即 close，CLOSE_WAIT 没机会累积。

**Why over alternatives**：

- **alt A · 周期性 `aclose()` 重建池**：单独不够——两次回收之间池子可能就
  已饱和。但**可作为补充**：作为第二层防御，每 1000 次 call 主动 aclose 重建，
  清掉任何 SDK 内部的状态残留。最终方案是 keepalive=0 + 周期重建双保险。
- **alt B · 切回 sync SDK + ThreadPoolExecutor**：完全绕开 asyncio/httpx 死
  锁面，但牺牲单 worker 内 500 protag 并行 → 5x 速度损失（per-tick LLM
  10s → 50s）。14-day × 1000-agent × 4-variant 整体 wall time 5x = 75-100h
  额外。不可接受。
- **alt C · 直接 monkey-patch SDK 内部 client**：D1' 事故 handoff 提到的方案
  B（替换 `client.aio._api_client._async_httpx_client`）。脆——SDK 版本升一
  级路径就变。
- **alt D · 切其它 SDK 内部 HTTP backend（aiohttp / requests）**：超出
  本 change 范围；返工成本大。

**Trade-off**：keepalive=0 每次 call 多一次 TLS handshake（~80-150ms），整体
慢 10-20%。可接受——D2 publishable 60-80h × 1.2 = 72-96h，比"完全跑挂"好得多。

**注意**：DeepSeek 当前已显式注入 `httpx.AsyncClient(max_keepalive=100,
max_connections=600)`——不是 keepalive=0；本 change SHALL 改为 0 并把
periodic recycle 作为补充。代价是 DeepSeek 重连开销，但根因防护一致。

### D2 · 统一 RetryPolicy 的位置：`synthetic_socio_wind_tunnel.run_resilience` 模块而非 `tools/`

**选择**：`RetryPolicy` 是 Pydantic frozen 模型，住在新模块
`synthetic_socio_wind_tunnel/run_resilience/retry.py`，对外通过包根
`__init__.py` re-export。`tier_llm_factory.py`（tools/）从该模块 import。

**Why over alternatives**：

- **alt A · 直接放 `tools/tier_llm_factory.py`**：tier_llm_factory 是工具脚本
  而非项目包公共 API；其它入口（未来 metrics 计算路径 / 单元测试 / 别的 CLI）
  想复用就要相互依赖 tools 路径，不优雅。
- **alt B · 放 `synthetic_socio_wind_tunnel/agent/`**：agent capability 已
  覆盖 Planner 的 LLMClient 协议，但 retry policy 属于"基础设施横切"——
  跨 agent / orchestrator / suite，不该绑死在 agent。

**含义**：与 `multi-day-run` capability 同位（都是 infrastructure-tier），
通过包根 `__init__.py` re-export 公共类型（RetryPolicy / HealthAudit /
HotfixSignalHandler / DayCheckpointWriter）。

### D3 · Per-day checkpoint 而非 per-tick

**选择**：checkpoint 粒度 = 1 simulation day（288 tick）。每天结束在
`on_day_end` hook 内同步落 `seed_{N}_day{D}.partial.json`。

**Why over alternatives**：

- **alt A · per-tick checkpoint**：每天 288 次 dump，I/O 占比过高（每次
  RunMetrics 序列化估 50-200ms × 288 × 14 = 4-15 min 额外开销 per seed），
  且单 tick 损失对实验信号几乎无影响。
- **alt B · per-N-tick (N=24, 每小时)**：粒度仍嫌细；增量复杂度（partial 内
  部还要 tick offset）。
- **alt C · 仅在 SIGUSR1 时 dump**：恶意路径——如果 SIGKILL（D1' 实际情况）
  根本不给 signal handler 机会，partial 永远不写。

**Trade-off**：日内死锁损失最多 24h 模拟时长（288 tick 数据）；对 14-day
实验 = 7% 数据丢失，可接受。如果未来需要 tick 级粒度，partial schema 预留
`last_tick_index` 字段允许后续扩展。

### D4 · SIGUSR1 而非 SIGTERM 作为 graceful-stop 信号

**选择**：worker 注册 SIGUSR1 handler → 跑完当前 tick → flush checkpoint →
`sys.exit(0)`。SIGTERM / SIGINT 保留 Python 默认（立即抛 KeyboardInterrupt），
SIGKILL 走 OS 路径强杀。

**Why over alternatives**：

- **alt A · 复用 SIGTERM**：`run_variant_suite.py` 的 coordinator 用
  ThreadPoolExecutor 跑 worker subprocess；coordinator 自己接 Ctrl-C 时 OS
  级 SIGTERM 给所有 child，行为已绑定。不能再赋予新语义。
- **alt B · 用文件 / socket 触发**：复杂；ops 体验差。
- **alt C · SIGUSR2**：等价；选 USR1 因为社区惯例（reload/checkpoint），
  USR2 留给未来"dump diagnostics"。

### D5 · 配置热重载粒度：环境变量 + 重启 worker

**选择**：所有可热改的参数（连接池 / 重试 / 熔断阈值）都从环境变量读，
`RESILIENCE_*` 前缀。改环境变量后 SIGUSR1 graceful-stop 当前 worker，
`--resume` 重启即生效。

**Why over alternatives**：

- **alt A · runtime reload（SIGHUP 触发 reread）**：worker 内部要维护
  "配置实例 vs 已构造的 httpx pool" 一致性；改连接池参数需要重建 pool；
  风险高、收益低（一次 graceful-stop + resume 不到 1 min）。
- **alt B · 配置文件 YAML**：增加新文件 + parser；环境变量已经够 D1 / D2 用，
  YAML 留给未来。

### D6 · Pre-flight smoke 的 agent 数：1000 而非渐进 100→500→1000

**选择**：preflight 直接跑 1000 agent × 1 day × 全 4 variant × 1 seed。

**Why over alternatives**：

- D1' 教训明确：scale-only bug 在 50/100/200 agent 全部触发不到，必须 1000
  才能复现连接池毒化路径。渐进式只浪费时间。
- 1 day × 1000 agent 估算 wall time：~15-20 min（基于 D1' baseline 每天 ~10
  min × 1.5 兼顾 keepalive=0 的 10-20% 减速）。在 publishable run 60-80h 头
  上加 20 min preflight 是 0.5% 成本，换 100% 死锁前置发现率。

**Why CLAUDE.md 强调 1000**：项目固定参数（不是 100；100 是 smoke 配置）。
preflight 名义上 = smoke，但参数 = publishable，目的就是用 publishable
配置探 scale-only bug。

### D7 · Multi-key 轮询扩展到 Gemini

**选择**：`GEMINI_API_KEYS`（逗号分隔）+ fallback `GEMINI_API_KEY` 单键，
逻辑与 DeepSeek 完全镜像。

**Why**：D1' 4 worker 抢同一 Gemini key 的 quota，毒化速度 4× 叠加。
multi-key 之外还有 per-key 熔断保护：单 key 连续 N 次失败短暂下线，避免
"一个 key 被服务端限流，全部 worker 卡这条路上"。

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| keepalive=0 让 D2 整体慢 10-20%，60-80h → 72-96h | 接受。比 D1' 100% 数据丢失好得多 |
| Pre-flight 20 min 浪费机器时间（如果 publishable 完全无故障） | 接受。20 min vs 72h 是 0.5% |
| Per-day checkpoint 把 14-day run 的磁盘占用乘 14 倍（最多 14 个 partial 同时存在） | 整 variant 完成后 partial 立即清除；最坏占用峰值 = 1 个 partial（约 5-50 MB），可接受 |
| SIGUSR1 在 ThreadPoolExecutor child 内可能被 wrapped——具体行为取决于 multiprocessing start method | `tools/run_variant_suite.py` 用 spawn / fork-server 时显式注册；test_run_resilience_hotfix.py 验证 |
| 多 key 轮询时若所有 key 同时被限流，熔断后所有路径都 half-open → 仍会拖慢 | 熔断仅保证不持续打死 key；服务端限流 = 等冷却 |
| 现有 D2 run 已在跑，不能中途切 keepalive=0 | 接受。D2 完成后切换；本 change 主要保护 D3 / 后续 publishable |
| Per-day checkpoint 包含 MemoryStore 序列化 — 1000 agent × 14 day 三层 memory 量级可能很大 | 序列化测试 → 监控单 partial 文件大小；若 > 200 MB 触发优化（仅 dump diff or 仅必要字段） |
| `RetryPolicy` 在 fatal 4xx 上立即抛可能让既有"transient 但报 4xx"的 provider 行为退化 | retryable / fatal 分类要在测试中精确覆盖；429 / 5xx 仍 retryable |

## Migration Plan

### Phase 1（本 change 实施期间，~2-3 day）

1. 写 `synthetic_socio_wind_tunnel/run_resilience/` 模块（retry / circuit /
   health / hotfix / checkpoint），测试覆盖
2. 改 `tier_llm_factory.py`：注入自定义 httpx client + 用 RetryPolicy +
   Gemini multi-key
3. 改 `orchestrator/multi_day.py`：on_day_end 写 partial + `resume_from`
   构造参数
4. 写 `tools/audit_run_health.py` + `tools/preflight_full_smoke.py`
5. 改 `tools/run_variant_suite.py`：`--resume` / `--resume-from-day` /
   `--skip-preflight` flag
6. 测试：1267 现有 test 0 回归 + 新增 ~30 test 100% pass
7. `openspec validate run-resilience --strict` 通过

### Phase 2（本 change archive 后立即）

1. **不影响 D2**：D2 还在跑，本 change 不动 D2 进程。D2 结束后才升级。
2. 跑 `tools/preflight_full_smoke.py` 一次，确认在新机器（已记录 D1' 故障
   的同 Mac）上 1000 agent × 1d × 全 variant 100% pass
3. 验证 graceful-stop：手动 SIGUSR1 一个 worker，观察 partial 落地 + exit 0
4. 用 partial 跑 `--resume`，确认从 day N+1 接得上、最终结果与从头跑等价

### Phase 3（D3 / 后续 publishable run）

1. 所有 publishable run 强制走新路径（preflight + checkpoint + resilient
   tier client）
2. `make fitness-audit` 新增 `phase2-gaps.run-resilience` 探针验证翻绿

### Rollback

- 若新 tier client 在某个 provider 上意外退化：环境变量 `RESILIENCE_DISABLE=1`
  让 `tier_llm_factory` 跳过新逻辑、走旧默认（仅 D2 那种已 in-flight 的
  应急逃生口；不该作为正常路径）
- 若 per-day checkpoint 写盘失败：`MultiDayRunner` SHALL 把异常 log 但继续跑
  完当天（不让 I/O 错误炸掉整个 run）

## Open Questions

1. **MemoryStore 序列化体积**：1000 agent × 14 day 三层 memory 量级未实测。
   若 partial > 200 MB → 需限定 dump 范围（如仅最近 7 天 memory）。**P1**
2. **Anthropic 直连路径的连接池实现**：当前 anthropic SDK 不直接暴露 httpx
   client；需要确认 monkey-patch 路径稳定（与 D1' Gemini 同类问题）。
   **P2**（D2 用 DeepSeek，D3 暂无 Anthropic 大尺度 plan）
3. **Pre-flight 失败时的细化诊断**：preflight 退出码 != 0 时如何把"哪个
   variant / 哪天 / 哪个 LLM call 卡死"快速定位给用户？目前打算依赖
   `tools/audit_run_health.py` 输出，但需要在 preflight 报错时显式调起。
   **P2**
4. **Checkpoint 与 `data/experiments/` 现有目录结构的对接**：`partial.json`
   放 variant 目录内还是单独 `checkpoints/` 子目录？倾向前者（方便 `--resume`
   定位），但需确认 `data/experiments/README.md` 的 tracking 规则不破。
   **P3**
