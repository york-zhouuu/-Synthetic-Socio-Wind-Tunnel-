## Context

最后两个非 face-validity ⚠️ 项需要落地。两者都是 metadata stamping，逻辑相
邻——合成一个 change 减少 ceremony。

## Goals / Non-Goals

**Goals**：
- 7 个 reproducibility 字段全部 stamp 到每个 publishable run
- ethics statement 自动注入到 report.md
- checklist #6/#7 ⚠️ → ✓
- 测试覆盖 hash 计算 + git fallback + ethics 注入

**Non-Goals**：
- 不重构 RunMetrics schema（用 extensions dict 现有 mechanism）
- 不实施 seed_pool 验证逻辑（spec 不要求）
- 不动 face-validity 协议（下个 change）

## Decisions

### D1：rep-lock 字段计算策略

**选择**：每个 hash 用 SHA256，输入是 canonical 字符串：
- `prompt_template_hash`: `hashlib.sha256(_PLAN_PROMPT_TEMPLATE.encode()).hexdigest()`；
  stub 模式下用 `f"stub:{variant_name}"`（spec D3）
- `LANE_COVE_PROFILE_hash`: `hashlib.sha256(LANE_COVE_PROFILE.model_dump_json(sort_keys=True).encode()).hexdigest()`
- `variants_loaded`: `{name: hashlib.sha256(repr(variant_class).encode()).hexdigest()}`
- `code_commit`: `subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()`
  → `OSError` / `CalledProcessError` 时 fallback `"unknown"`
- `model_version`: 由 use_real_llm + provider 决定的 string；stub
  路径 `"stub:v1"`
- `seed_pool`: 直接传入
- `phase_config`: 已有，沿用

### D2：reproducibility helper 独立模块

**选择**：`synthetic_socio_wind_tunnel/metrics/reproducibility.py`，
独立于 metrics/factory.py。

**Why**：未来可能加更多 stamping（如 carryover_hash 等）；保持
factory.py 清爽。

### D3：ethics 文本作为模块常量

**选择**：`synthetic_socio_wind_tunnel/metrics/ethics.py`：

```python
ETHICS_STATEMENT = """\
## Research Posture Statement

> 本项目是探索性研究装置，...
> （8 行 verbatim from research-design Part V）
"""
```

**Why**：
- 避免 doc-code 漂移（research-design 13.md 改了，metrics/ethics.py 也
  改；spec test 验证一致）
- 单一来源：metrics/ethics.py 是 publishable artifact 的法定 ethics
  text
- 文档可以引用 `from synthetic_socio_wind_tunnel.metrics.ethics import
  ETHICS_STATEMENT`

### D4：注入位置

**选择**：在 report.md 的位置：
1. Title (`# {suite_name} ...`)
2. `[unpublishable preview]` banner（如有）
3. Checklist
4. **NEW**: `## Research Posture Statement`（ethics）
5. **NEW**: `### Reproducibility Lock`（7 字段表）
6. trace comment
7. Act 1 onwards

**Rationale**：ethics + rep-lock 都是 metadata，放在 narrative 之前；
reviewer 一打开就看见。

### D5：rep-lock 块格式

**选择**：markdown 表格 + collapsible HTML detail：

```markdown
### Reproducibility Lock

| 字段 | 值 |
|---|---|
| seed_pool | [42, 99] |
| model_version | stub:v1 |
| prompt_template_hash | stub:hyperlocal_push (or sha256...) |
| LANE_COVE_PROFILE_hash | a3f4...8e21 |
| variants_loaded | {baseline: ..., hyperlocal_push: ...} |
| code_commit | 3f5aa23 |
| phase_config | {baseline: 4, intervention: 6, post: 4} |
```

7 字段缺任一 → checklist #6 ⚠️。

### D6：缺值处理

**选择**：每个字段缺失时：
- `code_commit`: `"unknown"`（git 不可用环境如 docker 无 .git）
- 其它字段：抛 ValueError（不应该缺；正常 publishable run 必填）

## Risks / Trade-offs

**[Risk 1] git 不可用环境（如 CI / docker）**
→ subprocess fallback 到 `"unknown"` + warning；不阻塞 publishable run

**[Risk 2] hash 计算开销**
→ sha256 对 ~10KB 输入 < 1ms；可忽略

**[Risk 3] PROFILE 序列化不稳**
→ Pydantic `model_dump_json(sort_keys=True)` 是稳定的；不动字段顺序

**[Risk 4] ethics 文本与 docs 漂移**
→ 测试用：assert ethics.ETHICS_STATEMENT 含关键 keyword "云室" + "dual-use"

**[Risk 5] variant 类 repr 不稳定（pydantic 默认 repr 含字段顺序）**
→ sort by field name；用 `sorted(model.model_dump().items())` 保证稳定

## Migration Plan

1. 新建 `metrics/reproducibility.py` + `metrics/ethics.py`
2. 单元测试 hash + ethics constants
3. 改 `tools/run_variant_suite.py` 调 helper + 塞入 RunMetrics
4. 改 `metrics/report.py::write_markdown` 注入 ethics + rep-lock block
5. 跑 dev smoke 验证 report.md 含两块
6. 全 pytest
7. archive sync

**回滚**：删两个新文件 + git revert metrics/report + tools/run_variant_suite

## Open Questions

1. **Q1**：variants_loaded 的 hash 用 class repr 还是 variant model dump？
   倾向：variant 是 Pydantic `VariantConfig`，用 model_dump_json 稳

2. **Q2**：seed_pool 是 list[int] 还是 set[int]？
   倾向：list（保留顺序，验证可重现性）

3. **Q3**：未来增加 stamp 字段时怎么处理？
   倾向：只追加，不改名/不改顺序；schema 版本号在外（report.md 不依赖
   字段顺序）
