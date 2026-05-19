## Context

5/19 D2 attempt 6 雪崩暴露了 worker 长跑 + 信号中断 + 资源争抢三轴交叉
下的多个隐性失败路径。已紧急修了 3 处（CLAUDE.md 不变量
`monitor-as-control-plane` / `sigusr1-graceful-stop-corruption` /
`memory-auto-restart`），但这些以"运维补丁"形式落地，没进 spec、没被
回归测试覆盖、新代码改动容易回退。同时 backlog 还有 1.9（直接 LLM call
缺 wait_for）+ 1.11（resume 丢 run_metrics）两条同主题的高 ROI 项目
没做。

技术栈约束：`asyncio` 单线程事件循环；macOS 单机 48GB RAM；4 worker
并发；snapshot per-tick 体量 1.7–3.5 GB。

利益相关方：跑 publishable run 的人（不希望凌晨被 push notify）、复用
本项目代码的下游研究者（不希望踩同样的雷）。

## Goals / Non-Goals

**Goals:**
- 把今天三条 CLAUDE.md 不变量 + 两条 backlog item + 三条新发现的高/中危
  bug 一次性形式化进 spec
- 每条新 requirement 至少 1 个 scenario（即 1 个测试）
- 所有改动**向后兼容**——已有 snapshot / partial / seed_N.json 仍能
  正常被新代码读 + resume
- 不动 SIGUSR1 协议本身（"set flag, exit after current tick"），只在
  setup-phase 加哨兵守护

**Non-Goals:**
- 不引入新 capability / 新 spec 文件夹——所有 deltas 进既有
  `run-resilience` + `tick-level-resume`
- 不做 backlog 1.7 的 A/C/D/E（mmap atlas / cold prune / fork / slots）
- 不做 backlog 1.8（baseline-prefix-share）/ 1.12（dialogue persistence）/
  1.13（fallback budget）/ 1.14（多核）
- 不重写 OperationPool 路径——模式 A 已经有 wait_for 兜底
- 不实现 dialogue 持久化到磁盘（只做内存 evict + summary 保留）

## Decisions

### 决策 1：直接 LLM call 用 `asyncio.wait_for` wrap，不重构架构

**选项 A（采纳）**：每个调用点手工 wrap `asyncio.wait_for(..., timeout=60s)`
+ 本地 try/except → fallback。
**选项 B**：把所有 LLM call 强制经过一个 `bounded_llm_call(client, ...,
timeout)` decorator 或 mixin。
**选项 C**：把所有调用迁到 OperationPool（已 wait_for 包裹）。

选 A 因为：5 个调用点，改动量 < 150 行；不引入新抽象；fallback 路径
本来就是 per-call 不同的（reflect 返空摘要、importance 返 0.5、
life_history 返空 list），强行 decorator 反而复杂。B 是 backlog 1.9
注释里提到的"更彻底方向"，留作未来扩展点（下次再有 3+ 类似 bug 时
再做）。C 涉及大量 setup 期调用，不适合走 OperationPool。

### 决策 2：snapshot atomic write 用 `tempfile.NamedTemporaryFile`

**选项 A（采纳）**：`tempfile.NamedTemporaryFile(dir=path.parent,
prefix=path.name+".", suffix=".tmp", delete=False)`——OS 保证名字唯一。
**选项 B**：手写 `f"{path}.{uuid.uuid4().hex}.tmp"`。
**选项 C**：用文件锁（`fcntl.flock`）串行化 write_atomic。

选 A 因为：标准库、跨平台、保证唯一名、O(1) 即得。B 等价但不如标准库
经过更多 review。C 太重——snapshot write 本来就 IO-bound 几秒钟，加锁
让多 worker 串行写会大幅拖慢。多 worker 并发写**不同** snapshot path
是 OK 的（路径不同就不冲突），只有"双胞胎 spawn 写同一 path"这个边角
案例才需要保护——A 已足够。

### 决策 3：SIGUSR1 setup-phase 写 `.aborted_in_setup.json` 哨兵

**选项 A（采纳）**：哨兵文件 `seed_N.aborted_in_setup.json`（JSON 含
seed/aborted_at/reason）。
**选项 B**：在已有 `seed_N.json` 加 metadata field `aborted_in_setup=True`。
**选项 C**：完全不写文件，只 log 然后退出。

选 A 因为：外部 audit / resume_publishable 只看文件名就能判断状态，
不必读 JSON；哨兵名清楚区分 "aborted in setup" vs "naturally INTERRUPTED"。
B 会跟 `seed_N.json` 的"DONE 标记"语义混淆（audit 看到 seed_N.json 存在
会判 DONE）。C 缺乏外部可观测性，audit 无法区分"从未启动"vs"setup 期挂了"。

哨兵的清理由下次 fresh resume 时检测到 + 删除（resume 启动后第一个
tick 之前 unlink），不留 dangling。

### 决策 4：DialogueService rolling cleanup 在 day_end，不在 dialogue.end()

