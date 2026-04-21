"""Planner — LLM 驱动的日计划生成与重规划。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from .profile import AgentProfile


# ---------------------------------------------------------------------------
# Typed literals（typed-personality change 引入）
# ---------------------------------------------------------------------------

PlanAction = Literal["move", "stay", "interact", "explore"]
"""Plan step 的 action 类型。LLM 若吐错拼写会在 Pydantic 解析时报错。"""

SocialIntent = Literal["alone", "open_to_chat", "seeking_company"]
"""Plan step 的社交意图。"""


# ---------------------------------------------------------------------------
# LLM Client Protocol — 任何实现了 generate() 的对象都可以注入
# ---------------------------------------------------------------------------

class LLMClient(Protocol):
    async def generate(self, prompt: str, *, model: str = "", **kwargs: Any) -> str:
        """发送 prompt，返回纯文本响应。"""
        ...


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

class PlanStep(BaseModel):
    """计划中的一步。"""
    time: str                                # "7:00"
    action: PlanAction                       # Literal-typed（typed-personality change）
    destination: str | None = None           # location_id
    activity: str = ""                       # "commuting" / "working" / "having_coffee"
    duration_minutes: int = 30               # 预计持续时间
    reason: str = ""                         # "daily commute"
    social_intent: SocialIntent = "alone"    # Literal-typed


class DailyPlan(BaseModel):
    """一天的计划。"""
    agent_id: str
    date: str
    steps: list[PlanStep] = Field(default_factory=list)
    current_step_index: int = 0

    def current(self) -> PlanStep | None:
        if self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return None

    def advance(self) -> PlanStep | None:
        """推进到下一步，返回新的当前步骤。"""
        self.current_step_index += 1
        return self.current()

    def remaining(self) -> list[PlanStep]:
        return self.steps[self.current_step_index:]

    def insert_interrupt(self, step: PlanStep, at_index: int | None = None) -> None:
        """在指定位置插入一个打断步骤。默认插入到当前步骤之后。"""
        idx = at_index if at_index is not None else self.current_step_index + 1
        self.steps.insert(idx, step)


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

# Phase 1 的 prompt 模板 — 精简版，不依赖 Memory (Phase 2 再加)
# typed-personality: {personality_description} → {personality_block}（结构化
# 数值，替换自由描述）
_PLAN_PROMPT_TEMPLATE = """\
你是 {name}，{age}岁，职业是{occupation}。
你住在 {home_location}。

人格特征（0.0 保守 / 0.5 中性 / 1.0 极端，用来指导你的选择）：
{personality_block}

{life_patterns_section}

你的兴趣: {interests}

今天是 {date} ({day_of_week})，天气是 {weather}。

请生成你今天的日程计划，从 {wake_time} 到 {sleep_time}。
社区中可用的地点: {available_locations}

输出一个 JSON 数组，每条包含:
- time: 开始时间 (如 "7:00")
- action: 必须为 "move" / "stay" / "interact" / "explore" 之一（拼写准确）
- destination: 目标地点 ID (必须是上面列出的地点之一)
- activity: 正在做什么
- duration_minutes: 预计持续分钟数
- reason: 为什么做这件事
- social_intent: 必须为 "alone" / "open_to_chat" / "seeking_company" 之一

