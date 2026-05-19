# Fault matrix — 穷举式 coverage 视图

> 本文档 complements `docs/testing-philosophy.md`：
> - testing-philosophy.md 是 **内涵式**（8 条抽象原则）
> - 本文档是 **外延式**（具体故障枚举）
>
> 每次 PR review 时翻一遍这张表，问"我的改动让哪些 fault 行为变了？
> 对应 test 还在吗？"。

---

## 0. 怎么读

每一类 fault 是 7 大类之一（OS / Network / Disk / Time / Memory /
Process / Filesystem），每条 fault 给：

- **触发场景**：本项目什么时候可能遇到这个 fault
- **正确行为**：代码 SHALL 怎么响应
- **测试位置**：哪个 test 文件 enforce 这个行为
- **状态**：✅ 覆盖 / ⚠️ 部分覆盖 / ❌ 未覆盖（**TODO**）

未覆盖的条目应被视为"下个 OpenSpec change 候选"——不要拖到事故发生
才补。

---

## 1. OS / 信号 fault

| Fault | 触发 | 正确行为 | Test | 状态 |
|---|---|---|---|---|
| SIGUSR1 in setup phase | 外部 monitor 误判，或 RSS 阈值在 setup 期就被触发 | 不写假 final，写 `seed_N.aborted_in_setup.json` 哨兵 | `test_aborted_in_setup_sentinel.py` | ✅ |
| SIGUSR1 in tick loop (≥1 day completed) | RSS auto-restart / 人为运维 | 跑完当前 tick → 写 per-day partial → exit 0 | `test_hotfix_integration.py` | ✅ |
| SIGUSR1 在 day_end 之间 | 罕见 race | 同上，partial 还是有效 | 同上 | ⚠️ 间接覆盖 |
| SIGTERM | 容器 stop / kill | 立即退出（无 cleanup contract） | — | ⚠️ 未明确 spec |
| SIGKILL anywhere | OOM jetsam / kill -9 | snapshot 要么不存在要么完整 JSON | `test_atomic_no_partial_residue` | ✅ |
| SIGINT (Ctrl-C) | 人为运维 | 同 SIGTERM | — | ❌ 未覆盖 |
| SIGHUP | terminal close | 应忽略（已 start_new_session） | — | ❌ 未覆盖 |
| Host reboot mid-run | macOS auto-update / 断电 / panic | LaunchAgent 重启 → resume_publishable spawn → resume from snapshot | partial：`resume_publishable` 单元 test 在，e2e reboot test ❌ | ⚠️ |
| 子进程被父进程 reap 卡住 | 父进程 hang 不 wait | 应 detached + start_new_session | source-level `start_new_session=True` 已用，无 test enforce | ⚠️ |

## 2. Network / LLM fault

| Fault | 触发 | 正确行为 | Test | 状态 |
|---|---|---|---|---|
| LLM call timeout (read_timeout) | 模型慢 / 网络抖 | asyncio.wait_for 兜底 → fallback | `test_direct_llm_timeout_guard.py` | ✅ |
| LLM 429 rate limit | 并发太高 | RetryPolicy backoff retry | `test_retry_policy.py` | ✅ |
| LLM 4xx (400/401/403) | 配置错 | 立即抛，不 retry | `test_retry_policy.py` | ✅ |
| LLM 5xx | 服务端故障 | retry with backoff | `test_retry_policy.py` | ✅ |
| TCP RST / ConnectionReset | 半开连接 | retry | `test_retry_policy.py` | ✅ |
| SSL handshake hang | 罕见 cloud 故障 | wait_for 兜底（httpx timeout 失效） | `test_direct_llm_timeout_guard.py` | ✅ |
| 整 provider 全挂（all keys open） | 火山 + DS + Gemini 同时崩 | AllKeysOpenError 传播；不在 fallback | `test_circuit_breaker_all_open.py` | ✅ |
| CLOSE_WAIT 累积 | D1' 教训 | `max_keepalive_connections=0` | source-level 已加；test ❌ | ⚠️ |
| DNS fail | 罕见 | 视为 ConnectionError，retry | 间接 | ⚠️ |

## 3. Disk fault

