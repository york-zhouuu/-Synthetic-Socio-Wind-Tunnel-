## MODIFIED Requirements

### Requirement: worker 必须有 RSS 阈值自重启机制

`MultiDayRunner` SHALL 在 `run_multi_day` 注册一个 on_tick_end hook (`_init_memory_management_hooks`)，在 hook 里：

- 当环境变量 `RSS_RESTART_MB > 0` 时，每
  `RSS_CHECK_EVERY_N_TICKS`（默认 50）tick 量一次 self RSS。**RSS 测量
  SHALL 是当前 RSS（current resident set size），不是 ru_maxrss
  生命周期峰值**。优先使用 `psutil.Process().memory_info().rss`；当
  psutil 不可用时 fallback to `resource.getrusage(RUSAGE_SELF).ru_maxrss`
  并 emit warning log line 说明此 fallback 行为可能误触发 cap
- 当当前 RSS > `RSS_RESTART_MB` MB 时，SHALL 设置
  `self._graceful_stop_requested = True`，让既有 graceful_stop 路径自然
  退出（写 partial + 退出 0）
- 当环境变量 `GC_EVERY_N_TICKS > 0`（默认 200）时，每 N tick 跑一次
  `gc.collect()` 并 log freed cycles

外部 launcher / LaunchAgent SHALL 在下次巡检 tick 看到 PID 不存在 +
有 snapshot/partial → spawn replacement（complement 的 constructive
recovery 行为）；effect 是每 worker RSS oscillates around threshold
而不是单调爬升。

`RSS_RESTART_MB=0`（默认 off）SHALL 完全禁用 RSS 监控，保持向后兼容。

**为什么必须用当前 RSS 不是 ru_maxrss**：`ru_maxrss` 是进程生命周期
RSS 峰值，单调非降；worker 一次 snapshot 反序列化峰值（实测 35GB）
之后，ru_maxrss 永远停在 35GB，即使 GC + malloc_relief 把当前 RSS 降
到 8GB，下次 RSS_CHECK 仍然 trip cap → graceful_stop → 重启 → 又
35GB → 永远循环。详见 `comprehensive-runtime-instrumentation`
2026-05-20 root cause analysis。

#### Scenario: RSS 超阈值触发 graceful_stop（当前 RSS）

- **WHEN** `RSS_RESTART_MB=100`、worker 当前 RSS 120 MB（psutil
  `memory_info().rss` 返回 120 × 1024 × 1024 bytes）
- **THEN** 下一次 RSS check tick SHALL 设 `_graceful_stop_requested=True`；
  worker SHALL 在当前 tick 末尾退出；写出 partial；退出码 0

#### Scenario: 峰值后当前 RSS 降下来不再 trip

- **GIVEN** worker peaked at RSS 35000 MB during snapshot deserialize，
  之后 GC + malloc_relief 把当前 RSS 降到 8000 MB；`RSS_RESTART_MB=10000`
- **WHEN** 下次 RSS check tick 触发
- **THEN** SHALL 用 psutil 读当前 RSS = 8000 MB；8000 < 10000 →
  `_graceful_stop_requested` 保持 False；worker 继续运行
- **THEN (对照 ru_maxrss bug)**: 若错误使用 `ru_maxrss`，会读到 35000
  → 错误触发 graceful_stop —— 这是修复前的 bug 行为

#### Scenario: 默认 off 不动行为

- **WHEN** `RSS_RESTART_MB` unset 或 == 0
- **THEN** worker SHALL 不发生 RSS-driven graceful stop；
  `_graceful_stop_requested` SHALL 永远是 False（除非外部 SIGUSR1）

#### Scenario: psutil 缺失 fallback 行为

- **GIVEN** Python 运行环境无 psutil（极少见，dev extras 缺失）
- **WHEN** RSS check 触发
- **THEN** SHALL fallback to `resource.getrusage(RUSAGE_SELF).ru_maxrss`；
  SHALL emit warning log line 包含 substring "psutil unavailable" 和
  "lifetime peak"；功能上 cap 仍生效但可能在 1 次峰值后永久 trip

#### Scenario: gc.collect 周期触发

- **WHEN** `GC_EVERY_N_TICKS=10`、worker 跑到 tick_global=20
- **THEN** `_init_memory_management_hooks` 注册的 hook SHALL 已经调用过
  `gc.collect()` 至少 2 次（tick 10、tick 20）