只输出 JSON 数组，不要其他内容。
"""


def _format_personality_block(profile: AgentProfile) -> str:
    """把 PersonalityTraits 8 个维度格式化为 prompt 里可读的数值列表。"""
    t = profile.personality
    return (
        f"- 好奇心（对新鲜事物）: {t.curiosity:.2f}\n"
        f"- 日常坚持: {t.routine_adherence:.2f}\n"
        f"- 外向性: {t.extraversion:.2f}\n"
        f"- 开放性: {t.openness:.2f}\n"
        f"- 风险容忍: {t.risk_tolerance:.2f}\n"
        f"- 责任心: {t.conscientiousness:.2f}\n"
        f"- 宜人性: {t.agreeableness:.2f}\n"
        f"- 神经质: {t.neuroticism:.2f}"
    )


class Planner:
    """为 agent 生成和管理日计划。"""

    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client

    async def generate_daily_plan(
        self,
        profile: AgentProfile,
        *,
        date: str,
        day_of_week: str = "monday",
        weather: str = "晴",
        available_locations: list[str] | None = None,
        life_patterns: list[str] | None = None,
    ) -> DailyPlan:
        """调用 LLM 生成一天的计划。"""

        life_section = ""
        if life_patterns:
            life_section = "你的日常生活模式:\n" + "\n".join(
                f"- {p}" for p in life_patterns
            )

        prompt = _PLAN_PROMPT_TEMPLATE.format(
            name=profile.name,
            age=profile.age,
            occupation=profile.occupation,
            home_location=profile.home_location,
            personality_block=_format_personality_block(profile),
            life_patterns_section=life_section,
            interests=", ".join(profile.interests) if profile.interests else "无",
            date=date,
            day_of_week=day_of_week,
            weather=weather,
            wake_time=profile.wake_time,
            sleep_time=profile.sleep_time,
            available_locations=", ".join(available_locations or []),
        )

        raw = await self._llm.generate(prompt, model=profile.base_model)
        steps = self._parse_plan(raw)

        return DailyPlan(agent_id=profile.agent_id, date=date, steps=steps)

    @staticmethod
    def _parse_plan(raw: str) -> list[PlanStep]:
        """从 LLM 原始输出解析 PlanStep 列表。容错处理。"""
        # 尝试提取 JSON 数组
        text = raw.strip()
        # 处理 markdown code block
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3].strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 尝试找到第一个 [ 和最后一个 ]
            start = text.find("[")
            end = text.rfind("]")
            if start != -1 and end != -1:
                try:
                    data = json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    return []
            else:
                return []

        if not isinstance(data, list):
            return []

        steps: list[PlanStep] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                steps.append(PlanStep(
                    time=str(item.get("time", "8:00")),
                    action=str(item.get("action", "stay")),
                    destination=item.get("destination"),
                    activity=str(item.get("activity", "")),
                    duration_minutes=int(item.get("duration_minutes", 30)),
                    reason=str(item.get("reason", "")),
                    social_intent=str(item.get("social_intent", "alone")),
                ))
            except (ValueError, TypeError):
                continue
        return steps

    # ------------------------------------------------------------------
    # Replan (memory change)
    # ------------------------------------------------------------------

    async def replan(
        self,
        profile: AgentProfile,
        current_plan: DailyPlan | None,
        interrupt_ctx: dict[str, Any],
    ) -> DailyPlan:
        """
        基于 interrupt_ctx 触发事件 + recent memories，替换当前 plan 的
        未来 steps（保留已走过的）。

        - 1 次 LLM 调用。
        - LLM 失败 / 解析失败 → fallback 返回原 plan 副本，不抛。
        """
        import logging
        logger = logging.getLogger(__name__)

        if current_plan is None:
            # 没有当前 plan，replan 退化为 generate_daily_plan 场景——超出
            # 本 change 范围；返回空 plan 让上层处理
            return DailyPlan(agent_id=profile.agent_id, date="", steps=[])

        # 构造 prompt
        trigger_event = interrupt_ctx.get("trigger_event")
        recent_memories = interrupt_ctx.get("recent_memories", [])
        current_time = interrupt_ctx.get("current_time")
        prompt = _build_replan_prompt(
            profile=profile,
            current_plan=current_plan,
            trigger_event=trigger_event,
            recent_memories=recent_memories,
            current_time=current_time,
        )

        try:
            raw = await self._llm.generate(prompt, model=profile.base_model)
        except Exception as exc:
            logger.warning("replan_failed: LLM error: %s", exc)
            return current_plan.model_copy(deep=True)

        new_future_steps = self._parse_plan(raw)
        if not new_future_steps:
            logger.warning(
                "replan_failed: empty / invalid plan from LLM. raw=%r", raw[:500]
            )
            return current_plan.model_copy(deep=True)

        # 保留已走过的 steps，替换未来部分
        kept = current_plan.steps[: current_plan.current_step_index]
        merged = kept + new_future_steps
        return DailyPlan(
            agent_id=profile.agent_id,
            date=current_plan.date,
            steps=merged,
            current_step_index=current_plan.current_step_index,
        )


def _build_replan_prompt(
    *,
    profile: AgentProfile,
    current_plan: DailyPlan,
    trigger_event: Any,
    recent_memories: list,
    current_time: Any,
) -> str:
    """Replan prompt：当前 plan + 触发事件 + 最近记忆 + 人格 → 新 future steps。"""
    # trigger_event 是 MemoryEvent（runtime import），这里只读 content / kind
    trigger_desc = ""
    if trigger_event is not None:
        kind = getattr(trigger_event, "kind", "unknown")
        content = getattr(trigger_event, "content", "")
        trigger_desc = f"[{kind}] {content}"

    memory_lines = []
    for m in recent_memories[-10:]:
        content = getattr(m, "content", str(m))
        memory_lines.append(f"- {content}")

    remaining = current_plan.steps[current_plan.current_step_index:]
    remaining_json = json.dumps(
        [s.model_dump() for s in remaining], ensure_ascii=False
    )

    return f"""\
你是 {profile.name}。

{_format_personality_block(profile)}

当前时刻：{current_time}
发生了以下事件，打断了你的计划：
{trigger_desc}

最近的记忆：
{chr(10).join(memory_lines) if memory_lines else '（无）'}

你当前计划里还剩下的步骤：
{remaining_json}

请重新规划从现在起的步骤：基于这个新事件，你会改变行为吗？

输出 JSON 数组（与 DailyPlan.steps 同格式），每条含：
- time: 开始时间（如 "7:35"）
- action: 必须为 "move" / "stay" / "interact" / "explore" 之一
- destination: 目标 location（可选）
- activity: 做什么
- duration_minutes: 持续分钟
- reason: 为什么
- social_intent: "alone" / "open_to_chat" / "seeking_company"

只输出 JSON 数组。
"""