| Fault | 触发 | 正确行为 | Test | 状态 |
|---|---|---|---|---|
| 磁盘满 | snapshot 大 + 长跑 | write_atomic 抛 OSError；既有数据不损坏 | — | ❌ 未覆盖 |
| 写一半 crash | SIGKILL / power | atomic rename catches | `test_atomic_no_partial_residue` | ✅ |
| 并发 write_atomic 同 path | double-spawn | tempfile.mkstemp 唯一名 | `test_concurrent_writes_no_corruption` | ✅ |
| fsync 失败（tmpfs / sshfs） | 罕见 FS | swallow + continue（已 try/except OSError） | source-level 已处理；test ❌ | ⚠️ |
| 读 corrupted JSON | 磁盘 bit-rot | IncompatibleCheckpointError | `test_read_incompatible_schema_raises` | ✅ |
| inode 耗尽 | 大量小 file | 视为 OSError | — | ❌ 未覆盖 |
| 文件 mtime 异常（早于 epoch） | 文件系统损坏 | in_setup 检测优雅降级 | 间接 by `test_harden_invariants.py` | ⚠️ |

## 4. Time / 时钟 fault

| Fault | 触发 | 正确行为 | Test | 状态 |
|---|---|---|---|---|
| 时钟跳跃（NTP correction） | 长跑 | staleness 检测**不**因负数 age 误判 | — | ❌ 未覆盖 |
| DST transition | 14 day 跨 DST | simulated_time 用 datetime 不受影响（已 verify？） | — | ❌ 未覆盖 |
| 时区不一致 | 跨机器 resume | snapshot 用 UTC isoformat | source 已用 datetime.utcnow；test ❌ | ⚠️ |
| simulated_time 与 wall-clock 错位 | 长跑误差 | 系统不依赖 wall-clock，只依赖 ticks | 间接 | ⚠️ |
| process start time 在 mtime 之后 | 双胞胎 spawn | in_setup 检测 | `test_harden_invariants.py` | ✅ |

## 5. Memory fault

| Fault | 触发 | 正确行为 | Test | 状态 |
|---|---|---|---|---|
| RSS 超阈值 | 长跑累积 | _graceful_stop_requested = True → exit | `test_harden_invariants.py::test_rss_threshold_triggers_graceful_stop` | ✅ |
| RSS 超阈值但 in setup | 极端 case | TODO：不该自杀（无 partial 可写）；现在会自杀写假 final | — | ❌ 未覆盖（gap） |
| OOM jetsam | swap 满 / 物理 RAM 满 | 进程死 → snapshot 完整 → LaunchAgent resume | 间接 | ⚠️ |
| 单 worker resume RAM peak 不可控 | publishable scale snapshot | TODO: budget test | — | ❌ **TODO** |
| N worker 并发 resume 撞 RAM | 同时 spawn | TODO: budget test + 强制 staggered spawn | — | ❌ **TODO** |
| 数据结构无界增长 | 14 day 长跑 DialogueService / Memory | rolling cleanup | `test_dialogue_service_eviction.py`（单步）；长跑 bounded ❌ | ⚠️ |

## 6. Process / 进程 fault

| Fault | 触发 | 正确行为 | Test | 状态 |
|---|---|---|---|---|
| Double-spawn 同 cell | watchdog 误判 PID 死 | 两 worker 互不损坏数据（atomic write + WAL append-only） | `test_concurrent_writes_no_corruption` | ⚠️（atomic 测了，但**业务逻辑**层多 worker 写同 WAL 没测） |
| Zombie 进程 | 父进程不 wait | start_new_session detach | source 已用；test ❌ | ⚠️ |
| Orphan 进程 | 父进程死 | 由 init 接管，继续跑直到完成 | 间接 | ⚠️ |
| ps 命令本身 timeout | 高 I/O load | `_find_alive_worker` 视为 None；调用方**不**应据此 spawn | — | ❌ **TODO** (本次事故诱因) |
| pgrep / lsof 返垃圾 | 罕见 OS bug | parse 失败 → log + skip | — | ❌ 未覆盖 |
| LaunchAgent crash | macOS bug | 自动 respawn (KeepAlive=true) | 配置层；test ❌ | ⚠️ |

## 7. Filesystem fault

