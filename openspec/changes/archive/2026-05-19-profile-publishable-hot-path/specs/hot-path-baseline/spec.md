## ADDED Requirements

### Requirement: 提供 dev-mode profile harness

`tools/profile_publishable_smoke.py` SHALL 作为可执行 CLI，跑 dev mode
`--agents 100 --num-days 1` smoke 同时挂 `cProfile.Profile()` 收集
function-level cumulative time，输出 JSON 到指定路径。

CLI 形态：

```bash
python tools/profile_publishable_smoke.py \
    --output tests/fixtures/hot_path_profile_baseline.json \
    [--seed 42] [--top-n 30]
```

JSON schema（locked，未来 PR 不可随意改）：

```json
{
  "metadata": {
    "scale": "dev",
    "agents": 100,
    "num_days": 1,
    "seed": 42,
    "python_version": "3.11.x",
    "captured_at": "<iso-datetime>",
    "wall_clock_seconds": <float>,
    "cprofile_overhead_pct_estimate": <float>
  },
  "top_n_functions": [
    {
      "rank": 1,
      "qualname": "<module:function>",
      "cumulative_seconds": <float>,
      "cumulative_pct": <float>,
      "call_count": <int>,
      "per_call_seconds": <float>
    },
    ...
  ]
}
```

`top_n_functions` SHALL 按 `cumulative_seconds` 降序，长度等于 `--top-n`
（默认 30）。

#### Scenario: harness CLI 跑通输出合法 JSON
- **WHEN** 用 `--seed 42 --agents 100 --num-days 1` 跑 harness 到一个
  临时 path
- **THEN** path SHALL 存在 + 是合法 JSON + schema 符合 above；
  `top_n_functions[0].cumulative_pct` SHALL > 0 且 < 100；
  `metadata.wall_clock_seconds` SHALL > 0

#### Scenario: top-N 截断生效
- **WHEN** 用 `--top-n 5` 跑 harness
- **THEN** `top_n_functions` SHALL 长度 5

### Requirement: 落 git-tracked baseline fixture

`tests/fixtures/hot_path_profile_baseline.json` SHALL 由 harness 生成
**至少一次**并 git commit。该 fixture 是后续 regression test 的对照源。

fixture SHALL 满足：

- 由 harness 在 dev mode `--seed 42 --agents 100 --num-days 1` 配置下
  产生（这是 reproducibility 锚点）
- 文件 size < 100 KB（可读、可 diff）
- 不进 git-LFS

#### Scenario: fixture 在 tests/fixtures/ 下存在
- **WHEN** repo root 下查 `tests/fixtures/hot_path_profile_baseline.json`
- **THEN** 文件 SHALL 存在；SHALL 可 `json.loads` 解析；
  `metadata.scale == "dev"`；`metadata.agents == 100`

### Requirement: regression test 防止 hot-path top-3 隐性偏移

`tests/test_hot_path_baseline_regression.py` SHALL 包含至少一个测试，
按下面三层断言：

1. **结构性**：top-3 函数 `qualname` 集合（**不是顺序**）等于 fixture 的
   top-3 集合
2. **wall-clock budget**：跑 dev smoke 总 wall-clock < fixture 记录值 × 1.5
3. **fixture 完整性**：fixture 符合 ADDED Requirement #1 的 schema

任一断言失败 SHALL 输出**可定位**信息：哪个函数偏移、新 wall-clock 是多少、
fixture 缺哪个字段。

`test_hot_path_baseline_regression.py` SHALL 用 `@pytest.mark.slow` 标记
（dev smoke 跑一遍 ~60s，不能进默认 CI 路径）。

#### Scenario: top-3 集合一致 → 通过
- **WHEN** 当前 dev smoke profile 的 top-3 函数集合等于 fixture top-3
- **THEN** test SHALL pass

#### Scenario: top-3 集合不一致 → 失败 + 可读 diff
- **WHEN** 当前 profile 的 top-3 集合中有一个函数不在 fixture top-3 集合
- **THEN** test SHALL fail；error 信息 SHALL 包含两个集合的 set diff
  （`新出现的: [...]; 消失的: [...]`），让 reviewer 立即定位哪条
  optimization PR 引起的 hot-path shift

#### Scenario: wall-clock 超 1.5× 预算 → 失败
- **WHEN** dev smoke 跑出 wall-clock 是 fixture 记录值的 2×
- **THEN** test SHALL fail；error 信息 SHALL 含 baseline 和 current 两个
  数字 + ratio

### Requirement: 落判读文档为后续优化的输入

`docs/hot-path-analysis-2026-05-19.md` SHALL 至少包含：

- top-10 函数表（从 fixture 提取，按 cumulative time 排序）
- 每条函数的"为什么慢"判读（1 句话）+ "能优化吗"评估
  （`yes-high-roi` / `yes-low-roi` / `no` / `unclear-need-more-data`）
- 三条**明确结论**：
  1. backlog 1.14 KD-tree 假设是否被推翻 / 部分支持 / 完全验证
  2. 下一个 openspec change 应针对的 top 候选（按 ROI×风险）
  3. 仍然 unclear 的问题（如果有），下一步如何 narrow down

文档语言：中文（与项目文档一致）；技术名词保留英文。

#### Scenario: 文档存在 + 包含三条结论
- **WHEN** repo root 下查 `docs/hot-path-analysis-2026-05-19.md`
- **THEN** 文件 SHALL 存在；SHALL 包含 "## 结论" section；section
  下 SHALL 至少含 3 个 `###` 子标题或 bullet item
