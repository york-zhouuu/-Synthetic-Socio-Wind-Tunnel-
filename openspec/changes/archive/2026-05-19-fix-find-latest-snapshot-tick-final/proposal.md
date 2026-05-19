## Why

2026-05-20 实测 publishable resume 暴露 `find_latest_snapshot` 静默
忽略 `tick_final.snapshot.json` 文件 — 而这正是 graceful_stop 时写的
**最权威最新状态**。

`run_resilience/state_snapshot.py::find_latest_snapshot` 用 `int(stem)`
解析文件名 tick number：
```python
stem = p.name[len(prefix):-len(suffix)]  # "_final" for tick_final
candidates.append((int(stem), p))         # ValueError → caught by silent skip
```

后果链：
1. Worker 跑到 day 12 触发 graceful_stop (mac 重启 / RSS cap / SIGUSR1)
2. graceful_stop 写一个 `seed_42_tick_final.snapshot.json` (最完整)
3. Auto resume_strategy 调 find_latest_snapshot → silent skip tick_final
4. 找到的最新 numeric tick snapshot 可能是 day 11 的 (旧 5.6GB 的)
5. Resume 从 day 11 重跑 day 12-13 — **浪费 2 day × 1000 agent × LLM cost**

实测今天 spawn 选了 5.6GB 旧 tick3444 snapshot 而忽略 lean 420MB
`tick_final`。手动 `mv` 老 snapshot 后 spawn 才用对 tick_final，
peak RAM 从 35GB → 1GB。

## What Changes

- `find_latest_snapshot` 改：
  - 优先选 `tick_final.snapshot.json` 如果存在（graceful_stop 写的，
    最权威）
  - 否则 fallback 到最高 numeric tick snapshot
  - 用 mtime 在两者之间裁判（如果 tick_final 比所有 numeric 旧，
    那是 stale tick_final，仍 fallback numeric）
- 新加 unit test 验证：
  - 有 tick_final + 旧 numeric → 选 tick_final
  - 只有 numeric → 选 highest numeric
  - tick_final mtime 早于 numeric → 选 numeric (stale tick_final)
  - 只有 tick_final → 选 tick_final

NOT in scope:
- 不改 snapshot 文件命名格式
- 不改 graceful_stop 写 tick_final 的行为
- 不改 prune_snapshots（既有 keep=K 行为保持）

## Capabilities

### Modified Capabilities

- `tick-level-resume`: `find_latest_snapshot` SHALL include tick_final
  in candidate list, prefer it when present + mtime is most recent
  (`tick_final` 是 graceful_stop 时刻最权威 state)。

## Impact

**Affected code**:
- `synthetic_socio_wind_tunnel/run_resilience/state_snapshot.py::find_latest_snapshot`

**Affected behavior (positive)**:
- Auto resume 选对 snapshot — graceful_stop 后下次 resume 不再回退
- 实测案例：peak RSS 35GB → 3-5GB (lean snapshot loads light)
- LLM cost 节省：每次 resume 不再重跑 1-2 day

**Affected behavior (negative)**:
- 行为 surprise 给读者：之前明确认为"resume 选最新 numeric"，现在
  可能选 tick_final。但语义上更对（tick_final 字面意思就是最终）。

**Test impact**: 4 个新 unit test + 1 e2e integration (resume after
graceful_stop 跑到 tick_final 写一遍 + 重启 verify 选对)。
