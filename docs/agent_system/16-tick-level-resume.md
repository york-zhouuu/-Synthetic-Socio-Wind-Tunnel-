# 16 · 真出问题：从最后一 tick 接着跑（tick-level-resume）

> **白话名**：跑挂了不用重头来
>
> **技术名**：tick-level-resume（2026-05-16；run-resilience 的上位升级）

## 是什么

publishable run 在 1000 agent × 14 day × DeepSeek 配置下要跑 60-80 小时。
中间任意时刻——电脑断电、SIGKILL、OOM、宇宙射线——都不应该把 14 天积累
的状态全部送给宇宙。我们希望：**任何中断，都能接着上次最后一个 tick
跑下去**。

之前的 run-resilience（2026-05-15）已经做了 per-day partial 写盘和
`--resume`，但有两个未关上的口子：

1. `--resume` 实际并不"复原"中断时的 in-memory 状态——它只是跳过前面
   几天从干净状态重新跑。day 5 起跑时的 ledger / agent 位置 / memory，
   和原本 day 4 结束时的状态**不一样**。
2. 粒度只到天。SIGKILL 在 day 5 tick 100 → 当天的 100 个 tick 数据全丢，
   `--resume` 只能从 day 6 起。

本模块把这两点都补齐：

- **per-tick WAL**：每个 tick 末写一行 `seed_42.wal.jsonl`（~100 B）。
  独立诊断信号：随时 `tail -f` 知道跑到哪了。
- **per-N-tick snapshot**：每 N tick（默认 N=24 = 1 小时 simulated time）
  写一份完整 in-memory state 到
  `seed_42_tick{T}.snapshot.json`。滚动保留最近 K=2 个。
- **真实 restore**：`SimulationCheckpoint.restore_into(...)` 把 ledger /
  agents / memory / attention 四个子系统的 state 灌回 in-memory 对象。
- **graceful-stop 写 final snapshot**：SIGUSR1 收到后，无论是否 N 整数倍，
  都强写一份当前 state 给 resume。
- **`--resume-strategy`**：4 个值控制 resume 行为（snapshot 优先 / 仅
  snapshot / 仅 partial / 重头跑）。
- **`suspected_stuck` 探活维度**：`audit_run_health.py` 根据 WAL 最近一行
  的 mtime 距离 now 判定 worker 是不是卡死了。

**技术注脚**：核心模块
`synthetic_socio_wind_tunnel/run_resilience/state_snapshot.py` 暴露
`SimulationCheckpoint`（Pydantic frozen）+ `SnapshotPolicy`（频率与保留
策略）+ `WALWriter` + RNG capture/restore helper + 各子系统的
`to_snapshot_state` / `from_snapshot_state` 双向接口。

## 解决什么问题

> "我前面跑了 60 小时，最后 2 小时电脑死机了，我能不能不要从头来？"

> "上次我 SIGKILL 之后 `--resume`，跑出来的数据跟跑完整 14 天的不一样——
> 是不是因为状态没恢复对？"

> "我想知道现在跑到 tick 几了，但 worker 日志里看不出来，能不能有个
> 简单的进度条？"

## 意义

| 失效场景 | run-resilience 之前 | run-resilience（per-day） | tick-level-resume（per-N-tick） |
|---|---|---|---|
| Worker 死锁 | 7 小时无人觉察 | `audit_run_health.py` 报警 + SIGUSR1 救出 | 同 + WAL 实时进度可视化 |
| SIGKILL 在 day 5 tick 100 | 5 天数据全丢 | day 5 全天数据丢（~5h wall） | 最多丢 N-1 个 tick（~10 min wall） |
| `--resume` 的 state 正确性 | N/A | day 起点 state 是 day 0 fresh（**前后不接缝**） | 真正从 snapshot 时刻还原（**无 seam**） |
| 改配置后接着跑 | 重头 | 改 env + `--resume` 从 day+1 起 | 改 env + `--resume-strategy=snapshot-only` 从最近 snapshot 接 |
| 进度可见性 | log 看 | log 看 | `tail -f seed_42.wal.jsonl` |

## 用法速记

