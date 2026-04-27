## Context

`validation-strategy` Part IV / Part V 把 calibration 协议规定好了
（数据源 / 距离指标 / acceptance），但留了"未实施"标签。本 change 把它
落地，接入现有 `population.py` + `build_scripted_plan` + run_variant_suite
报告链。

`fitness-audit` 协议 `phase1-baseline.profile-preset-ground-truthed` 当前 FAIL；
本 change 目标是把它转 PASS（best-effort 阈值），打开 publishable suite 的
第 1 个门禁。

## Goals / Non-Goals

**Goals**：
- LANE_COVE_PROFILE 6 维分布 best-effort 通过（≥ 4/6 维度 p > 0.10）
- baseline sim 14d × 1000 agent 的 OD + Popular Times 行为通过 best-effort
  阈值
- 三类 scripted_plan（commute / errand / leisure）替换 4-6-slot random 版
- calibration assessment 进 publishable suite report

**Non-Goals**：
- Strict acceptance（stretch；不达标不 block archive）
- 自动调参（手填 + 几轮迭代足够）
- 接入 ABS live API（static snapshot，重现性优先）
- 校准 attention 行为（注意力 / replan 是 thesis 主线，不是 calibration 范畴）

## Decisions

### D1：ABS Census 用 static JSON snapshot，不接 TableBuilder API

**选择**：手工从 ABS 网站下载 Lane Cove SA2 6 维表，转成内部 JSON schema，
存 `data/calibration/abs_census_lanecove_2021.json`。

**Schema**：
```jsonc
{
  "source": "ABS Census 2021 Lane Cove SA2",
  "downloaded": "2026-04-26",
  "url": "https://www.abs.gov.au/...",
  "total_population": 11242,
  "distributions": {
    "age": {"0-4": 0.063, "5-9": 0.061, ..., "85+": 0.012},
    "gender": {"male": 0.487, "female": 0.513},
    "housing_tenure": {"own": 0.31, "mortgage": 0.27, "rent": 0.39, "public": 0.03},
    "income_tier": {"low": 0.31, "mid": 0.42, "high": 0.27},
    "ethnicity_group": {...},  // 按 ABS ancestry top-10 + "other"
    "work_mode": {"commute": 0.41, "remote": 0.18, "shift": 0.07, "not_working": 0.34}
  }
}
```

**Why static**：
- 研究项目重现性硬要求："任何时点跑同份代码 → 同份结果"
- ABS Census 5 年一次（2021 → 2026 下次更新），刷新率不重要
- 避免 API key 维护 / schema drift / 半年后 endpoint 死掉

### D2：Popular Times 用 Outscraper API + ship JSON

**选择**：写 `tools/fetch_popular_times.py`，用 Outscraper Free Tier
（500 businesses 免费额度 > 我们的 ~20 POI），抓 Lane Cove top-20 POI 的
完整 24h × 7d schedule，存 `data/calibration/lanecove_popular_times.json`。

**Schema**：
```jsonc
{
  "source": "Outscraper Google Maps API",
  "fetched": "2026-04-26",
  "pois": [
    {
      "id": "...", "name": "...", "place_id": "...",
      "category": "cafe|park|library|...",
      "popularity": [
        // index = day-of-week 0=Mon, 1=Tue, ..., 6=Sun
        // each is array of 24 ints (% peak), 0 = closed
        [0, 0, ..., 0],  // Mon
        ...
      ]
    },
    ...
  ]
}
```

**Why Outscraper**：
- 商业 SaaS 自己负责对抗 Google 反爬
- Free tier 永久覆盖我们用量
- 一次性 fetch + 提交 JSON：保留 static snapshot 优势

**Backup plan**：若 Outscraper 政策变了，切 SerpAPI 也是免费 tier；脚本
重写很简单（HTTP + parse）。

### D3：scripted_plan 重构为 commute / errand / leisure 三模式

**选择**：新建 `synthetic_socio_wind_tunnel/agent/scripted_plan.py`，公共 API
保持 `build_scripted_plan(profile, destinations, date, rng) -> DailyPlan`
（原签名），内部按 profile.work_mode 分派：

```python
def build_scripted_plan(profile, destinations, date, rng):
    work_mode = profile.work_mode  # commute / remote / shift / not_working
    if work_mode == "commute":
        return _commute_day(profile, destinations, date, rng)
    elif work_mode == "remote":
        return _remote_day(profile, destinations, date, rng)
    elif work_mode == "shift":
        return _shift_day(profile, destinations, date, rng)
    else:  # not_working
        return _flexible_day(profile, destinations, date, rng)
```

每个 day-shape 内部：
- 锚点 step（home / workplace / commute return）按 ABS Travel Survey OD +
  时段分布
