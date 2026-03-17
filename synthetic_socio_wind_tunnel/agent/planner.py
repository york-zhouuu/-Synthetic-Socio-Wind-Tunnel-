"""Planner — LLM 驱动的日计划生成与重规划。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field

from .profile import AgentProfile


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
    action: str                              # "move" / "stay" / "interact" / "explore"
    destination: str | None = None           # location_id
    activity: str = ""                       # "commuting" / "working" / "having_coffee"
    duration_minutes: int = 30               # 预计持续时间
    reason: str = ""                         # "daily commute"
    social_intent: str = "alone"             # "alone" / "open_to_chat" / "seeking_company"


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
_PLAN_PROMPT_TEMPLATE = """\
你是 {name}，{age}岁，职业是{occupation}。
你住在 {home_location}。

{personality_description}

{life_patterns_section}

你的兴趣: {interests}

今天是 {date} ({day_of_week})，天气是 {weather}。

请生成你今天的日程计划，从 {wake_time} 到 {sleep_time}。
社区中可用的地点: {available_locations}

输出一个 JSON 数组，每条包含:
- time: 开始时间 (如 "7:00")
- action: "move" / "stay" / "interact" / "explore"
- destination: 目标地点 ID (必须是上面列出的地点之一)
- activity: 正在做什么
- duration_minutes: 预计持续分钟数
- reason: 为什么做这件事
- social_intent: "alone" / "open_to_chat" / "seeking_company"

只输出 JSON 数组，不要其他内容。
"""


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
            personality_description=profile.personality_description or "（无特别描述）",
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
