# 测试方法论：从今天的 7 个事故学到的 8 条原则

> 写给本项目所有现在和将来的开发者。读这份文档之前先读 `CLAUDE.md` 的
> "关键不变量"系列——这份文档把那些不变量背后的**测试要怎么写**说清楚。

---

## 0. 为什么写这份文档

**2026-05-19 D2 attempt 6 雪崩**——一个 publishable run 在 12 小时内
经历了 7 次连环故障，全部根因都不是 simulation 算法错，而是 **resilience
/ resource / 工具链** 的 bug。每一个 bug 都对应一类**这个项目从来没写过的
测试**。

按时间顺序：

| 时间 | bug | 缺失的测试类别 |
|---|---|---|
| 06:09 | macOS 自动更新重启，12h 进度丢 | **未覆盖**：跨整机重启的 resume 完整性 |
| 11:59 | SIGUSR1 在 setup 期触发，写假 `seed_N.json` + 删 partials | 中断路径语义测试 |
| 12:08 | 4 worker 同时 deserialize mid-run snapshot 撞 RAM 上限 | 资源 budget 测试 |
| 12:39 | `resume_publishable.py` WAL mtime 误判（新 spawn worker） | 启动期边界条件测试 |
| 12:54 | swap thrash 让 `ps` 超时 → 双胞胎 spawn | 外部依赖失败路径 mock 测试 |
| 13:02 | `state_snapshot.write_atomic` tmp 文件名冲突（双胞胎 spawn 副作用） | 并发原子操作竞态测试 |
| 13:11 | DialogueService 无界增长触发 jetsam 风险 | long-running 数据结构有界性测试 |

**核心反思**：今天每个 bug 都"显然"——`code review` 看代码也容易看出来。
但**没有任何一个 bug 是 review 抓住的**，因为没人按"中断路径"、"资源
budget"、"启动期边界"这种维度去 review。**唯一系统化的防御只能是测试**。

这份文档给 8 条按"血洗"程度排序的原则，每条配一个真实 case study + 代码
模板。

---

## 1. 原则一：测中断路径，不只是 happy path

**血洗 case**：`run_variant_suite.py` 的 SIGUSR1 handler 写
`seed_N.json` 时不区分"自然完成"和"被中断"——`total_ticks=0`
+ `per_day_summaries=[]` 也一样写。下游 audit 看到文件存在 = DONE，
实际数据是空的。**14 个测试覆盖了 happy path，0 个覆盖中断时写出
什么**。

### DO

每一条"会被中断"的代码路径（SIGUSR1 / SIGTERM / asyncio cancel /
KeyboardInterrupt / `--max-ticks` 触发）写**至少 2 个**测试：

1. **中断后磁盘状态正确**：assert 没写出"看起来成功但内容空"的文件
2. **中断后 resume 能正确接力**：assert 用中断后的 disk state 重新
   resume，最终 metric 跟"从来没中断过"一致

```python
def test_sigusr1_in_setup_does_not_write_fake_final():
    """SIGUSR1 在 worker 进 tick loop 之前触发时，SHALL NOT 写
    seed_N.json（那是 'DONE' 标记）；SHALL 写哨兵文件让 audit 区分。"""
    runner = _make_runner_in_setup_state()
    # fire SIGUSR1 before first tick
    runner._graceful_stop_requested = True
    runner._fire_finally_cleanup()
    assert not (output_dir / "seed_42.json").exists()
    assert (output_dir / "seed_42.aborted_in_setup.json").exists()
```

### DON'T

```python
def test_sigusr1_graceful_stop():
    """Happy path：SIGUSR1 → worker exits clean."""
    # ⚠️ 只测了"会 exit"，没测"exit 后留下什么"
    fire_sigusr1(runner)
    assert worker.exit_code == 0  # 不够！还要检查磁盘
```

### Checklist when writing a new "interruptible" feature

- [ ] 至少 1 个 test：中断后磁盘**不含**"看似完整但内容空"的 final
- [ ] 至少 1 个 test：中断后 resume → 最终 metric == 没中断过
- [ ] 至少 1 个 test：连续 2 次中断（中断、resume、再中断）也不损坏

---

## 2. 原则二：测启动期边界条件

**血洗 case**：`resume_publishable.py` 用 WAL mtime 检测 staleness。
Mac 重启后新 spawn 的 worker WAL 文件还是 pre-reboot 的老 mtime，
被误判为 stale，全部被 SIGUSR1 graceful-stop（连带触发原则 1 的
bug）。**0 个测试覆盖"新 spawn worker WAL 比进程更老"这种状态**。

