## Why

backlog 1.14（单 worker 多核并行）的核心驱动是"publishable 单 worker
14h，机器 70% CPU IDLE"——但提议的具体优化（O(N²) encounter detection
→ scipy.spatial.cKDTree）建立在**未经验证的假设**之上。

2026-05-19 grep `orchestrator/service.py::_detect_encounters` 推翻该
假设：

```python
# 当前实现根本不是 Euclidean radius search
# 而是 location-bucket pair generation：
location_visitors: dict[loc_id, set[agent_id]] = ...
for loc, visitors in location_visitors.items():
    for i, j in combinations(sorted(visitors), 2):
        pair_shared[(i,j)].add(loc)
# 注释明说：O(total_trace_length + N)
```

scipy.spatial.cKDTree 用不上（没有几何 radius 概念）。**1.14 backlog
的 5-10× speedup 估算建立在错误假设上**——单 worker 14h 慢，慢在
**别的东西**，目前不知道是什么。

在不知道真正 hot path 前实施任何优化都是 premature optimization，
属于"测试方法论 Section 11.4 adversarial review" 直接驳回的方案。

## What Changes

**Scope** 严格限定为 **测量 + 落 fixture**，不动任何 production
optimization code。具体交付物：

1. **Profile harness**（新增 `tools/profile_publishable_smoke.py`）：
   - 跑 dev mode `--agents 100 --num-days 1` smoke 同时挂 cProfile
     + py-spy（如可用）
   - 输出 cProfile stats JSON + 火焰图（py-spy SVG，可选）
   - 自动归一化函数路径（去掉 site-packages 噪音、合并 stdlib）
2. **Hot path baseline fixture**（git-tracked，~50KB）：
   - `tests/fixtures/hot_path_profile_baseline.json` —— top-30 函数 +
     cumulative time 占比 + call count
   - **stable schema**：未来 PR 必须 diff 这个 fixture
3. **Regression guard test**（新增 `tests/test_hot_path_baseline_regression.py`）：
   - 跑同样的 dev smoke + cProfile
   - 断言 top-3 函数与 fixture 一致（防止"优化某个函数但碰巧让另一个
     更慢，整体没改进"）
   - 断言 dev smoke 总 wall-clock < N seconds（catch 大幅 regression）
4. **Analysis doc**（新增 `docs/hot-path-analysis-2026-05-19.md`）：
   - 火焰图截图 + top-10 函数表
   - **判读**：每条函数为什么慢、能不能优化、ROI 估算（不是优化方案本身，
     是 next-change 候选清单）
   - **明确 conclusions**：哪个假设被证实 / 哪个被推翻

## Capabilities

### New Capabilities

- `hot-path-baseline`: 把"publishable single-worker run 的 hot path 测量
  结果"作为 git-tracked artifact + regression guard。本 capability
  只交付 measurement + diff 能力，不携带任何 production code 优化职责。

### Modified Capabilities

（无——production code 不动；既有 capability behavior 不变。）

## Impact

**新增文件**：
- `tools/profile_publishable_smoke.py`
- `tests/fixtures/hot_path_profile_baseline.json`
- `tests/test_hot_path_baseline_regression.py`
- `docs/hot-path-analysis-2026-05-19.md`

**修改文件**：（无 production code 改动）

**测试影响**：
- 新增 ≥3 个 test：fixture 存在 + schema 正确 + dev smoke wall-clock budget
- 不改既有 1656 tests

**依赖**：
- `cProfile` / `pstats`（Python stdlib，免装）
- `py-spy`（pip install py-spy，可选；只生成火焰图，没有也不影响 fixture
  生成）

**Non-goals (explicit)**：
- 不优化任何代码——本 change 只 measure
- 不预设"encounter 是 hot path"——profile 显示什么就报告什么
- 不揽 1.14 backlog 整体（多核 / fork / numba 等），只测量
- 不生成 production benchmark CI 流水线（那是下一步）
- 不形式化 capability spec（measurement 是 tooling，不是 capability）

**触发后续**：profile 数据出来后，**根据真实 top-3 hot path 单独
propose 第二个 openspec change** 针对真实瓶颈。可能是：
- MemoryService.retrieve(top_k)（如果真是 do_something 调用 dominant）
- Pydantic serialize / deserialize（如果是 IO bound 表面下的 CPU）
- async event loop overhead（如果是 await 等待 dominant）
- 又或者根本就是 LLM call wait（那就不是 CPU 问题，1.14 的整个思路要重审）

无论哪个，**先量后改**才能保证 ROI 真实。
