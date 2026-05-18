"""Planner — LLM 驱动的日计划生成与重规划。"""

from __future__ import annotations

import asyncio
import json
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import BaseModel, Field

from .profile import AgentProfile

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.memory.carryover import CarryoverContext


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
# multi-day-simulation: 新增 {carryover_section}（默认空串，不影响单日路径）
_PLAN_PROMPT_TEMPLATE = """\
你是 {name}，{age}岁，职业是{occupation}。
你住在 {home_location}。

人格特征（0.0 保守 / 0.5 中性 / 1.0 极端，用来指导你的选择）：
{personality_block}

{life_patterns_section}

你的兴趣: {interests}

今天是 {date} ({day_of_week})，天气是 {weather}。
{carryover_section}
请生成你今天的日程计划，从 {wake_time} 到 {sleep_time}。
社区中可用的地点: {available_locations}

请用 XML 格式输出今天的日程，结构如下：

<plan>
  <step>
    <time>8:00</time>
    <destination>cafe_main</destination>
    <action>visit cafe to read</action>
    <duration>30</duration>
    <social>open_to_chat</social>
  </step>
  ...
</plan>

字段说明：
- <time>：开始时刻（如 "8:00"），必填
- <destination>：目标地点 ID（必须取自上面列出的可用地点）
- <action>：自由描述你要做什么（如 "visit"/"work"/"go home"/"chat with neighbor"）
- <duration>：分钟数（整数）
- <social>：你的社交倾向（如 "alone"/"open"/"seeking_company"/"private"）

只输出 <plan>...</plan>，不要其他内容。
"""


# multi-day-simulation: 防 prompt 爆炸
_CARRYOVER_MAX_CHARS = 1500
_SUMMARY_TRUNCATE_CHARS = 300


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _format_carryover_section(carryover) -> str:
    """
    把 CarryoverContext 渲染成 prompt 段落。

    - 三段结构：昨日摘要 / 近 3 日反思 / 未完成任务锚点
    - 若总长超过 _CARRYOVER_MAX_CHARS：对 yesterday_summary.summary_text 截断到
      _SUMMARY_TRUNCATE_CHARS
    - carryover=None 或所有字段为空时返回空串（不注入任何段落，单日行为不变）
    """
    if carryover is None:
        return ""

    yesterday = carryover.yesterday_summary
    reflections = carryover.recent_reflections
    tasks = carryover.pending_task_anchors

    if yesterday is None and not reflections and not tasks:
        return ""

    parts: list[str] = ["\n"]

    yest_text = yesterday.summary_text if yesterday else None

    def _render(yest_s: str | None) -> str:
        p: list[str] = []
        if yest_s:
            p.append(f"【昨日经历摘要】\n{yest_s}")
        if reflections:
            lines = ["【近 3 日反思】"]
            for s in reflections:
                snippet = _truncate(s.summary_text.strip().replace("\n", " "), 120)
                lines.append(f"- day {s.date}: {snippet}")
            p.append("\n".join(lines))
        if tasks:
            lines = ["【未完成任务锚点】"]
            for t in tasks:
                snippet = _truncate(t.content.strip().replace("\n", " "), 120)
                lines.append(f"- {snippet}")
            p.append("\n".join(lines))
        p.append(
            "（注：上面是你过去几天的经历；请生成**与历史一致但允许偏离**的"
            "新 plan。）"
        )
        return "\n\n".join(p)

    rendered = _render(yest_text)
    if len(rendered) > _CARRYOVER_MAX_CHARS and yest_text is not None:
        # truncate yesterday 再重渲染
        rendered = _render(_truncate(yest_text, _SUMMARY_TRUNCATE_CHARS))

    return "\n" + rendered + "\n"


# ---------------------------------------------------------------------------
# lightweight-llm-format: synonym map + XML parser
# 把 LLM 自由 action / social_intent 措辞映射到 canonical PlanAction /
# SocialIntent。dispatch 词表（4/3 类）保持不变；spec 不写死表内容。
# ---------------------------------------------------------------------------