### DO

每一个"读时间戳判断状态"的函数必须测**至少 3 个边界**：

1. 文件不存在
2. 文件 mtime 早于进程 start time（worker 还没写过）
3. 文件 mtime 晚于进程 start time（worker 已经在动）

```python
def test_staleness_classifier_handles_pre_process_wal():
    """新 spawn worker 接手老 WAL 文件时 SHALL NOT 误判 stale。"""
    wal = tmp_path / "seed_42.wal.jsonl"
    wal.write_text("")
    os.utime(wal, (0, 0))  # mtime = 1970-01-01
    fake_pid = _spawn_dummy_process()  # start_time = now
    state, info = _cell_state(suite, 42, "variant", stale_secs=60)
    assert state == CellState.RUNNING_FRESH  # NOT STALE
    assert info["in_setup"] is True
```

### DON'T

只测"WAL 是 5 分钟前 → stale"或"WAL 是 30 秒前 → fresh"，
不测两者交叉时间维度（WAL mtime vs process start time）。

### Checklist

- [ ] 当时间戳比较涉及两个独立时钟（文件 vs 进程），至少 1 个 test
      明确测 "old file + new process" 这个组合
- [ ] 进程还没产生任何输出的状态 ≠ 进程死掉

---

## 3. 原则三：资源消耗必有 explicit budget 测试

**血洗 case**：12:08 spawn 4 worker，每个 deserialize 一个 1.7–3.5 GB
snapshot。Python 反序列化膨胀 5–10×，总 RAM peak 50–100 GB，物理 RAM
48 GB 不够。**单元测试全 OK，因为每个测试都用 tiny snapshot；没人
测过"4 个真实 publishable snapshot 同时反序列化"**。

### DO

每个声明"O(N) memory"或"bounded RAM"的代码必须有一个**explicit budget
测试**：

```python
def test_concurrent_resume_within_ram_budget():
    """4 worker 同时 resume publishable-scale snapshot RAM peak SHALL
    < 物理 RAM 80%（CI 限定 16 GB → 12.8 GB budget）。"""
    ## Skip in CI; only meaningful on developer machine
    if os.environ.get("CI") == "true":
        pytest.skip("RAM budget test requires real machine")

    snap_path = _fixture_publishable_snapshot()  # 1.5GB JSON
    peak_rss_mb = _measure_concurrent_load(snap_path, n_workers=4)
    physical_mb = psutil.virtual_memory().total / 1024 / 1024
    assert peak_rss_mb < physical_mb * 0.8, (
        f"Peak RSS {peak_rss_mb} MB > 80% of {physical_mb} MB physical"
    )
```

如果做不到 真实 4 worker 测试（CI 资源限制），至少做：

```python
def test_single_resume_rss_within_budget():
    """单 worker resume publishable snapshot SHALL < 8 GB peak RSS。"""
    peak = _measure_single_resume_rss(snap_path)
    assert peak < 8 * 1024  # MB
```

### DON'T

```python
def test_snapshot_roundtrip():
    snap = SimulationCheckpoint(seed=42, ledger_state={}, ...)
    snap.write_atomic(path)
    snap2 = SimulationCheckpoint.read(path)
    assert snap2 == snap  # 用 toy 数据，永远过；产线 case 一败到底
```

### Checklist

- [ ] 任何"内存敏感"代码（snapshot / cache / 累积 dict）必有 1 个
      explicit budget 测试，跑在 publishable-scale fixture 上
- [ ] CI 跳过昂贵测试，但 PR description 必须附 "本地跑过 budget 测试"
- [ ] Budget 阈值要硬编码在测试里，rationale 写注释；不要从代码读阈值
      （那是循环论证）

---

## 4. 原则四：外部依赖必 mock 失败路径

**血洗 case**：`resume_publishable.py` 用 `subprocess.run(["ps", ...])`
找 PID。swap thrash 时 `ps` 命令本身超时，返回空 stdout。代码看见
"PID 列表空" 就认为 worker 死了，spawn 替代——**实际上 worker 还
活着**，结果两个 worker 写同一 cell 的 WAL 损坏数据。**测试只测了
ps 返回正常列表的情况，没测 ps 失败 / 超时 / garbage 输出**。

