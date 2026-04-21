## 1. Typed 人格 / 技能 / 情绪模型

- [x] 1.1 创建 `synthetic_socio_wind_tunnel/agent/personality.py`：`PersonalityTraits`（8 字段 + frozen + [0,1] 校验）
- [x] 1.2 同文件：`Skills`（perception / investigation / stealth + frozen + [0,1]）
- [x] 1.3 同文件：`EmotionalState`（guilt / anxiety / curiosity / fear + frozen + [0,1]）
- [x] 1.4 写 `tests/test_personality_models.py`：默认值、frozen、校验、可哈希

## 2. Plan / Household Literal

- [x] 2.1 在 `agent/planner.py`（或 `agent/plan_types.py`）定义 `PlanAction = Literal["move", "stay", "interact", "explore"]`
- [x] 2.2 同处：`SocialIntent = Literal["alone", "open_to_chat", "seeking_company"]`
- [x] 2.3 在 `agent/profile.py` 定义 `Household = Literal["single", "couple", "family_with_kids"]`
- [x] 2.4 `PlanStep.action` / `social_intent` 改 Literal；`AgentProfile.household` 改 Literal
- [x] 2.5 写 `tests/test_plan_literal.py`：合法值接受、非法值被 Pydantic 拒绝
- [x] 2.6 `Planner._parse_plan_response`：确认现有 try/except 能捕获 Literal ValidationError；加日志记录 LLM 原始输出

## 3. AgentProfile 迁移

- [x] 3.1 `agent/profile.py` 移除 `personality_traits: dict[str, float]` / `personality_description: str` / `trait()` 方法
- [x] 3.2 新增 `personality: PersonalityTraits = Field(default_factory=PersonalityTraits)`
- [x] 3.3 保留其它字段；household 改 Literal
- [x] 3.4 写 `tests/test_agent_profile_personality.py`：默认 personality、typed 访问、移除 trait 方法后 AttributeError
- [x] 3.5 更新 `tests/test_agent_phase1.py` / `test_agent_profile_structural.py` / `test_attention_models.py` 等构造 AgentProfile 的测试
- [x] 3.6 更新 `tests/test_agent_intent.py` 的 `_profile` helper

## 4. PopulationProfile / sample_population

- [x] 4.1 在 `agent/population.py` 定义 `PersonalityParams`（8 个 (mean, std) tuple，默认全 (0.5, 0.2)）
- [x] 4.2 `PopulationProfile` 新增 `personality_params: PersonalityParams` 字段，默认 `PersonalityParams()`
- [x] 4.3 `sample_population` 内部：对每 agent 按 `clamp(gauss(μ, σ), 0, 1)` 采样 8 维，构造 `PersonalityTraits`，注入 profile
- [x] 4.4 更新 `LANE_COVE_PROFILE`：personality_params 用默认即可
- [x] 4.5 写 `tests/test_population_personality.py`：curiosity std ≥ 0.15（1000 样本）、seed 复现、边界 clamp

## 5. ObserverContext 迁移

- [x] 5.1 `perception/models.py`：`ObserverContext.skills` / `emotional_state` 改 typed
- [x] 5.2 移除 `get_skill` / `get_emotion` 方法
- [x] 5.3 便利 property `investigation_skill` / `perception_skill` / `guilt_level` / `anxiety_level` 内部改为 typed 访问
- [x] 5.4 更新所有直接构造 `ObserverContext` 的测试（test_observer_context_digital / test_perception / ...）

## 6. perception filters + pipeline 消费 typed

- [x] 6.1 `perception/filters/skill.py`（若存在）改为 `ctx.skills.investigation` 访问
- [x] 6.2 `perception/pipeline.py` 中 `_observe_entity / _observe_item / _check_clues` 等已用 property 的保持；任何残留 `ctx.skills.get(...)` 改 typed
- [x] 6.3 `perception/pipeline.py` 的 `default_renderer` 中 `context.guilt_level > 0.5` 保持（用 property）

## 7. AgentRuntime / Planner 读 typed

- [x] 7.1 `agent/runtime.py::build_observer_context`：skill/emotion 改为构造 Skills(perception=profile.personality. ...) / EmotionalState(curiosity=...) 而不是 dict
- [x] 7.2 `agent/planner.py`：`_PLAN_PROMPT_TEMPLATE` 中 `{personality_description}` 替换为 8 个维度的结构化文本
- [x] 7.3 `Planner._build_prompt`（或相关构造方法）用 `profile.personality.<field>:.2f` 格式化
- [x] 7.4 写 `tests/test_planner_prompt.py`（若不存在则新建）：snapshot prompt 包含 typed 数值

## 8. 公共 API

- [x] 8.1 `synthetic_socio_wind_tunnel/__init__.py` re-export `PersonalityTraits` / `Skills` / `EmotionalState` / `PersonalityParams` / `PlanAction` / `SocialIntent` / `Household`
- [x] 8.2 运行 `python3 -c "from synthetic_socio_wind_tunnel import PersonalityTraits; p = PersonalityTraits(); print(p.curiosity)"` 确认

## 9. 回归 + fitness-audit

- [x] 9.1 跑全量 `python -m pytest tests/ -v`——预期大量 profile 构造点测试要改；全部 PASS
- [x] 9.2 跑 `make fitness-audit`：`profile-distribution` category 应仍 PASS；`digital-profile-variance` 不受影响
- [x] 9.3 在 `fitness/audits/profile.py` 中新增一条探针 `profile.personality-variance`：断言 1000 samples 的 `curiosity` std ≥ 0.15
- [x] 9.4 跑 `make fitness-audit` 确认新探针 PASS

## 10. memory change 衔接

- [x] 10.1 在 `openspec/changes/memory/design.md` 的 D7 末尾追加"**已被 typed-personality 解决**：should_replan 读 `profile.personality.routine_adherence` / `profile.personality.curiosity` typed 字段"
- [x] 10.2 在 `openspec/changes/memory/specs/agent/spec.md` 的 `should_replan` Scenario 中更新示例值为 typed 访问
- [x] 10.3 在 `openspec/changes/memory/design.md` 的 D10 段（MemoryEvent tag 改造）保留原计划——tag 改为结构化字段的工作由 memory change 自己做

## 11. Archive 前

- [x] 11.1 `openspec validate typed-personality` 无错误
- [x] 11.2 smoke demo：`sample_population(LANE_COVE_PROFILE, seed=42)` 打印 5 个 agent 的 personality，观察异质性
- [x] 11.3 文档：`docs/agent_system/10-typed-personality.md`（一页）：列 8 维度 + PlanStep Literal + 迁移前后对照