_ACTION_SYNONYMS: dict[str, str] = {
    # move
    "move": "move", "go": "move", "go_home": "move", "gohome": "move",
    "goto": "move", "go_to": "move",
    "visit": "move", "travel": "move", "walk": "move", "drive": "move",
    "commute": "move", "head": "move", "head_to": "move", "headto": "move",
    "leave": "move", "depart": "move", "return": "move",
    # stay
    "stay": "stay", "wait": "stay", "rest": "stay", "sleep": "stay",
    "work": "stay", "eat": "stay", "drink": "stay", "read": "stay",
    "study": "stay", "watch": "stay", "cook": "stay", "relax": "stay",
    "write": "stay",
    # interact
    "interact": "interact", "talk": "interact", "chat": "interact",
    "meet": "interact", "greet": "interact", "converse": "interact",
    "discuss": "interact", "socialize": "interact",
    # explore
    "explore": "explore", "wander": "explore", "search": "explore",
    "investigate": "explore", "find": "explore", "look": "explore",
    "discover": "explore", "browse": "explore",
}

_SOCIAL_SYNONYMS: dict[str, str] = {
    "alone": "alone", "private": "alone", "solo": "alone", "by_myself": "alone",
    "open_to_chat": "open_to_chat", "open": "open_to_chat",
    "casual": "open_to_chat", "friendly": "open_to_chat", "open_chat": "open_to_chat",
    "seeking_company": "seeking_company", "social": "seeking_company",
    "looking_for_company": "seeking_company", "wants_company": "seeking_company",
}


def _normalize_action(raw: str) -> str:
    """LLM 自由 action 词 → canonical PlanAction。未知 → 'stay' + log debug。"""
    if not raw:
        return "stay"
    text = raw.strip().lower()
    if text in _ACTION_SYNONYMS:
        return _ACTION_SYNONYMS[text]
    # 取首词试一次（"visit cafe to read note" → "visit"）
    head = text.split()[0] if text.split() else ""
    if head in _ACTION_SYNONYMS:
        return _ACTION_SYNONYMS[head]
    logger.debug("unknown action token: %r", raw)
    return "stay"


def _normalize_social_intent(raw: str) -> str:
    """LLM 自由 social 词 → canonical SocialIntent。未知 → 'alone' + log debug。"""
    if not raw:
        return "alone"
    text = raw.strip().lower()
    if text in _SOCIAL_SYNONYMS:
        return _SOCIAL_SYNONYMS[text]
    head = text.split()[0] if text.split() else ""
    if head in _SOCIAL_SYNONYMS:
        return _SOCIAL_SYNONYMS[head]
    logger.debug("unknown social_intent token: %r", raw)
    return "alone"


def _child_text(elem: ET.Element, tag: str) -> str | None:
    """取首个匹配子元素的 text；缺失返 None。"""
    child = elem.find(tag)
    if child is None or child.text is None:
        return None
    return child.text.strip() or None