| Fault | 触发 | 正确行为 | Test | 状态 |
|---|---|---|---|---|
| 路径不存在 | output_dir 拼错 | mkdir(parents=True, exist_ok=True) | 源码已加 | ⚠️ |
| 权限不足 | sudo 跑后留下的 file | OSError，明确 log | — | ❌ 未覆盖 |
| Case-sensitivity 不一致（APFS vs ext4） | 跨机器 | seed_42 vs Seed_42 不冲突 | — | ❌ 未覆盖 |
| symlink loop | 罕见用户配置 | 视为 OSError | — | ❌ 未覆盖 |
| 网络 FS (NFS / SMB) atomic rename 语义 | 共享存储跑 publishable | 不保证 → 应禁用 / warning | — | ❌ 未覆盖 |
| 文件被外部进程持有（lsof 占用） | 用户开 editor 看 partial | 应 sleep/retry rename | — | ❌ 未覆盖 |

---

## 8. Coverage 汇总

按 fault 大类统计：

| 类 | ✅ 全覆盖 | ⚠️ 部分覆盖 | ❌ 未覆盖 | 总数 |
|---|---|---|---|---|
| OS / 信号 | 3 | 4 | 2 | 9 |
| Network / LLM | 7 | 2 | 0 | 9 |
| Disk | 3 | 2 | 2 | 7 |
| Time / 时钟 | 1 | 2 | 2 | 5 |
| Memory | 1 | 2 | 3 | 6 |
| Process | 0 | 4 | 2 | 6 |
| Filesystem | 0 | 1 | 5 | 6 |
| **合计** | **15** | **17** | **16** | **48** |

**31% 全覆盖；33% 未覆盖**。

注意：本次 `harden-worker-resilience` 修了**今天踩过的 7 个 bug**，把
某些 fault 从 ❌ 提到 ✅。剩下的 16 个 ❌ 是**还没踩但有可能踩**的雷。
按事故概率 × 损失粗排：

### 高优补 test 候选（top 5 — 下一个 OpenSpec change 候选）

1. **ps 命令超时 / 失败路径 mock**（process #4）— 今天已踩过的诱因，
   只缺测试 enforce
2. **磁盘满 + write_atomic**（disk #1）— 任意长跑都可能踩
3. **N worker 并发 resume RAM budget**（memory #4/5）— 今天另一个
   诱因，无 publishable-scale fixture 测过
4. **数据结构长跑 bounded 测试**（memory #6）— DialogueService /
   MemoryStore 各一个
5. **时钟跳跃**（time #1）— 长跑必踩

### 中优

6. SIGINT / Ctrl-C 退出语义
7. CLOSE_WAIT 累积 enforce test
8. 跨机器 resume 时区一致性

---

## 9. 怎么用这张 matrix

### 9.1 PR review 时

每个 PR 在描述里**显式标注**：

```
## Fault matrix delta
新增 / 改动行为：
- [+] OS #5 SIGKILL 期间 atomic write — 状态 ✅ → ✅（保持）
- [+] Memory #1 RSS 超阈值 — 状态 ❌ → ✅（新加 test）
回退检查：
- [-] 无回退
```

### 9.2 写新 capability 时

当 capability 涉及任一 fault 类别（IO / 资源 / 信号 / 多进程），spec
必须包含至少 2 个 Scenario 显式响应该 fault 类的"高优"条目（看
matrix 9 节）。

### 9.3 季度审计

每季度过一遍 matrix，更新状态（事故发生后 ❌ → ✅）+ 添加上季度
新发现的 fault 条目。

---

## 附录：本项目特有 fault（不属 7 大通用类）

| Fault | 描述 | 测试 |
|---|---|---|
| LLM provider 路由切换中 | aitown wiring 同时 routing 改变 | ❌ |
| Variant target_location 失效 | atlas 数据更新但 push 还用旧 ID | ⚠️ |
| social_priors 与 setup_cache schema drift | prewarm 老 cache 喂新 sim | ⚠️ via schema_version 检测 |
| WAL schema 升级 | 长跑跨 version | ⚠️ via schema_version |
| Doubao / DeepSeek token quota 耗尽 | 长跑超 budget | ❌ |