**选项 A（采纳）**：在 `on_day_end` hook 批量 evict ≥ 2 simulated-day 前
结束的 dialogue。
**选项 B**：在 dialogue `_end()` 时立刻把它 demote 到 summary。
**选项 C**：用 LRU cache 限制 `_dialogues` size（如 max 1000）。

选 A 因为：批量 evict 比 per-dialogue cleanup CPU 开销低（一次 dict
comprehension vs N 次散点修改）；2 day grace window 给"刚结束想再
retrieve full content"的场景留余地（如 metric 计算可能延后到 day_end
跑）；day boundary 跟 snapshot/partial write 的频率对齐。B 会让短对话
（开始结束在同一 tick）瞬间被 demote，破坏可观测性。C 不能区分新对话和
长尾对话——可能 evict 掉刚开始的 in-progress dialogue。

### 决策 5：snapshot run_metrics_state schema version bump "1" → "2"

**选项 A（采纳）**：schema_version "2"，新增 `run_metrics_state` 字段；
read 时 "1" 自动设 `run_metrics_state={}` + log warning。
**选项 B**：保持 "1"，新增字段时 read 时 default `{}`。
**选项 C**：完全 backward-incompatible bump "2"，拒读 "1"。

选 A 因为：明确版本号易诊断；warning 提示研究者老 snapshot resume 后
metric 不全；不强制现有跑里 snapshot 重做（即今天还没清的 12:08 snapshot
仍可用，只是 resume 后前段 metric 缺失，但 worker 本身能跑）。B 不
明显是 schema 演进。C 太严，会让今天残留的 snapshot 完全废掉。

## Risks / Trade-offs

- **[Risk] `tempfile.NamedTemporaryFile` 在 path.parent 没写权限会抛**
  → 既有 `write_atomic` 一直要求 parent 可写；不会引入新失败模式。
  Mitigation：测试覆盖 parent unwritable case，期望抛 PermissionError
  并附带可读消息。

- **[Risk] DialogueService evict 后下游 metric 计算找不到 full
  messages 抛 KeyError** → 调研下游：`metrics/encounter_metrics.py` /
  `metrics/dwell.py` 等只用 dialogue_id + participant + timestamp，不
  访问 messages；narrative 输出（backlog 1.12）才需要 full messages，
  那条路径未实施。Mitigation：spec scenario 覆盖
  `retrieve_summary` 返回非 None；evict 前先扫一遍 metric 模块确认
  没引用 `Dialogue.messages`。

- **[Risk] run_metrics_state 体量增长让 snapshot 更大** → 14 day ×
  per_day_summaries (~100 KB) ≈ 1.4 MB，可忽略相对 1.7 GB snapshot。

- **[Risk] LLM wait_for fallback 让 fallback 数据混入 publishable**
  → fallback 已经存在（do_something fallback 当 LLM call 失败时
  agent 用默认 action）；新加的 wait_for 只是把"挂死"路径转成
  "fallback"路径，没新增 fallback 数据源。Mitigation：metric 端
  已有 fallback_rate budget（backlog 1.13，预备 capability 1.13），
  fallback 率超阈值会标 inconclusive。

- **[Trade-off] `.aborted_in_setup.json` 哨兵需要 audit / resume 工具
  一起改** → 一次性改 3 个工具（`audit_run_health.py` /
  `resume_publishable.py` / `watchdog_wal_deadlock.py`）识别该哨兵；
  tasks.md 拆为独立 task。

## Migration Plan

**步骤**：
1. 实现 snapshot atomic write 多进程安全（决策 2）+ 测试 → 不破坏
   既有 snapshot（仅改 tmp 命名）
2. 实现 SIGUSR1 setup-phase 哨兵（决策 3）+ 测试 + 更新 audit / resume
   工具识别哨兵
3. 实现 DialogueService rolling evict（决策 4）+ 测试
4. 加 LLM wait_for wrap（决策 1，5 个调用点）+ 测试
5. snapshot schema v2 + run_metrics_state（决策 5）+ TickMetricsRecorder
   round-trip 测试 + resume 等价性测试
6. 跑全量 pytest 回归
7. 更新 backlog.md 标 1.9 + 1.11 已实施；更新 CLAUDE.md（不变量
   formalized + spec 引用）

**回滚**：每个决策独立 commit，可单独 revert。snapshot schema v2 通过
auto-default `run_metrics_state={}` 兼容 v1 文件，不需 migration script。

## Open Questions

- 决策 4 的 "2 day grace window" 是否够？需不需要 configurable？
  默认 2 够用；如果将来有 metric 需要更长 history retention，加 env
  `DIALOGUE_EVICT_AFTER_DAYS` 配置点（不阻塞 ship）。
- 决策 1 fallback 路径是否需要标记 metric 端"这个 tick 的某个
  agent 走了 fallback"？已经有 `get_tracker().check_budget()` 在
  fallback-rate budget capability 里处理（per-call site reporter），
  本 change 不动 metric reporter，只确保 fallback 触发时调一次
  `record_fallback(call_site, agent_id)`。