- 灵活 step（errand / leisure）按 personality + Popular Times 加权采样目的地

**Rationale**：4-6 random slots 永远 match 不上真实 OD 分布；三类化是行为
校准的硬前提。

**Public API contract 不变**——`tools/*` 里 `from ... import build_scripted_plan`
仍能跑；只是路径换到 `synthetic_socio_wind_tunnel.agent.scripted_plan`，
原 `tools/smoke_experiment_demo.py` 内的副本删除。

### D4：scripted_plan 位置——production code 而非 tools/

**选择**：`synthetic_socio_wind_tunnel/agent/scripted_plan.py`（production），
**不是** `tools/scripted_plan.py`。

**Why**：
- behavioral calibration 是 publishable 路径硬依赖；不是"demo 实用工具"
- 加入 agent capability spec → 有 SHALL 契约，未来变更受 spec 保护
- 公共 API 通过 `synthetic_socio_wind_tunnel/agent/__init__.py` re-export
- 符合 CLAUDE.md "生产代码路径不得含 mock_/demo_/_v2" 命名规约（之前在
  `smoke_experiment_demo.py` 里就违反了）

### D5：Calibration helper 用 scipy 而不是手写

**选择**：`scipy.stats.chi2_contingency` / `scipy.stats.kstest` /
`scipy.stats.wasserstein_distance`。

**Rationale**：
- `requirements.txt`/`pyproject.toml` 加 scipy 是值得的（一项明确依赖换三个
  正确实现的统计函数）
- 手写 chi² + Welford 补偿 / EMD optimal transport 容易写错；不写错也是
  时间黑洞
- scipy 是科学 Python 标准库，安装代价低；CI 已有 numpy

### D6：Acceptance 阈值 — best-effort 是本 change 目标

**选择**：

| 维度 | best-effort（本 change） | strict（stretch） |
|---|---|---|
| 人口 6 维 | ≥ 4/6 维度 p > 0.10 | 6/6 维度 p > 0.10 |
| OD chi² | p > 0.05 | p > 0.10 |
| Popular Times EMD | ≥ 70% POI EMD < 0.25 | ≥ 80% POI EMD < 0.20 |

best-effort 通过 → fitness-audit `phase1-baseline.profile-preset-ground-truthed`
PASS、checklist #1 ✓、本 change 可 archive。

**Why best-effort 阈值放宽**：
- 6 维同时调极难（耦合：年轻人租房，老人自有；调一维破另一维）
- 3360-cell Popular Times 完美 match 不可能（节假日 / 天气 / 突发事件 OSM 没记）
- best-effort + 显式 disclose 是 publishable 学术实践标准（不是"放水"，是
  "诚实"）

### D7：Calibration 不接入 hot path（不每天跑）

**选择**：calibration 是**离线协议**——`tools/run_calibration.py` 单独跑，
产出 report；suite 跑 sim 时**不**重算 calibration（report 是已知 PASS/FAIL
的静态状态）。

**Why**：
- chi² + KS 跑 1000 agent 大约 1 s；不算贵
- 但 OD 校准要跑 14d × 1000 agent baseline = 4 minute（dev mode）/ 几分钟
  （publishable mode）—— 加进 hot path 让每个 variant suite 跑都重算 4 分钟
  浪费
- run_calibration.py 单独跑后，把 report 路径写进 publishable suite 的
  config / metadata；run_variant_suite 读这份 report 引到最终 report.md

### D8：fetch_popular_times CLI 依赖 OUTSCRAPER_API_KEY

**选择**：脚本严格要求 `OUTSCRAPER_API_KEY` env；缺则 sys.exit(2) +
诊断 message。**不**写默认 key / 不嵌入仓库 key。

**Rationale**：API key 永远不上 git；脚本有清晰 onboarding：
```
$ python3 tools/fetch_popular_times.py
error: OUTSCRAPER_API_KEY env required. Sign up at outscraper.com (free tier
500 businesses/mo). Set OUTSCRAPER_API_KEY=... and re-run.
```

JSON 一旦抓出来就提交仓库 → 后续重现 sim 不需要 API key。

### D9：build_scripted_plan 公共 API contract

**保留**当前签名：`build_scripted_plan(profile, destinations, date, rng)`。
内部行为升级（三类化），外部调用方不动。

未来若需要传额外参数（如显式 work_mode override），加 keyword-only kwarg；
不破坏现有签名。

## Risks / Trade-offs

**[Risk 1] ABS 数据 6 维不全 / 字段定义模糊**
→ ABS Census Lane Cove SA2 6 维都有公开表，但分桶可能与我们 schema 不
  对齐（如 ABS 有 19 个 income bracket，我们用 3 tier）。需要在
  `docs/calibration/01-data-sources.md` 详细记录映射规则；assessment 算法
  以 ABS 桶为准对齐 sim 桶。