### DO

每个调外部命令（`subprocess` / shell / HTTP / DB）的函数必须有
**failure mode 测试矩阵**：

| 失败模式 | 测试 |
|---|---|
| 命令超时 | mock `subprocess.run` 抛 `TimeoutExpired` |
| 命令返回非零 | mock returncode=1 + stderr |
| 命令返回空 stdout | mock stdout="" |
| 命令返回 garbage | mock stdout="not parseable" |
| 网络断开 | mock raises `ConnectionError` |
| API 401/429/500 | mock 各种 HTTP 状态码 |

```python
@pytest.mark.parametrize("mock_outcome", [
    ("timeout", subprocess.TimeoutExpired(["ps"], 5)),
    ("garbage", subprocess.CompletedProcess([], 0, "junk", "")),
    ("empty", subprocess.CompletedProcess([], 0, "", "")),
    ("nonzero", subprocess.CompletedProcess([], 1, "", "ps error")),
])
def test_find_pid_handles_ps_failures(mock_outcome):
    """ps 命令在 swap thrash / OS load 时可能超时或返垃圾。
    `_find_alive_worker` SHALL NOT 在 ps 失败时假阴性 (返 None →
    认为 worker 死 → double-spawn)。

    Right behavior on ps failure: log warning + return None means
    'cannot determine', and CALLER must not act on that ambiguity.
    """
    with patch("subprocess.run", side_effect=mock_outcome[1]):
        pid = _find_alive_worker(seed=42, variant="x", suite_dir=p)
    assert pid is None
    # Caller (resume_publishable) MUST NOT spawn-on-None-from-ps-failure;
    # only spawn when we have positive evidence the worker is gone.
```

### DON'T

只测 `subprocess.run` 返回 PID 列表的 happy path——线上 99% 跑这条，
但 1% 失败时**没有人在 review code 时记起来 mock 这个分支**。

### Checklist

- [ ] 任何 subprocess / HTTP / DB call 至少 3 个失败 mode 测试
- [ ] 测试要 assert "失败时如何降级" 而非 "失败时如何崩溃"
- [ ] 永远不要在 production code 里"假设 subprocess 总是返回有效值"

---

## 5. 原则五：并发 / 原子操作必有竞态测试

**血洗 case**：`SimulationCheckpoint.write_atomic` 用固定 tmp 文件名
`path.with_suffix(".tmp")`。**单元测试串行调用 100 次都没问题**。
但 13:02 两个 worker 几乎同时 `write_atomic` 同一 path，第二个的
`os.replace` 找不到 tmp 因为第一个已 rename 走了——FileNotFoundError，
worker crash。

### DO

任何"声明 atomic"或"线程安全"的函数必须有**多 worker 并发 race 测试**，
跑**至少 10 轮**（race 是 timing-dependent，跑 1 轮可能巧合通过）。

```python
def test_write_atomic_concurrent_no_corruption(tmp_path):
    """harden-worker-resilience: 2 threads racing to write the same
    snapshot path SHALL NOT corrupt the final file; SHALL NOT raise
    FileNotFoundError on os.replace."""
    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def _write(snap):
        try:
            barrier.wait()
            snap.write_atomic(path)
        except Exception as e:
            errors.append(e)

    for iteration in range(10):  # ← 多轮关键
        path.unlink(missing_ok=True)
        errors.clear()
        threads = [Thread(target=_write, args=(s,)) for s in (snap_a, snap_b)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert errors == [], f"iter {iteration}: {errors[0]!r}"
        loaded = SimulationCheckpoint.read(path)
        assert loaded.day_index in (0, 1)  # 是 A 或 B 之一的完整内容
```

### DON'T

```python
def test_write_atomic_is_atomic():
    snap.write_atomic(path)
    assert path.exists()  # 测了"写入"，没测"并发不损坏"
```

### Checklist

- [ ] 任何"atomic"声明配并发测试，threading.Barrier 同步起点
- [ ] 至少 10 轮迭代增加 race 暴露率
- [ ] 用 errors 列表收集 thread 异常（thread 默认吞异常）
- [ ] 多文件系统（macOS APFS / Linux ext4）行为不同，PR 列在测试覆盖矩阵

---

## 6. 原则六：long-running 数据结构必测有界性

