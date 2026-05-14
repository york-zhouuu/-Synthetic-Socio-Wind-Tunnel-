## 1. Orchestrator: TickResult.entity_locations

- [x] 1.1 在 `orchestrator/models.py::TickResult` 加 `entity_locations: tuple[tuple[str, str], ...] = ()` 字段（默认空元组保向后兼容）
- [x] 1.2 在 `orchestrator/service.py::_run_tick` 把已有的 `entity_locations` dict 转为 tuple 填入 TickResult

## 2. PositionTraceRecorder

- [x] 2.1 新建 `metrics/position_trace.py`：`PositionChange` dataclass + `PositionTraceRecorder` class
- [x] 2.2 实现 `on_tick_end`：sparse 记录（仅在 location_id 与上次记录不同时 append）
- [x] 2.3 实现 `to_dict()` + `write(Path)`：JSON schema "position_trace_v1"
- [x] 2.4 在 `metrics/__init__.py` re-export
- [x] 2.5 新增 `tests/test_position_trace.py` 5 scenarios（no_change_no_record / changes_recorded / serialization / empty_location_ignored / multi_day）

## 3. Suite wiring

- [x] 3.1 在 `run_seed_with_metrics` 实例化 `PositionTraceRecorder` 并 `register_on_tick_end`
- [x] 3.2 把 recorder stash 到 `variant_metadata["position_recorder"]`，主调度从此 pop 出来
- [x] 3.3 主调度在 dump seed_X.json 旁写 `seed_X_positions.json`
- [x] 3.4 在终端输出加 `pos_changes={N}` 日志

## 4. 验证

- [x] 4.1 `pytest tests/test_position_trace.py` 5 PASS
- [x] 4.2 `pytest tests/test_memory_service.py tests/test_orchestrator_*.py tests/test_variant_smoke_e2e.py` 37 PASS（TickResult 字段添加不破坏现有逻辑）
- [x] 4.3 14d × 4 variant × 50 agent stub run 验证：每 variant 生成 ~2200 changes（725KB total）；终端日志含 `pos_changes={N}`
- [x] 4.4 顺带验证 thesis 信号：pf eff=17205 (consistent vs baseline 13991)

## 5. 后续（separate change，不在本范围）

- [ ] 5.1 3D dashboard 接入 position trace（day slider 时间轴）—— 开新 change 做
- [ ] 5.2 archive 本 change