def _parse_xml_plan(raw: str) -> list[PlanStep]:
    """
    从 LLM 原始输出（XML）解析 PlanStep 列表。容错：
    - 找不到 <plan> 根 → wrap 后重试
    - 解析失败 → 返 []
    - 单 step 缺 <time> → 跳过
    - 缺其它字段 → 用默认值
    - action / social 通过同义词映射
    - LLM 没显式 <activity> → 把 <action> 原文作 activity
    """
    text = (raw or "").strip()
    if not text:
        return []

    # 处理 markdown code block
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3].strip()

    # 截取第一个 < 之后到最后一个 > 之前（去掉模型寒暄）
    lt = text.find("<")
    gt = text.rfind(">")
    if lt > 0 or gt < len(text) - 1:
        if lt != -1 and gt != -1 and gt > lt:
            text = text[lt : gt + 1]

    root: ET.Element | None = None
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        # 尝试 wrap 一层 <plan>
        try:
            root = ET.fromstring(f"<plan>{text}</plan>")
        except ET.ParseError:
            return []

    if root is None:
        return []

    # root 可能本身是 <plan>，也可能是单个 <step>（被我们 wrap 过则 root=plan）
    if root.tag.lower() == "step":
        step_elements = [root]
    else:
        step_elements = root.findall(".//step")

    steps: list[PlanStep] = []
    for elem in step_elements:
        time_text = _child_text(elem, "time")
        if not time_text:
            logger.debug("xml step missing <time>, skipping")
            continue

        action_raw = _child_text(elem, "action") or ""
        social_raw = _child_text(elem, "social") or _child_text(elem, "social_intent") or ""
        destination = _child_text(elem, "destination")
        duration_text = _child_text(elem, "duration") or _child_text(elem, "duration_minutes")
        activity_text = _child_text(elem, "activity")
        reason_text = _child_text(elem, "reason") or ""

        try:
            duration = int(duration_text) if duration_text else 30
        except (ValueError, TypeError):
            duration = 30

        canonical_action = _normalize_action(action_raw)
        canonical_social = _normalize_social_intent(social_raw)

        # LLM 原始措辞保留到 activity（D5）
        activity_final = activity_text if activity_text else action_raw

        try:
            steps.append(PlanStep(
                time=time_text,
                action=canonical_action,
                destination=destination,
                activity=activity_final,
                duration_minutes=duration,
                reason=reason_text,
                social_intent=canonical_social,
            ))
        except (ValueError, TypeError) as exc:
            logger.debug("xml step build failed: %s", exc)
            continue

    return steps


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
        carryover: "CarryoverContext | None" = None,
    ) -> DailyPlan:
        """
        调用 LLM 生成一天的计划。

        multi-day-simulation: `carryover` 非 None 时，prompt 额外包含"昨日
        摘要 / 近 3 日反思 / 未完成任务"三段；字符数 cap 1500，yesterday
        summary 过长时截断到 300 字符。carryover=None 时 prompt 与单日
        路径完全一致（向后兼容）。
        """

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
            carryover_section=_format_carryover_section(carryover),
        )

        # capability 1.9 (2026-05-19): hard timeout (60s — daily plan is
        # called once per agent per day; expensive but not latency-critical).
        try:
            raw = await asyncio.wait_for(
                self._llm.generate(prompt, model=profile.base_model),
                timeout=60.0,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "generate_daily_plan timed out (>60s) for %s — empty plan",
                profile.agent_id,
            )
            return DailyPlan(agent_id=profile.agent_id, date=date, steps=[])
        steps = _parse_xml_plan(raw)
        if not steps:
            # fallback：LLM 偶尔吐 JSON，保留旧 parser
            steps = self._parse_plan(raw)

        return DailyPlan(agent_id=profile.agent_id, date=date, steps=steps)

    @staticmethod
    def _parse_plan(raw: str) -> list[PlanStep]:
        """
        Deprecated（lightweight-llm-format）：旧 JSON parser。仅作 fallback；
        XML parser (`_parse_xml_plan`) 是主路径。
        """
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
        *,
        perceptual_context: Any = None,
    ) -> tuple[DailyPlan, bool]:
        """
        基于 interrupt_ctx 触发事件 + recent memories，替换当前 plan 的
        未来 steps（保留已走过的）。

        - 1 次 LLM 调用。
        - LLM 失败 / 解析失败 → fallback 返回 `(原 plan 副本, changed=False)`，不抛。
        - 成功改 plan → `(new_plan, changed=True)`。

        返回值变更（B7 修复）：tuple[DailyPlan, bool]，第二个元素表示
        plan 是否真的被改了。下游 metric counter 据此分流计入
        `replan_count` (changed=True) / `replan_no_op_count` (changed=False)。
        """
        if current_plan is None:
            # 没有当前 plan，replan 退化为 generate_daily_plan 场景——超出
            # 本 change 范围；返回空 plan 让上层处理
            return DailyPlan(agent_id=profile.agent_id, date="", steps=[]), False

        # 构造 prompt — 新 ctx 键 (current_step / current_location_kind /
        # nearby_agents) 缺失时整块在 prompt 中省略，旧 caller 依然可以工作
        trigger_event = interrupt_ctx.get("trigger_event")
        recent_memories = interrupt_ctx.get("recent_memories", [])
        current_time = interrupt_ctx.get("current_time")
        current_step = interrupt_ctx.get("current_step")
        current_location_kind = interrupt_ctx.get("current_location_kind")
        nearby_agents = interrupt_ctx.get("nearby_agents")
        prompt = _build_replan_prompt(
            profile=profile,
            current_plan=current_plan,
            trigger_event=trigger_event,
            recent_memories=recent_memories,
            current_time=current_time,
            current_step=current_step,
            current_location_kind=current_location_kind,
            nearby_agents=nearby_agents,
            perceptual_view=perceptual_context,
        )

        try:
            # capability 1.9 (2026-05-19): hard timeout (30s — replan is
            # interactive, must not deadlock tick scheduling).
            raw = await asyncio.wait_for(
                self._llm.generate(prompt, model=profile.base_model),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            logger.warning("replan timed out (>30s) for %s", profile.agent_id)
            return current_plan.model_copy(deep=True), False
        except Exception as exc:
            logger.warning("replan_failed: LLM error: %s", exc)
            return current_plan.model_copy(deep=True), False

        new_future_steps = _parse_xml_plan(raw)
        if not new_future_steps:
            # fallback：LLM 偶尔吐 JSON
            new_future_steps = self._parse_plan(raw)
        if not new_future_steps:
            logger.warning(
                "replan_failed: empty / invalid plan from LLM. raw=%r", raw[:500]
            )
            return current_plan.model_copy(deep=True), False

        # D.2 修复：LLM 可能吐出早于 current_time 的 step.time，
        # AgentRuntime._current_step_expired 会自动 advance 跳过 → agent 静默忽略。
        # 这里 parse 后保底重写：任何 step.time < current_time 的，改写为
        # current_time + 1 分钟。
        if current_time is not None:
            new_future_steps = [
                _ensure_future_step_time(step, current_time) for step in new_future_steps
            ]

        # 保留已走过的 steps，替换未来部分
        kept = current_plan.steps[: current_plan.current_step_index]
        merged = kept + new_future_steps
        new_plan = DailyPlan(
            agent_id=profile.agent_id,
            date=current_plan.date,
            steps=merged,
            current_step_index=current_plan.current_step_index,
        )
        # changed=True only if the merged plan differs from current.
        # current_plan.steps is a list of PlanStep; equality compared element-wise.
        changed = list(merged) != list(current_plan.steps)
        return new_plan, changed


def _ensure_future_step_time(step: "PlanStep", current_time) -> "PlanStep":
    """
    如果 step.time 早于 current_time（或不可解析），rewrite 为
    current_time + 1 分钟，让 AgentRuntime._current_step_expired 不会
    立刻判它为过期。

    D.2 修复。
    """
    from datetime import timedelta

    time_str = step.time or ""
    try:
        hour_str, minute_str = time_str.split(":", 1)
        hour = int(hour_str)
        minute = int(minute_str)
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError
        step_dt = current_time.replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
    except (ValueError, AttributeError):
        step_dt = None

    if step_dt is None or step_dt < current_time:
        safe_dt = current_time + timedelta(minutes=1)
        safe_time_str = f"{safe_dt.hour}:{safe_dt.minute:02d}"
        return step.model_copy(update={"time": safe_time_str})
    return step


def _build_replan_prompt(
    *,
    profile: AgentProfile,
    current_plan: DailyPlan,
    trigger_event: Any,
    recent_memories: list,
    current_time: Any,
    current_step: Any = None,
    current_location_kind: str | None = None,
    nearby_agents: list | None = None,
    perceptual_view: Any = None,
) -> str:
    """Replan prompt：对称 context window 装配。

    realism-attention-rebalance：push 不再被语言学特殊化为"打断者"，与
    physical / memory / nearby / 人格 / 计划并列为同级 context block。
    空 block 整块省略。

    Block 顺序：
      【现在】 / 【正在做】 / 【周围】 / 【最近发生】 / 【手机】 / 【环境】 / 【接下来计划】

    realism-perception-loop（A1）：当 perceptual_view (SubjectiveView) 非
    空时，在【手机】之后插入【环境】block 描述 agent 看见 / 听见 / 闻到的
    具体场景。空时整块省略，保持现有 prompt structure 测试不破。
    """
    blocks: list[str] = []

    # 【现在】 — 时间 + 当前 location 类型（kind 缺省时省略 location 部分）
    now_parts = [f"时间 {current_time}"]
    if current_location_kind and current_location_kind != "other":
        now_parts.append(f"地点类型 {current_location_kind}")
    blocks.append("【现在】" + "；".join(now_parts))

    # 【正在做】 — 当前 step 信息（无 step 时省略整块）
    if current_step is not None:
        activity = (
            getattr(current_step, "activity", None)
            or getattr(current_step, "action", "")
        )
        duration = getattr(current_step, "duration_minutes", 0)
        social = getattr(current_step, "social_intent", "")
        line = f"【正在做】{activity}（{duration} 分钟"
        if social:
            line += f"，{social}"
        line += "）"
        blocks.append(line)

    # 【周围】 — nearby_agents 列表（空时整块省略）
    if nearby_agents:
        familiar = sum(1 for n in nearby_agents if getattr(n, "is_familiar", False))
        stranger = len(nearby_agents) - familiar
        parts = []
        if familiar:
            parts.append(f"{familiar} 个认识的人")
        if stranger:
            parts.append(f"{stranger} 个陌生人")
        blocks.append("【周围】" + "、".join(parts))

    # 【最近发生】 — recent memories（空时整块省略）
    memory_lines: list[str] = []
    for m in recent_memories[-10:] if recent_memories else []:
        content = getattr(m, "content", str(m))
        memory_lines.append(f"- {content}")
    if memory_lines:
        blocks.append("【最近发生】\n" + "\n".join(memory_lines))

    # 【手机】 — 推送内容（空时整块省略）
    if trigger_event is not None:
        content = getattr(trigger_event, "content", "")
        if content:
            blocks.append(f"【手机】{content}")

    # 【环境】 — agent 看见/听见/闻到的场景（A1 / realism-perception-loop）
    if perceptual_view is not None:
        from synthetic_socio_wind_tunnel.perception.prose import (
            render_subjective_view_prose,
        )
        prose = render_subjective_view_prose(perceptual_view)
        if prose:
            blocks.append(f"【环境】{prose}")

    # 【接下来计划】 — 剩余 steps（空时整块省略）
    remaining = current_plan.steps[current_plan.current_step_index:]
    remaining_lines = [
        f"- {s.time} → {s.destination or '-'} ({s.activity or s.action}) "
        f"[{s.duration_minutes}min, {s.social_intent}]"
        for s in remaining
    ]
    if remaining_lines:
        blocks.append("【接下来计划】\n" + "\n".join(remaining_lines))

    context_section = "\n\n".join(blocks)

    return f"""\
你是 {profile.name}。

{_format_personality_block(profile)}

{context_section}

综合以上所有信息，你会调整接下来的计划吗？如果不调整，按原计划复述；
如果调整，给出新的步骤。

请用 XML 格式输出：

<plan>
  <step>
    <time>7:35</time>
    <destination>cafe_main</destination>
    <action>visit cafe to chat</action>
    <duration>30</duration>
    <social>open_to_chat</social>
  </step>
  ...
</plan>

字段说明：
- <time>：开始时刻，必须 >= 当前时刻 {current_time}
- <destination>：目标 location（可选）
- <action>：自由描述（如 "visit"/"work"/"go home"）
- <duration>：持续分钟
- <social>：社交倾向（如 "alone"/"open"/"seeking_company"）

只输出 <plan>...</plan>，不要其他内容。
"""
