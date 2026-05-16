# setup-content-cache shipped · 2026-05-16

## TL;DR

D2 续跑 attempt 3（2026-05-16，4 worker × 500 protag 并发）暴露 setup phase
LLM 生成的灾难性失败——`[aitown] life_history: 0 events across 500 protag`，
500 个虚构居民里 0 个有 backstory，publishable 数据等于 garbage。

本 change（`setup-content-cache`）从根上解决：**把幂等 + 一次性的 setup
LLM 内容搬到 publishable run 之前的离线慢喷脚本里**——

- 新增 `SimulationContentCache` Pydantic frozen 模型 + per-seed JSON 文件
  (`data/setup_content_cache/seed_<N>.json`)
- 新增 `tools/prewarm_setup_content.py` CLI（默认 concurrency=4，慢喷模式）
- `tools/run_variant_suite.py` setup phase 改 cache-aware：HIT = 0 LLM；
  MISS = 在线生成 + 落盘（兜底）
- `life_history` ABCD 升级：n_records 10→20、tier sonnet、retry 2 次、
  prompt v2（注入 Lane Cove 地标 + home_location + 显式"提及地标+时间"要求）
- 新增 `identity_text` 生成路径（同 cache 路径，150-200 字第一人称中文）

**78 个新增 test，全 pass + 0 回归**。fitness audit 5/5 PASS。

## 设计要点

- **缓存粒度 = per-seed**：一文件一 seed，便于人工 spot-check 和 per-seed
  重跑。不做 per-protag 增量 merge，partial coverage 直接 invalidate 重生成
  （cache 是离线产出物，重跑比 merge 简单）
- **schema_version 显式**：未来加字段（emotional_valence /
  related_agent_id）走 invalidate-and-regenerate，不做向后兼容
- **HIT 路径零 LLM**：suite 跑起来 setup phase 几乎瞬完成，彻底消除并发
  突发模式
- **MISS 路径自动落盘**：兜底逻辑保证就算没预热也能跑（只是慢），下次就是 HIT
- **fallback_to_template=True**：LLM 三次失败后用 archetype 模板的 fallback
  records，绝不出现 0-event protag。失败的 agent_id 计入 `failed_protag`
  字段做 audit trail

## 实现要点

| 模块 / 文件 | 角色 |
|---|---|
| `synthetic_socio_wind_tunnel/data_loader/setup_cache.py` | `SimulationContentCache` 模型 + load/save/is_complete |
| `synthetic_socio_wind_tunnel/data_loader/lanecove.py` | `_LIFE_HISTORY_PROMPT_TEMPLATES`（v1/v2）+ `NEIGHBORHOOD_LANDMARKS` + `_IDENTITY_TEXT_PROMPT_TEMPLATES` + `_generate_identity_text_for_one` + retry/fallback 路径 |
| `tools/prewarm_setup_content.py` | CLI: seed range parser、dry-run、--force、skip-existing、退出码 0/1/2 |
| `tools/run_variant_suite.py` | `_load_or_generate_setup_content` cache-aware + setup phase wiring + identity_text 注入 runtime profile |
| `synthetic_socio_wind_tunnel/fitness/audits/setup_content_cache.py` | 5 个 fitness probes |
| `synthetic_socio_wind_tunnel/__init__.py` | 顶层 re-export 4 个公共类型 |

## 测试覆盖

| 测试文件 | 数量 |
|---|---|
| `tests/test_setup_content_cache.py` | 15（cache model / save-load round-trip / schema mismatch / partial coverage / failed_protag 持久化） |
| `tests/test_life_history_retry.py` | 14（retry path / prompt versioning v1/v2 / batch wrapper / fallback template） |
| `tests/test_identity_text_generation.py` | 15（single agent / retry / truncation / markdown fence / batch wrapper / failed protag） |
| `tests/test_prewarm_setup_content_cli.py` | 17（seed range parser / argparse / 退出码 / skip path / dry-run） |
| `tests/test_load_or_generate_setup_content.py` | 4（cache HIT 零 LLM / cache MISS 写盘 / partial cache → MISS / non-protag skip） |
| `tests/test_lanecove_life_history.py` | 13（原有 + 2 个新增 / 已更新接口签名） |
| **总计** | **78 个 test，全 pass** |

### Fitness audit

- `audit_setup_content_cache()`: 5/5 PASS
  - module importable / cache round-trip / is_cache_complete 正确性 /
    prewarm CLI 存在 / suite-wiring 暴露 `_load_or_generate_setup_content`

### 全量回归

**1567 passed, 2 skipped, 1 pre-existing flake** (9 min wall). 唯一 failure
是 `test_run_variant_suite_resume.py::TestSkipPreflightInPublishable::
test_skip_preflight_warned_in_publishable_mode`——subprocess 跑 preflight
超 120 s 测试 timeout，已验证 stash 掉本 change 后仍同样失败，跟本次工作
无关。本 change 0 回归。

### 实际 prewarm wall + cost（TBD）

| seed 数 | wall time | API cost | fallback% | 备注 |
|---|---|---|---|---|
| 10 (42-51) | TBD | TBD | TBD | publishable 默认范围（2026-05-17 β rigor 由 30 → 10） |

### 数据质量 spot check（TBD）

- 随机抽 3 个 protag 看 life_history 内容 → TBD
- 检查是否提及 Lane Cove 具体地标 → TBD
- 检查 title 多样性 → TBD
- 检查 identity_text 自然度 → TBD

## 用法速记

```bash
# 一次性预热（推荐每台新机器跑一次）
python tools/prewarm_setup_content.py
# 估时 45-90 min；写到 data/setup_content_cache/seed_<N>.json

# 单个 seed 排查
python tools/prewarm_setup_content.py --seeds 42

# 慢一点更稳
python tools/prewarm_setup_content.py --concurrency 2 --batch-sleep 0.3

# 看一眼计划但不真的调 LLM
python tools/prewarm_setup_content.py --dry-run -v

# publishable suite — 自动 cache-aware，无需额外操作
python tools/run_variant_suite.py --mode publishable --use-aitown ...
# 看 worker log 找 [setup_cache] HIT for seed=N 行确认走的是 cache
```

## 后续

- 启动 D2 attempt 4（baseline / hp_push / gd / pf 4 个 variant × 10 seed）
  应见 setup phase ~5x 加速 + worker log 全是 cache HIT 行
- 监控 `audit_run_health.py`：与之前一样
- schema_version 演化策略：未来 spec 升级走 `"2"` / `"3"` invalidate path

## 相关 capability

- `run-resilience`（2026-05-15）→ 提供 atomic-write / RetryPolicy /
  HealthAudit 模式
- `tick-level-resume`（2026-05-16）→ 同上，atomic-write 模式复用
- `data-loader-lanecove`（pre-existing）→ life_history / identity_text /
  social_priors 生成本身