**血洗 case**：`DialogueService._dialogues: dict` 在 dialogue end 之后
永不删。**单元测试跑 5 个 dialogue 测全套状态机；0 个测试**跑 14 天 ×
1000 agent 后 dict size 是否 bounded。线上每 worker 100–500 MB 永久
泄漏，撞 RSS 阈值。

### DO

每个**累积**的数据结构（dict / list / set / deque）必须有**有界性
property test**：

```python
@hypothesis.given(...)  # 或者直接 parametrize
def test_dialogue_service_bounded_after_simulated_days():
    """跑 N 天后，DialogueService 累积内存 SHALL 不超过 cap。"""
    svc = DialogueService(seed=42)
    for day in range(14):  # 14-day publishable
        # 模拟一天的 dialogue activity
        for _ in range(50):
            d = svc.schedule_invite(...)
            svc._end(d, tick=day * 288 + 100, ...)
        svc.evict_old_dialogues(before_tick=(day - 2) * 288)

    # ← 关键 assertion
    assert len(svc._dialogues) < 100, (
        f"Active dialogues bloated: {len(svc._dialogues)}; "
        f"rolling cleanup not working"
    )
    # _dialogue_summaries 可以无界增长但每项 1 KB，14 day × 700 = 1 MB OK
    assert len(svc._dialogue_summaries) < 1000
```

### DON'T

```python
def test_dialogue_lifecycle():
    d = svc.schedule_invite(...)
    svc._end(d, ...)
    assert d.ended_tick is not None  # 测了语义，没测"长跑后总量"
```

### Checklist

- [ ] 任何 service 含累积 dict/list/set，写一个 "跑 N day 后 size <
      threshold" 测试
- [ ] 把 size 阈值写进 spec scenario（不只是测试）
- [ ] 如果带 retention/eviction 机制，专门一个测试模拟"老数据 + 新
      数据混在一起"的 evict 决策正确性

---

## 7. 原则七：smoke 测试要覆盖最坏一天，不只是 day 0

**血洗 case**：项目 smoke test (`tools/preflight_full_smoke.py`) 跑
1000 agent × 1 day——day 0 setup 没问题就 pass。但**所有今天的故障
都在 day 8–11 才出现**：snapshot 大、memory 累积多、LLM 已 fallback
多次。1-day smoke 抓不到 14-day 才暴露的故障。

### DO

至少一类 smoke 跑到**最坏一天**——通常是：

1. **Memory peak day**：day 11–12，cumulative memory 已经攒满
2. **LLM stress day**：day 4 的 push intervention 开始那天，并发
   LLM call 翻倍
3. **Day-end deadlock 风险窗口**：reflection batch 跑完那个 tick

```python
@pytest.mark.smoke_publishable_scale
def test_smoke_day11_memory_peak():
    """1000 agent × 1 seed × resume-from-day-10-snapshot.

    跑 publishable scale 而不是 dev scale；跑 day 11 而不是 day 0。
    """
    ## Pre-built fixture: a day-10 snapshot from a prior run
    snap = _fixture_day10_snapshot()
    runner = MultiDayRunner(restore_from=snap, ...)
    result = runner.run_multi_day(
        start_date=date(2026, 4, 22), num_days=14,  # 期望从 day 10
                                                    # 跑到 day 11 退出
    )
    assert result.metadata["graceful_stop"] is False
    assert len(result.per_day_summaries) >= 1
    # 验证 day 10 → 11 边界没 deadlock：tick latency < 30s
    assert max(d.tick_max_latency_ms for d in result.per_day_summaries) < 30_000
```

### DON'T

只跑 day 0 smoke 就以为"publishable safe"——day 0 是最简单的一天。

### Checklist

- [ ] smoke 矩阵必须有"resume from mid-run snapshot"路径，不只是
      "from-scratch day 0"
- [ ] smoke 输出必须含 peak RSS / max tick latency / fallback rate，
      不只是 pass/fail
- [ ] preflight gate 要把 "day 11 smoke" 列为 publishable 必跑前置

---

## 8. 原则八：spec scenario 必须机器可验证 + 源码级 guard

**血洗 case**：`monitor-as-control-plane` 不变量我们写进了 CLAUDE.md，
但**没有任何 test 在源码里强制 enforce**。两天后某人优化代码加回
`os.kill` 调用，没人发现，又一次雪崩。

### DO

每条 CLAUDE.md 不变量配**两层 guard**：

1. **行为级**：mock 上下文 → 调函数 → assert 不变量成立
2. **源码级**：扫源代码 grep 禁用模式，assert pattern 不存在

