# data/experiments — selective tracking

整个 `data/experiments/` 目录在 `.gitignore` 里，因为本地累计 ~215MB（含
position trace、缓存中间产物、demo 输出等噪声）。

**只有以下 thesis-relevant runs 通过 `git add -f` 强制纳入 Git**，方便他人复现
+ 评审参考：

## 已纳入

| 目录 | 时间 | 大小 | 用途 |
|---|---|---|---|
| `20260513_032122_sensitivity_0.2/` | 2026-05-13 | 2.3M | B3 sensitivity sweep · BASE_NOTICING_RATE=0.2 |
| `20260513_032150_sensitivity_0.3/` | 2026-05-13 | 2.3M | B3 sensitivity sweep · BASE_NOTICING_RATE=0.3 (default) |
| `20260513_032218_sensitivity_0.4/` | 2026-05-13 | 2.3M | B3 sensitivity sweep · BASE_NOTICING_RATE=0.4 |
| `20260511_132735_d1_deepseek_nothink_smoke/` | 2026-05-11 | 3.8M | D1' OG DeepSeek smoke（**有 home_location bug，已 disclose**） |
| `20260511_172808_d2_deepseek_publishable/` | 2026-05-11 | 1.6M | D2 DeepSeek publishable run |
| `20260427_182712_publishable_real_llm_v1/` | 2026-04-27 | 1.0M | 早期 Gemini publishable v1 |
| `20260428_130934_publishable_real_llm_v2_post_realism/` | 2026-04-28 | 1.0M | post-realism Gemini publishable v2 |
| `aitown_publishable_v1/` | 多次更新 | 1.1M | aitown port 阶段 publishable run |
| `20260513_051605_preflight_1000agent_smoke/` | 2026-05-13 | 3M (slim) | 1000-agent preflight 18 seed × 1 day baseline。**仅 metric JSON，移除 18 × 7MB position trace** 以避免仓库膨胀 |

总计仓库内 ~18MB。

## 未纳入（本地存在但不推 GitHub）

- `20260513_054719_d1_prime_3seed_1000agent_14d/` — 5 月 14 日 D1' Gemini full
  rerun **正在跑** (1000 agent × 14 day × 4 variants × Gemini 3.1 Flash Lite)。
  完成后另以 release artifact 形式分享
- `*_smoke/`、`*_test/`、`viz_demo/` 等 demo / capacity / 单 variant 验证 run
  —— 噪声多于价值
- 所有 `seed_*_positions.json` 位置轨迹文件（单文件 7MB+，加起来 100MB+）
  —— 需要轨迹的研究者请联系作者获取或自己 reproduce
- `data/experiments/<dir>/cache/`、`raw_llm/` 等中间产物

## 怎么用

```bash
# 例：复现 B3 sensitivity sweep 结论
ls data/experiments/20260513_032150_sensitivity_0.3/

# 例：读 contest report
cat data/experiments/20260513_032150_sensitivity_0.3/contest.json | jq .

# 自己重跑（需 GEMINI_API_KEY）
python3 tools/run_variant_suite.py --variants baseline,hyperlocal_push \
  --seeds 7 --agents 100 --num-days 3 --phase-days 1,1,1 \
  --mode publishable --use-aitown --aitown-provider gemini \
  --suite-name b3_replication --output-dir data/experiments/
```

## 重要约束

- **D1' OG smoke (20260511_132735_*) 有 home_location bug**，导致 93%
  agent 在街上过夜。结论被 `fix-population-uses-typed-locations` 修复后失效。
  详见 `docs/limitations-ethics.md` 段"旧实验数据局限"
- 所有 publishable run 的 contest.json 含 `reproducibility_lock`
  字段（provider / model / commit / data hash），可在三年后用同样配置复跑
- 所有 run 的 measurement 措辞固定 "evidence consistent / not consistent /
  inconclusive"，禁用 "proved / falsified"
