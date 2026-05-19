# Testing — 写新 test 前必读

> 1 分钟版本：每个 PR 过下面 8 类问题。哪一类没覆盖，要么写测试，
> 要么在 PR description 显式说明 "scope out 的 reason"。
>
> 长版本见 `docs/testing-philosophy.md`——每条原则配真实事故 +
> DO / DON'T 代码例子。

---

## 提交前 8 类问题清单

跑过项目 venv 后，执行 `pytest tests/` 全绿是必要条件，**远不充分**。
本项目过去 7 个生产事故都在测试全绿的代码里。问自己：

### ☐ 1. 中断路径测了吗？

涉及 SIGUSR1 / SIGTERM / asyncio cancel / Ctrl-C / `--max-ticks`
触发等"中断"的代码必须有 test 验证：

- 中断时**不**写出"看似完整但内容空"的 final 文件
- 中断后 resume 能正确接力，最终 metric 等价于从未中断
- 连续 2 次中断（中断 → resume → 再中断）也不损坏数据

**反例**：今天 SIGUSR1 写假 `seed_N.json`（`tests/test_aborted_in_setup_sentinel.py`）

### ☐ 2. 启动期边界条件测了吗？

涉及"读时间戳判状态"（WAL mtime / file age / process start）的代码
必须测：

- 文件 mtime **早于**进程 start time（worker 还没产生 output）
- 文件不存在
- 文件存在但内容空

**反例**：今天 `resume_publishable.py` WAL staleness 误判
（`tests/test_harden_invariants.py`）

### ☐ 3. 资源 budget 测了吗？

任何"O(N) memory"或"bounded RAM"的代码必须有 explicit budget test，
在 **publishable-scale fixture** 上跑（不是 toy 数据）：

- 单 worker resume publishable snapshot → peak RSS < threshold
- 多 worker 并发 deserialize → 总 RSS < 物理 RAM × 80%
- snapshot 写盘耗时 < threshold

**反例**：今天 4 worker 同时 deserialize 撞 RAM 上限
（**TODO**：`test_concurrent_resume_ram_budget.py` 未写）

### ☐ 4. 外部依赖失败路径 mock 了吗？

任何 subprocess / HTTP / DB call 至少 3 个失败 mode 测试：

```python
@pytest.mark.parametrize("mock_outcome", [
    ("timeout", subprocess.TimeoutExpired(...)),
    ("garbage", CompletedProcess(returncode=0, stdout="junk")),
    ("empty", CompletedProcess(returncode=0, stdout="")),
    ("nonzero", CompletedProcess(returncode=1, stderr="error")),
])
def test_caller_handles_external_failure(mock_outcome):
    ...
```

**反例**：今天 ps 超时 → 双胞胎 spawn（**TODO**：
`test_find_pid_ps_failure_modes.py` 未写）

### ☐ 5. 并发 / atomic 操作 race 测了吗？

声明"atomic"或"thread-safe"的函数必须有多线程/进程 race test，
**至少 10 轮迭代**，threading.Barrier 同步起点，errors 列表收
thread 异常：

```python
def test_op_concurrent_no_corruption(tmp_path):
    barrier = threading.Barrier(2)
    errors: list[Exception] = []
    def _do():
        try: barrier.wait(); operation()
        except Exception as e: errors.append(e)
    for _ in range(10):
        threads = [Thread(target=_do) for _ in range(2)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert errors == []
```

**正例**：`tests/test_simulation_checkpoint.py::test_concurrent_writes_no_corruption`

### ☐ 6. long-running 数据结构有界性测了吗？

累积型 dict/list/set 跑 N 天后必须 bounded：

```python
def test_service_bounded_after_simulated_days():
    svc = MyService()
    for day in range(14):  # 14-day publishable
        _simulate_one_day(svc)
        svc.maybe_evict(day)
    assert len(svc._cache) < 100  # 写出 threshold 不是从代码读
```

**反例**：今天 `DialogueService._dialogues` 无界增长（**TODO**：
`test_dialogue_service_bounded_long_run.py` 未写——现有
`test_dialogue_service_eviction.py` 测了 evict 单步，**没测**长跑总量）

### ☐ 7. smoke 覆盖最坏一天了吗？

不只是 day 0 setup smoke，至少有一条覆盖：

