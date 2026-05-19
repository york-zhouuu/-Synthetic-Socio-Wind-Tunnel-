## ADDED Requirements

### Requirement: publishable mode 必须默认 enable RSS hard cap

`tools/run_variant_suite.py` SHALL 在 `--mode publishable` 时检测环境
变量 `RSS_RESTART_MB`：未显式设置或值为 `0` 时 SHALL 自动 set 为
`10000` (10 GB)。

dev mode 不强制（保持默认 0 = 不启用），允许 dev 临时实验不被打断。

env override 仍然生效：`RSS_RESTART_MB=20000` 显式设可拉高，
`RSS_RESTART_MB=0` 可在 publishable 关闭（仅 advanced 场景）。

#### Scenario: publishable 自动设 10000
- **WHEN** 跑 `python tools/run_variant_suite.py --mode publishable ...`
  且 env RSS_RESTART_MB 未设
- **THEN** worker subprocess SHALL 启动时看到 `RSS_RESTART_MB=10000`；
  MultiDayRunner._init_memory_management_hooks SHALL 注册 RSS check
  hook（既有逻辑）

#### Scenario: publishable 但用户显式 override
- **WHEN** 跑 `RSS_RESTART_MB=5000 python ... --mode publishable`
- **THEN** worker SHALL 看到 `RSS_RESTART_MB=5000`（用户值优先）

#### Scenario: dev mode 不强制
- **WHEN** 跑 `--mode dev` 且 env 未设
- **THEN** worker SHALL 看到 `RSS_RESTART_MB=0`（or unset）；不撞顶

### Requirement: gc.collect() 后必须调 malloc_zone_pressure_relief

`MultiDayRunner._init_memory_management_hooks` SHALL 在 `gc.collect()`
之后立即调用 platform-specific malloc pressure relief：

- macOS: `ctypes.CDLL("libc.dylib").malloc_zone_pressure_relief(None, 0)`
- Linux: `ctypes.CDLL("libc.so.6").malloc_trim(0)` (TODO follow-up;
  非阻塞，本 change macOS 优先)
- Windows / 其它: skip silently

任何 ctypes call 失败 SHALL 包 try/except：第一次失败时 log warning，
后续 silent skip（避免每 200 tick 一次 warning 刷屏）。

#### Scenario: macOS 调用成功
- **WHEN** 跑在 macOS 且 GC_EVERY_N_TICKS=10 时跑到 tick_global=10
- **THEN** gc.collect 后立刻 malloc_zone_pressure_relief 被调；no exception

#### Scenario: ctypes 调用失败 fallback
- **WHEN** mock ctypes.CDLL raise OSError
- **THEN** run SHALL NOT crash；log warning 一次；后续 tick 静默 skip

#### Scenario: 非 macOS 平台 skip silently
- **WHEN** sys.platform == "linux" 且 malloc_trim 不可用
- **THEN** SHALL fallback warn 一次；不抛
