## Why

2026-05-20 全量项目扫发现 `tools/check_publishable_integrity.py` 第 42
行 `seed_file.glob("seed_*.json")` 太宽 —— 会 match 到非 seed 结果
文件：
- `seed_42_positions.json` (agent 轨迹位置数据)
- `seed_42_tick3984.snapshot.json` (resume snapshot)
- `seed_42.wal.jsonl`（不会被 `.json` 后缀匹配，但同目录）

这些文件被当作 seed result records 检查 → 23/25 false positive errors
被报告（reproducibility_lock 缺、replan_count 缺等），淹没真实有效的
错误信号。

实测：在 `data/experiments/20260518_003103_d2_beta4_seed42_20260518_0031`
跑 checker 得 **140 个错误**，其中只有少数是真问题，绝大多数来自
auxiliary files 被误当 seed records。

## What Changes

- 把 `seed_file.glob("seed_*.json")` 改为正则匹配 `seed_<N>.json`
  exactly（只数字 + `.json`），过滤掉：
  - `seed_*_positions.json`
  - `seed_*_tick*.snapshot.json`
  - `seed_*_day*.partial.json`
  - 任何其它 `seed_*` 前缀但有更多 suffix segment 的文件
- 加 1 个 unit test 验证 glob 排除 auxiliary files

NOT in scope:
- 不改 checker 检查逻辑本身（rep_lock / replan / encounter / traj_dev
  等 invariant 不动）
- 不改 seed result file schema

## Capabilities

无 capability 改动 — 纯 tool bugfix。

## Impact

**Affected code**:
- `tools/check_publishable_integrity.py::_load_seed_files`

**Affected behavior (positive)**:
- 现有 D2 run 跑 checker 从 140 errors → 真实 error 数（估 < 10）
- 信号 / 噪音比恢复，可以信赖 checker 结果

**Test impact**: 1 个新 unit test 验证文件名正则。
