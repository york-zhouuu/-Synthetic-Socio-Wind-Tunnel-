# Tasks — setup-content-cache

为 publishable run 提供 setup phase LLM 内容的持久缓存 + 离线慢速预热 +
ABCD 精细化。修今天 D2 attempt 3 暴露的"500 protag 中 0 个有 life_history"
灾难性失败 + 永久消除每跑都重新生成的浪费。

**Chain-Position**: `infrastructure`（与 multi-day-simulation / run-resilience /
tick-level-resume 同位；不引入新主边界）

**前置**：`run-resilience` + `tick-level-resume` 已 archive（用其 atomic-write
模式）；今早提前加的 `_load_or_generate_life_history`（commit 79fd236）会被
扩展为 `_load_or_generate_setup_content`

**下游**：所有 publishable run（D2 attempt 4+ / D3 / 后续）SHALL 先跑 prewarm 再起

## 1. 新建 setup_cache 模块

- [x] 1.1 创建 `synthetic_socio_wind_tunnel/data_loader/setup_cache.py`：
  - `SimulationContentCache` Pydantic frozen model，字段按 spec 定义
  - `_CURRENT_SCHEMA_VERSION = "1"` 常量
  - `load_setup_cache(seed, *, cache_dir=None) -> SimulationContentCache | None`
  - `save_setup_cache(seed, cache, *, cache_dir=None) -> Path`（原子写 .tmp +
    rename）
  - `is_cache_complete(cache, profiles) -> bool`
  - 默认 cache_dir = `<repo_root>/data/setup_content_cache/`
- [x] 1.2 `synthetic_socio_wind_tunnel/data_loader/__init__.py` re-export
  上述 4 个类型 / 函数
- [x] 1.3 单测 `tests/test_setup_content_cache.py`：
  - `test_save_load_round_trip`
  - `test_load_missing_returns_none`
  - `test_load_incompatible_schema_returns_none_with_warning`
  - `test_save_atomic_no_tmp_residue`
  - `test_is_cache_complete_full`
  - `test_is_cache_complete_partial_life_history`
  - `test_is_cache_complete_partial_identity_text`
  - `test_failed_protag_persists_in_cache`

## 2. data_loader/lanecove.py 加 retry + prompt v2

- [x] 2.1 在 `lanecove.py` 加 `_LIFE_HISTORY_PROMPT_TEMPLATES: dict[str, str]`
  - key "v1" = 现有 `_DEFAULT_LIFE_HISTORY_PROMPT_TEMPLATE` 复制
  - key "v2" = 新版（加 `{home_location}` / `{neighborhood_landmarks}` 等
    placeholder + 显式"提及具体地标 + 时间"指令）
- [x] 2.2 加 `_NEIGHBORHOOD_LANDMARKS` 常量（Plaza、Longueville Rd、Greenwich、
  Epping Rd、Mowbray Rd 等核心地标静态 list）
- [x] 2.3 修改 `_generate_life_history_for_one` 签名加：
  - `prompt_version: str = "v2"` 参数
  - `max_retries: int = 2` 参数
  - `tier: Literal["sonnet", "haiku"] = "sonnet"` 参数（影响 model selection）
- [x] 2.4 实现 retry loop：JSON parse 失败 → 同 prompt 重试（含 backoff
  0.5s）最多 max_retries 次；用尽后 fallback 走
  `_load_life_history_templates_for_archetype` 的静态模板
- [x] 2.5 单测 `tests/test_life_history_retry.py`：
  - `test_first_call_fails_then_succeeds`
  - `test_exhausts_retries_returns_empty`
  - `test_unknown_prompt_version_raises`
  - `test_v2_includes_landmarks_in_prompt` + 11 more

## 3. identity_text 生成函数

- [x] 3.1 在 `lanecove.py` 加 `_IDENTITY_TEXT_PROMPT_TEMPLATES: dict[str, str]`
  含 v1 default（~150-200 字第一人称中文）
- [x] 3.2 加 `_generate_identity_text_for_one` 函数（签名按 spec）
- [x] 3.3 加 `generate_identity_text_for_protagonists` 批量函数（与
  `generate_life_history_for_protagonists` 同模式）