```python
def test_resume_publishable_does_not_call_os_kill():
    """monitor-as-control-plane invariant: 守护脚本 SHALL NOT 主动发
    termination signal。"""
    src = Path("tools/resume_publishable.py").read_text()
    no_comments = re.sub(r"#.*", "", src)
    no_docstrings = re.sub(r'"""[\s\S]*?"""', "", no_comments)
    for forbidden in ["os.kill(", "signal.SIG", "kill -USR", "kill -TERM"]:
        assert forbidden not in no_docstrings, (
            f"forbidden pattern {forbidden!r} found in production source. "
            f"See CLAUDE.md monitor-as-control-plane invariant."
        )
```

### DON'T

```python
# ⚠️ 只在 CLAUDE.md 里写 "脚本不能 kill"，没有测试 enforce
# 一次 review 不小心放过，下次 PR 就破坏不变量
```

### Checklist

- [ ] 每条 "禁止 X" 类不变量配一个源码级 grep test
- [ ] 每条 "必须 Y" 类不变量配一个行为级 mock test
- [ ] 测试文件命名 `test_<invariant_name>.py` 让 git blame 容易追溯
- [ ] Spec scenario 的 WHEN/THEN 必须可映射到具体 test fn，PR review
      时人工 check

---

## 9. 综合 checklist：写新 capability 时的 8 类问题

任何新 OpenSpec capability / 大 PR 提交前，过这 8 类问题：

```
✅ 1. 中断路径测了吗？
   - SIGUSR1 / SIGTERM / asyncio cancel / Ctrl-C 在 setup 期、tick 中
     间、day_end 各触发一次，每次 assert 磁盘 + resume 正确

✅ 2. 启动期边界条件测了吗？
   - 文件 mtime 早于进程 start time
   - 进程还没 produce 任何 output 时的 state classifier 行为
   - 第一个 tick 之前的 signal 投递

✅ 3. 资源 budget 测了吗？
   - publishable-scale fixture 单 worker / 多 worker RSS 上限
   - snapshot 写盘时间上限
   - 反序列化时间 + RAM peak 上限

✅ 4. 外部依赖失败路径 mock 了吗？
   - subprocess 超时 / 非零 / 空 / 垃圾
   - HTTP 4xx / 5xx / 网络断
   - DB connection drop

✅ 5. 并发 / atomic 操作 race 测了吗？
   - threading.Barrier + 10 轮迭代
   - 多 worker 写同一 path、同一 cell

✅ 6. long-running 数据结构有界性测了吗?
   - dict/list/set 跑 14 day 后 size < threshold
   - retention / eviction 机制实测有效

✅ 7. smoke 覆盖最坏一天了吗？
   - 不只是 day 0，至少有一条覆盖 day 8+
   - 输出含 peak RSS / max latency / fallback rate

✅ 8. 不变量配源码级 + 行为级 双层 guard 了吗？
   - 禁用模式 grep test
   - 行为 mock test
   - 写进 CLAUDE.md 引用 test 文件
```

---

## 10. 给 OpenSpec spec 写 scenario 的 best practice

每个 `### Requirement:` 下的 `#### Scenario:` 应该满足：

1. **可机器验证**：WHEN/THEN 子句能 1:1 映射到一个 test fn 的 setup +
   assertion
2. **覆盖 happy + sad**：每条 requirement 至少 1 happy scenario + 1
   sad scenario（中断 / 失败 / 边界）
3. **避免"待人工 review"**：不允许 "THEN reviewer 检查 output 合理"
   这种 scenario
4. **关联到测试文件**：在 commit message 或 PR description 里写
   `Scenario X → tests/test_y.py::test_z`

参考模板见 `openspec/changes/archive/2026-05-19-harden-worker-resilience/specs/`。

---

## 11. 怎么防"还没踩过的雷"——4 层主动策略

前面 8 条原则是 **反应式**——每条对应一次已发生事故。但用户会问得对：
"万一有漏下的呢？"——8 条不能穷举所有可能的 bug 类型。

这一节给 4 层 **主动** 防御，依次强化（每层补上一层的盲点）：

### 11.1 穷举式：Fault matrix

**思想**：列出**所有**可能的 fault 类别（OS / 网络 / 磁盘 / 时间 /
内存 / 进程 / 文件系统 …），对每条问"代码遇到时怎样"+"有 test 吗"。