**[Risk 2] Popular Times 抓不全**（Lane Cove 小 POI Google 没数据）
→ Outscraper 返回 `popularity: null` 时跳过该 POI，从 top-20 降到能拿到的
  N 个。报告里 disclose 实际 N。

**[Risk 3] LANE_COVE_PROFILE 调到 best-effort 也不够**
→ 多迭代 1-2 轮（根据 chi² p 值方向手调）；如果 4/6 都拿不下，可能要重审
  ABS 数据（如 work_mode 桶 ABS 没直接给，要按 employment status 推算）

**[Risk 4] OD 矩阵 ABS 数据粒度不够**
→ ABS Travel Survey 给的是 SA2 → SA2 OD；Lane Cove 内部 destination ID
  级别 OD 没有。需要假设 "Lane Cove → 其它 SA2" 比例适配为 "agent home
  destination → 离 home 远的 sim destination"。报告里 disclose 这个建模
  decision。

**[Risk 5] scripted_plan 重构破现有 sim**
→ 用 build_scripted_plan 的 5 个 tools 全部跑一遍 smoke 验证；
  `test_scripted_plan.py` 用 mock profile 验证三类比例正确

**[Risk 6] scipy 引入新依赖**
→ scipy 是 numpy 之后第二常见科学包；安装 ~50 MB；CI / Docker 影响小。
  pyproject.toml 加到 main deps（不是 [dev]，因为 calibration 是产品功能）

**[Risk 7] best-effort acceptance 被 reviewer 质疑放水**
→ 显式 disclose"哪些维度没过 + 为什么"是学术诚实标准；同时本 change archive
  时若 strict 也已通过，自然写成 strict 报告

## Migration Plan

阶段 1（数据 + 工具，3-4 day）：
1. 手工下载 ABS Census Lane Cove SA2 6 维表 → 写转换脚本（一次性）→
   `data/calibration/abs_census_lanecove_2021.json`
2. 手工下载 ABS Travel Survey 2021 OD → 转 JSON
3. 实现 `tools/fetch_popular_times.py` + 抓一次 → 提交 JSON
4. `docs/calibration/01-data-sources.md` 记录所有数据源

阶段 2（计算层，2-3 day）：
5. 实现 `synthetic_socio_wind_tunnel/agent/calibration.py`：6 维 chi²/KS
   + OD chi² + Popular Times EMD + assess_*
6. 单元测试 + 数值验证

阶段 3（人口校准，2-3 day）：
7. 跑当前 LANE_COVE_PROFILE → 看 6 维 p 值
8. 手调 LANE_COVE_PROFILE 数值 → 重测 → 直到 ≥ 4/6 通过

阶段 4（行为层，3-4 day）：
9. 重写 `build_scripted_plan` 三类化（移到 `synthetic_socio_wind_tunnel/agent/
   scripted_plan.py`）
10. 跑 baseline 14d sim → 计算 OD 矩阵 + Popular Times 时段热度
11. 调三类比例 / errand 时段权重 → match

阶段 5（CLI + 集成，1 day）：
12. `tools/run_calibration.py` CLI
13. publishable suite report 接入 calibration section

阶段 6（测试 + 文档 + archive sync）

**回滚**：删 data/calibration + git revert agent/* + tools/* import 路径恢复
即可。下游 stereotype-audit / face-validity 受影响，但它们都还没立项。

## Open Questions

1. **Q1**: ABS data privacy？SA2 级别公开数据没 PII；下载的 raw CSV 不进
   git（只进 JSON 转换后的版本）
2. **Q2**: 抓 Popular Times 时间段 — 工作日 vs 含周末？
   倾向：抓完整 7 天，校准时分别评估
3. **Q3**: LANE_COVE_PROFILE 调过头怎么 detect？
   倾向：同时跑 strict assessment 当 sanity 检查；如果 best-effort 通过但
   strict 大幅倒退，提示"可能 over-fit"
4. **Q4**: 做 Lane Cove 之外其它社区时怎么扩展？
   倾向：本 change 只做 Lane Cove；schema 设计留扩展位（数据 path 配置化），
   下个社区再补
5. **Q5（Resolved 2026-04-27）**：发现 AgentProfile 缺 `gender` 字段无法
   做 6 维 ABS 校准；本 change 范围**含 gender 字段加入**（profile.py +
   population.py + sample_population），但**不级联到** name generator /
   Planner prompt 一致性 —— 那部分 defer 到 stereotype-audit 或独立
   change 处理（gender-aware naming + pronoun in prompt）