- [x] 3.4 实现长度截断（max_chars 截到 ≤ 500，log warning）+ retry 路径 +
  fallback 模板
- [x] 3.5 单测 `tests/test_identity_text_generation.py`：
  - `test_happy_path_returns_text`
  - `test_truncation_when_too_long`
  - `test_exhausts_retries_returns_fallback`
  - `test_protag_only_get_identity` + 11 more

## 4. prewarm_setup_content.py CLI

- [x] 4.1 新建 `tools/prewarm_setup_content.py`：
  - argparse 按 spec 表格定义所有 flag
  - `_parse_seed_range("42-56")` / `_parse_seed_range("42,43,44")` helper
- [x] 4.2 主流程 per seed
- [x] 4.3 退出码逻辑（0/1/2）
- [x] 4.4 集成测试 `tests/test_prewarm_setup_content_cli.py` — 17 tests pass

## 5. suite-wiring 集成

- [x] 5.1 `_load_or_generate_setup_content` 加入 `tools/run_variant_suite.py`
- [x] 5.2 call site 改用新函数 + 把 identity_text 注入 runtime profile
- [x] 5.3 sanity test：`test_run_variant_suite.py` / `test_suite_wiring.py`
  8 passed, 1 skipped — 零回归
- [x] 5.4 新测 `tests/test_load_or_generate_setup_content.py` — 4 tests pass

## 6. 公共 API re-export

- [x] 6.1 `synthetic_socio_wind_tunnel/__init__.py` re-export
  `SimulationContentCache` / `load_setup_cache` / `save_setup_cache` /
  `is_cache_complete`，进 `__all__`
- [x] 6.2 smoke import test 通过

## 7. fitness-audit 探针

- [x] 7.1 新建 `synthetic_socio_wind_tunnel/fitness/audits/setup_content_cache.py`：
  - 5 个探针：module / cache-roundtrip / is-cache-complete / prewarm-cli /
    suite-wiring
  - mitigation_change = "setup-content-cache"
- [x] 7.2 接入 `fitness/audits/__init__.py` + `fitness/audit.py`
- [x] 7.3 直接运行 audit_setup_content_cache() — 5/5 PASS

## 8. 文档

- [x] 8.1 新建 `docs/agent_system/17-setup-content-cache.md`
- [x] 8.2 更新 `.gitignore` 加 `data/setup_content_cache/`
- [x] 8.3 更新 `CLAUDE.md` "关键不变量" 加 setup-content-cache 段

## 9. 性能 & 体积验证

- [ ] 9.1 真跑 `tools/prewarm_setup_content.py --seeds 42-56` 一次完整：
  - 测量 wall time（target ≤ 90 min）
  - 测量 API 成本（target ≤ $10）
  - 测量 fallback 比例（target < 5% / seed）
  - 检查 15 个 cache 文件落地 + size 合理
- [ ] 9.2 手动 spot check 数据质量：
  - 随机抽 3 个 protag 看 life_history 内容
  - 检查是否提及 Lane Cove 具体地标
  - 检查 title 多样性（不全是"搬来 Lane Cove 那天"）
  - 检查 identity_text 自然度
- [ ] 9.3 D2 attempt 4 启动测试：
  - `run_variant_suite.py` setup phase 应快 5 倍以上（cache HIT）
  - worker log 应含 `[setup_cache] HIT for seed=N` 行

## 10. 验证 & 归档准备

- [ ] 10.1 `openspec validate setup-content-cache --strict` 通过
- [ ] 10.2 全量 `pytest tests/` 0 回归 + 新增 ~30 test 全 pass
- [ ] 10.3 grep 一致性：`SimulationContentCache` / `load_setup_cache` /
  `_load_or_generate_setup_content` 在 spec / 代码 / 测试三处一致
- [ ] 10.4 所有 ADDED Requirement 至少一个 Scenario 有对应 test
- [ ] 10.5 准备 `docs/sessions/2026-05-16-setup-content-cache-shipped.md`
  ship doc（含 D2 attempt 3 失败 + prewarm 实测 wall time + cache 数据样本）