**落地**：`docs/testing-fault-matrix.md` —— 7 大类 × 48 条具体 fault，
每条标 ✅ / ⚠️ / ❌。截至 2026-05-19，本项目 **31% 全覆盖、33%
未覆盖**——未覆盖那 33% 就是下次最可能踩的雷。

**何时用**：
- 写新 capability 前 review 一遍 matrix，看 spec 是否涉及 ❌ / ⚠️
  条目；若涉及，必须先把那条提到 ✅
- 季度审计，更新状态 + 添加新发现的 fault

### 11.2 随机式：Property-based testing

**思想**：不写"特定 input → 特定 output"，写**不变量**（property）；
让 [Hypothesis](https://hypothesis.readthedocs.io) 在大空间随机采样
input，自动 shrink 出最小反例。

**例**：`tests/test_dialogue_eviction_property.py`——5 条 invariant
（in-progress 永不 evict / 单调性 / idempotent / 守恒 / cutoff
线性映射），每条 200 个随机 input。Hypothesis 会自动找到"如果存在
反例，最小反例长这样"。

**模板**：

```python
import hypothesis.strategies as st
from hypothesis import given, settings

@given(
    inputs=st.lists(st.integers(min_value=0, max_value=1000), min_size=0, max_size=50),
    cutoff=st.integers(min_value=-100, max_value=2000),
)
@settings(max_examples=200, deadline=None)
def test_invariant_X(inputs, cutoff):
    """SHALL invariant: <state your invariant in 1 sentence>."""
    result = your_function(inputs, cutoff)
    # Now assert the invariant holds *for all* inputs, not just one
    assert <property holds>, f"failed for inputs={inputs} cutoff={cutoff}"
```

**何时用**：
- 任何 pure function 接受 List / Dict / 数值参数的代码
- 任何"有不变量"声明的代码（如 evict / merge / sort / dedupe）
- 任何 "round-trip" 操作（serialize → deserialize 等价）

**何时 NOT 用**：
- 重度 IO / 网络 / DB（hypothesis 跑得慢、不可重复）
- LLM-coupled 逻辑（output 本身有随机性）

### 11.3 量化式：Mutation testing

**思想**：自动改源码（把 `<` 改成 `<=`、把 `+` 改成 `-`、把 `True`
改成 `False`），跑测试看是否被 catch。**Mutation score = killed
mutations / total mutations**——你测试到底有多严的客观指标。

**预期**：

| Mutation score | 解读 |
|---|---|
| < 50% | 测试很弱，大量 mutation 滑过 |
| 50–75% | 一般，关键逻辑有测但 edge case 没测 |
| 75–90% | 良好，可以发布 |
| > 90% | 优秀，但小心 "test 过度耦合到实现" 的陷阱 |

**本项目 baseline (2026-05-19)**：

`dialogue_service.py` 用 `tests/test_dialogue_service_eviction.py` 作为
runner，配 coverage 过滤：

```
Total mutations:  123  (coverage-filtered subset)
🎉 Killed:        53
🙁 Survived:      70
⏰ Timeout:       0
🤔 Suspicious:    0
─────────────────────────────────
Mutation score:   43%  ← 本项目首个量化分
```

**解读**：43% 落在"弱"区，**符合预期**——eviction tests 只针对
`evict_old_dialogues` / `retrieve_summary` / snapshot 路径（~70 行新代码），
而 mutmut 对**整个文件** 250+ 行做 mutation。要把分数推到 75%+ 需要
把现有 `test_dialogue_service.py`（schedule_invite / accept / reject /
state machine 等）也加入 runner——但那是另一个 capability 的事，本
change scope 不包。

**下次 PR 准入条件（建议加进 PR template）**：

```
☐ mutmut score 不可下降（当前 baseline 43%）
☐ 新加代码必须把 score 整体推 +1% 以上
```

**跑命令**：

```bash
# 先生成 coverage（mutmut 用它过滤无法到达的 mutation）
.venv/bin/python3 -m pytest --cov=synthetic_socio_wind_tunnel.conversation.dialogue_service \
    tests/test_dialogue_service_eviction.py

# 再跑 mutation
.venv/bin/python3 -m mutmut run \
    --paths-to-mutate synthetic_socio_wind_tunnel/conversation/dialogue_service.py \
    --runner ".venv/bin/python3 -m pytest -x -q tests/test_dialogue_service_eviction.py" \
    --use-coverage

# 看结果
.venv/bin/python3 -m mutmut results
.venv/bin/python3 -m mutmut show <mutant_id>   # 查具体某个 surviving mutation
```

**注意**：mutmut 3.x 在 macOS 上有 sandbox-copy 问题（`.VolumeIcon.icns`
hidden file），本项目用 v2.x 锁定（`pyproject.toml` deps）。

**何时用**：
- 任何新 capability 完成后，跑一次 mutmut 看 score
- score < 75% → 补 test
- 每个季度跑一次，确认无回退

**何时 NOT 用**：
- IO / 信号 / 多进程代码（mutmut 慢且不稳）
- 大模块（一次跑可能要几小时）—— 只针对"关键纯逻辑"

### 11.4 流程式：Adversarial spec review

**思想**：spec / PR review 时强制有人扮"破坏者"，问 "如果 X 发生
呢？"。前 3 层是工具层，这一层是**人**层——工具找不到的高层故障
（"如果磁盘满了"、"如果时钟跳跃"、"如果两 worker 写同一文件"）
只能靠人想。

**Checklist**（review 时强制问的 8 类）：

1. "如果 SIGUSR1 在你这块代码**任意一行**触发会怎样？"
2. "如果你读的文件 mtime 早于本进程 start time 呢？"
3. "如果 publishable-scale 跑这段，RAM peak 多少？跑过 budget test 吗？"
4. "你调的 subprocess / HTTP / DB 失败时怎样？mock 过失败 path 吗？"
5. "如果两个 worker 同时跑你这段呢？竞态测了几轮？"
6. "你新加的 dict / list 跑 14 day 后多大？bounded 吗？"
7. "smoke test 是 day 0 还是 day 11？"
8. "新加的 invariant 有 source 级 grep test 吗？"

review 把这 8 个问题挂在 PR template 里，每问一个 reviewer 必须答
"是 X" 或 "不适用 因为 Y"。

**为什么这一层不能去掉**：工具发现不了"系统级"故障——比如 RAM peak
collide / 双胞胎 spawn / reboot 跨周期完整性。这些必须人脑模拟。

---

## 12. 4 层关系图

```
┌──────────────────────────────────────────────┐
│ 反应层 (8 原则 + harden-worker-resilience)    │  ← 防"已踩过的雷"
└──────────────────────────────────────────────┘
                  ↑ 每次事故必反喂
┌──────────────────────────────────────────────┐
│ 预测层 4 层 (穷举 + 随机 + 量化 + 流程)        │  ← 防"还没踩的雷"
│  - Fault matrix       (穷举式)               │
│  - Property-based     (随机式)               │
│  - Mutation testing   (量化式)               │
│  - Adversarial review (流程式)               │
└──────────────────────────────────────────────┘
                  ↑ 跑不出来时
┌──────────────────────────────────────────────┐
│ 兜底层 (production monitor + postmortem)      │
│  - resume_publishable.py 巡检                │
│  - LaunchAgent 自动恢复                       │
│  - 每个事故必写 postmortem + 入反应层         │
└──────────────────────────────────────────────┘
```

**每层都漏的 bug 才是 escape——但漏 3 层的概率远小于漏 1 层**。

---

## 附录：今天每个事故的对应 test

| 事故 | 防御 test 文件 | 原则 |
|---|---|---|
| SIGUSR1 写假 final | `tests/test_aborted_in_setup_sentinel.py` | 1 |
| WAL mtime 误判 | `tests/test_harden_invariants.py` (in_setup detection) | 2 |
| 4 worker RAM peak | TODO: `test_concurrent_resume_ram_budget.py`（未做） | 3 |
| ps 超时 double-spawn | TODO: `test_find_pid_ps_failure_modes.py`（未做） | 4 |
| atomic write race | `tests/test_simulation_checkpoint.py::test_concurrent_writes_no_corruption` | 5 |
| DialogueService 无界 | TODO: `test_dialogue_service_bounded_long_run.py`（未做） | 6 |
| smoke day 0 抓不到 day 11 bug | TODO: `tests/test_smoke_publishable_day11.py`（未做） | 7 |
| 不变量无 enforce | `tests/test_harden_invariants.py`、`test_direct_llm_timeout_guard.py` | 8 |

> "TODO" 行是这份方法论暴露但本次 change 未实施的 gap。下次开 OpenSpec
> change 时考虑做 1-2 个补齐。