- **Memory peak day**（day 11–12 累积内存满）
- **LLM stress day**（push intervention 那天 LLM call 翻倍）
- **Day-end deadlock 风险窗口**（reflection batch tick）

Smoke 必须输出含 peak RSS / max tick latency / fallback rate，
**不只是 pass/fail**。

**反例**：`tools/preflight_full_smoke.py` 只跑 1 day（**TODO**：
`tests/test_smoke_publishable_day11.py` 未写）

### ☐ 8. CLAUDE.md 不变量配源码级 + 行为级 guard 了吗？

每条 "禁止 X" 不变量配源码 grep test：

```python
def test_no_forbidden_pattern():
    src = Path("path/to/file.py").read_text()
    no_docstrings = re.sub(r'"""[\s\S]*?"""', "", src)
    for forbidden in ["os.kill(", "signal.SIG"]:
        assert forbidden not in no_docstrings
```

每条 "必须 Y" 不变量配行为 mock test：

```python
def test_invariant_enforced():
    runner = _setup()
    with patch.dict(os.environ, {"FLAG": "value"}):
        runner._do_thing()
    assert runner.state == expected
```

**正例**：`tests/test_harden_invariants.py`（3 不变量 × 2 层 guard
= 6 tests）

---

## 测试代码组织约定

```
tests/
├── test_<module>.py                   # 单元测试 — 1 module / 1 file
├── test_<feature>_*.py                # 跨 module feature 测试
├── test_<invariant_name>_invariant.py # CLAUDE.md 不变量 guard
├── test_smoke_*.py                    # smoke / e2e
├── conftest.py                        # 共享 fixtures
└── README.md                          # ← 你正在读
```

测试函数命名：`test_<what>_<condition>_<expected>`：

```python
✅ test_write_atomic_concurrent_no_corruption()
✅ test_evict_old_dialogues_in_progress_preserved()
✅ test_resume_publishable_does_not_call_os_kill()

❌ test_write_atomic()         # 测什么？
❌ test_dialogue_service()     # 哪个 case？
❌ test_thing_works()          # 抽象太多
```

---

## 跑测试

```bash
# 单文件
.venv/bin/python3 -m pytest tests/test_X.py -v

# 失败时一个 fail 就停 + 短 traceback
.venv/bin/python3 -m pytest tests/ -x --tb=short

# 跳过慢测试（已 mark slow 的）
.venv/bin/python3 -m pytest tests/ -m "not slow"

# 并行（跑得快）
.venv/bin/python3 -m pytest tests/ -n auto

# 只跑变更影响的（git diff vs main）
.venv/bin/python3 -m pytest tests/ --picked
```

---

## 测试数据 fixtures

```
data/                          # 真实数据（git-tracked，~10 MB）
├── lanecove_atlas.json        # 真实地图 fixture
└── face_validity/             # 验证用人工 review 输出

tests/fixtures/                # （未来）测试 fixtures
└── publishable_day10_snapshot.json  # publishable-scale resume fixture
```

**重要**：写 budget test (问题 3) 时**不要用 toy 数据**——必须用
publishable-scale fixture，否则测试结果无意义。如果 fixture 太大不能
git-track，写一个 `tests/fixtures/build_fixtures.py` 让 CI / developer
本地生成。

---

## 进一步阅读

### 反应式（防已踩过的雷）

- `docs/testing-philosophy.md` Section 1–10 — 8 条原则完整版（带 case study）
- `CLAUDE.md` 关键不变量系列 — 每条不变量对应测试位置
- `openspec/specs/run-resilience/spec.md` — Spec scenario WHEN/THEN
  写作模板

### 主动式（防还没踩的雷）

- `docs/testing-philosophy.md` Section 11–12 — 4 层主动策略（穷举 +
  随机 + 量化 + 流程）+ 关系图
- `docs/testing-fault-matrix.md` — **穷举式**：48 条具体 fault × 本项目
  响应 + 测试覆盖状态；下次 PR 必看
- `tests/test_dialogue_eviction_property.py` — **随机式**：Hypothesis
  property-based test 模板，5 个 invariant 用 hypothesis 各跑 200 个随机 case
- `pyproject.toml [tool.mutmut]` + `python -m mutmut run` — **量化式**：
  Mutation testing baseline；新 PR 不可让 score 下降
- PR template Section "Fault matrix delta" — **流程式**：
  Adversarial review 8 类问题
