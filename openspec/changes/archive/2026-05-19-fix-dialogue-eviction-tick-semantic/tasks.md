## 1. 改 Dialogue dataclass

- [x] 1.1 加 `started_day_index: int = 0` + `ended_day_index: int | None = None`

## 2. 改 evict_old_dialogues signature + filter

- [x] 2.1 `before_tick` → `before_day_index`
- [x] 2.2 filter: `d.started_day_index < before_day_index`
- [x] 2.3 log msg 同步更新

## 3. 改 caller multi_day.py

- [x] 3.1 day_end hook 传 `before_day_index = max(0, day - grace)`

## 4. 既有 test 更新

- [x] 4.1 `_make_dialogue` / `_inject_dialogue` 设 `started_day_index`
- [x] 4.2 call sites `before_tick=` → `before_day_index=`
- [x] 4.3 property test invariants 重写为 started_day_index 语义

## 5. Regression

- [x] 5.1 跑既有 dialogue tests → 全绿（13/13）
- [x] 5.2 跑全量 regression → dialogue 区无 regression，邻区
  (multi_day, checkpoint) 也全绿；2 失败属 Bug F 引入（已在 F change 修复）

## 6. Spec validate + archive

- [x] 6.1 `openspec validate --strict` → "is valid"
- [ ] 6.2 archive + commit + push