```bash
# 1. 默认就开启了（snapshot_every_ticks=24, K=2, wal_enabled=True）
python tools/run_variant_suite.py \
  --variants baseline,hyperlocal_push,global_distraction,phone_friction \
  --seeds 15 --agents 1000 --num-days 14 \
  --mode publishable --use-aitown --aitown-provider deepseek \
  --num-protagonists 500 --workers 4 \
  --suite-name d3_deepseek_with_snapshots

# 2. 实时看 worker 进度
tail -f data/experiments/<run>/variant_baseline/seed_42.wal.jsonl

# 3. 巡检（含 suspected_stuck 维度）
python tools/audit_run_health.py data/experiments/<run>/

# 4. 卡了？SIGUSR1 优雅停 → final snapshot 落盘 → 改 env → 续跑
kill -USR1 <worker_pid>
export RESILIENCE_RETRY_MAX_ATTEMPTS=5
python tools/run_variant_suite.py --suite-dir <run> \
  --resume-strategy snapshot-only ...

# 5. 完全重头跑（罕见，用于强制清干净）
python tools/run_variant_suite.py --suite-dir <run> \
  --resume-strategy none ...
```

## 4 个 resume-strategy 选哪个

| strategy | 行为 | 用于 |
|---|---|---|
| `auto`（默认） | 优先用 snapshot；找不到 fallback 到 per-day partial；都没有 → day 0 | 99% 场景 |
| `snapshot-only` | 强制 snapshot；找不到 → fail-fast 退出 | 中断后想严格继续；不接受 per-day fallback 的 seam |
| `partial-only` | 忽略 snapshot，按 run-resilience 旧路径走 | 调试 / 对比；publishable 不推荐 |
| `none` | 重头跑 day 0 | 想完全干净的对照实验 |

## "Replay-drift" 折扣声明

snapshot 落盘是**精确 state 还原**——只要 snapshot 是有效的，restore 后
的状态严格等于 snapshot 时刻的状态。

但 snapshot 之间**还没落盘**的 tick（最多 `every_ticks - 1` 个）会丢。
我们**接受**这部分损失为已知折扣，因为：

- LLM 路径不可严格重现（即便 temperature=0 也有 ~0.1% drift），所以
  replay 这部分 tick 跟 "重做" 没区别
- 默认 N=24 ≈ 2 小时 simulated time / ~10 min wall time。比之前丢 1 整天
  小**两个数量级**

如果用户要更严格："就丢 1 个 tick"：`RESILIENCE_SNAPSHOT_EVERY_TICKS=1`
（per-tick snapshot；体积大、写盘 overhead 高，但断电只丢 5 min simulated
time）。

## 4 个子系统的 to/from snapshot 接入

| 子系统 | 序列化策略 |
|---|---|
| `Ledger` | `_data.model_dump(mode="json")` — Pydantic 全 dump |
| `AgentRuntime` | 仅 mutable 字段（plan / location / movement / mood / hint / ai-town state / 每 agent invite_rng）；**不**含 profile / service refs / in-flight LLM ops |
| `MemoryService` | per-agent MemoryStore.events list（reverse indices 是 derived，restore 时 rebuild）+ per-agent counters + service RNG |
| `AttentionService` | profiles / feed_index / delivery_log / consumed / phone_attention 全 dump + RNG |
| `Atlas` | **不**接入（只读、不变；Atlas 加载从 atlas.json 走） |
| `OperationPool` | **不**接入（pending ops abandon-and-retry；resume 后 agent 重新触发） |

新增子系统的 mutable state 字段时，**必须**更新对应 `to_snapshot_state` /
`from_snapshot_state` 方法，并补 round-trip 测试。

## 故事化背景

run-resilience（2026-05-15）解决了"Gemini 连接池死锁导致 72h 全损"这一类
急性故障。但用户在它 archive 之后立刻指出：

> "如果真的中断了，可以沿着最后一次提交的内容可以继续跑下去。"

仔细看 run-resilience 的 `MultiDayRunner.resume_from=5` 实现——它只是
把循环起点跳到 day 5，**没有**把 partial JSON 里的 ledger / memory /
attention state 灌回 in-memory 对象。day 5 的起跑状态实际上跟 day 0 一样
是从 atlas 重新构造的 fresh state，根本不是 "day 4 结束时" 的状态。

也就是说之前的 `--resume` 是"状态半残"的——前后数据拼起来有 seam，
对依赖 cross-day carryover 的实验信号（memory 长期累积、attention 衰减
state、agent 位置长期演化）造成系统性偏差。

本 change 把这个修对：完整的 state snapshot + 完整的 restore_into +
per-N-tick 粒度（默认 1 小时 simulated time / ~10 min wall）。

## 参考文档

- [`openspec/specs/tick-level-resume/spec.md`](../../openspec/specs/tick-level-resume/spec.md) — 正式契约
- [`openspec/changes/tick-level-resume/`](../../openspec/changes/tick-level-resume/) — 设计 + 任务
- [`docs/agent_system/15-run-resilience.md`](15-run-resilience.md) — 前置层（per-day checkpoint + SIGUSR1 + preflight）
