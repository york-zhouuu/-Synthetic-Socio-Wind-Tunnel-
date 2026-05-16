"""
Lane Cove community data loader — turn curated public-source records into
protagonist memory + identity injections.

Two datasets currently under `data/lanecove/`:

1. `shared_memories.json` — 12 community-level events (run-start memory inject)
2. `archetypes.json` — 7 resident persona templates (sample-time identity grounding)

The on-disk schema for shared_memories.json is:

    {
      "_meta": {...},
      "memories": [
        {"id": str, "title": str, "content": str, "year": int,
         "category": str, "salience": float, "source_urls": [str],
         "tags": [str], "uncertain": bool},
        ...
      ]
    }

`inject_shared_memories_for_protagonists` writes one MemoryEvent per
(record × protagonist) into MemoryService at run-start. Each event:
- kind="shared_memory"
- importance = record.salience (0-1)
- urgency = 0.0 (not a replan trigger)
- tick = -1 (pre-sim sentinel; matches daily_summary convention)
- day_index = -1
- simulated_time = a stable backdated stamp (record.year-July-1) — gives
  retrieval recency some signal without burying real action memories
- tags = (record.category,) + tuple(record.tags)
- event_id = f"shared_{record.id}_{agent_id}"  -- deterministic, idempotent

Idempotency: re-running the injection is a no-op (event_id collision is
caught by MemoryStore.append → silently skipped). Same shared memory
won't be duplicated across multiple sim runs sharing one MemoryService.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from synthetic_socio_wind_tunnel.memory.models import MemoryEvent

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.agent.profile import AgentProfile
    from synthetic_socio_wind_tunnel.memory.service import MemoryService


logger = logging.getLogger(__name__)


# Default location of the curated dataset, relative to the repo root.
_DEFAULT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data" / "lanecove" / "shared_memories.json"
)


@dataclass(frozen=True)
class SharedMemoryRecord:
    """In-memory representation of one entry in shared_memories.json."""

    id: str
    title: str
    content: str
    year: int
    category: str
    salience: float
    source_urls: tuple[str, ...]
    tags: tuple[str, ...]
    uncertain: bool = False

    def as_memory_content(self) -> str:
        """Render to MemoryEvent.content. Title acts as headline; content
        body provides detail. LLM prompts read the full string verbatim,
        so we keep it tight: '<title> — <content>'."""
        return f"{self.title} — {self.content}"

    def stable_simulated_time(self) -> datetime:
        """Backdate to mid-year of the record's year so retrieval's
        recency dimension has a meaningful (but old) anchor. Year-clamped
        to [1990, 2100] for safety."""
        y = max(1990, min(2100, self.year))
        return datetime(y, 7, 1, 12, 0, 0)


# ---------------------------------------------------------------------------


def load_shared_memories(
    path: Path | str | None = None,
) -> list[SharedMemoryRecord]:
    """Load and validate `shared_memories.json`.

    Returns records sorted by descending salience (highest-importance
    first), so callers iterating top-N pick the most-recognizable ones.
    """
    target = Path(path) if path is not None else _DEFAULT_PATH
    if not target.exists():
        raise FileNotFoundError(
            f"shared_memories.json not found at {target}; "
            f"run `tools/refresh_lanecove_data.py` or pass an explicit path"
        )
    raw = json.loads(target.read_text(encoding="utf-8"))
    entries = raw.get("memories", [])
    out: list[SharedMemoryRecord] = []
    for i, e in enumerate(entries):
        try:
            rec = SharedMemoryRecord(
                id=str(e["id"]),
                title=str(e["title"]),
                content=str(e["content"]),
                year=int(e["year"]),
                category=str(e.get("category", "other")),
                salience=float(e.get("salience", 0.5)),
                source_urls=tuple(e.get("source_urls") or ()),
                tags=tuple(e.get("tags") or ()),
                uncertain=bool(e.get("uncertain", False)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "shared_memories[%d] malformed (%r); skipping entry: %r",
                i, exc, e,
            )
            continue
        if not (0.0 <= rec.salience <= 1.0):
            logger.warning(
                "shared_memory %r salience %.3f out of [0,1]; clamping",
                rec.id, rec.salience,
            )
            rec = SharedMemoryRecord(
                **{**rec.__dict__, "salience": max(0.0, min(1.0, rec.salience))}
            )
        out.append(rec)
    out.sort(key=lambda r: r.salience, reverse=True)
    return out


# ---------------------------------------------------------------------------


def _record_to_memory_event(
    record: SharedMemoryRecord,
    *,
    agent_id: str,
) -> MemoryEvent:
    """Build a single MemoryEvent for `agent_id` from `record`."""
    return MemoryEvent(
        event_id=f"shared_{record.id}_{agent_id}",
        agent_id=agent_id,
        tick=-1,                              # pre-sim sentinel
        simulated_time=record.stable_simulated_time(),
        kind="shared_memory",
        content=record.as_memory_content(),
        urgency=0.0,
        importance=record.salience,
        tags=(record.category,) + record.tags,
        day_index=-1,
    )


def inject_shared_memories_into_agent(
    agent_id: str,
    records: Iterable[SharedMemoryRecord],
    *,
    memory_service: "MemoryService",
    skip_uncertain: bool = False,
) -> int:
    """Write one MemoryEvent per record into `agent_id`'s memory store.

    Returns the count of events actually written. Idempotent — calling
    twice does NOT double-write (deterministic event_id + MemoryStore
    dedup).

    Args:
        agent_id: target agent id (typically a protagonist)
        records: shared memory records to inject
        memory_service: receives the events
        skip_uncertain: when True, records with `uncertain=True` are
            skipped (useful for `--strict` runs)
    """
    written = 0
    existing = {e.event_id for e in memory_service.all_for(agent_id)}
    for r in records:
        if skip_uncertain and r.uncertain:
            continue
        ev = _record_to_memory_event(r, agent_id=agent_id)
        if ev.event_id in existing:
            continue
        memory_service.record(agent_id, ev)
        existing.add(ev.event_id)
        written += 1
    return written


def inject_shared_memories_for_protagonists(
    profiles: Iterable["AgentProfile"],
    records: Iterable[SharedMemoryRecord],
    *,
    memory_service: "MemoryService",
    skip_uncertain: bool = False,
) -> dict[str, int]:
    """Inject `records` into the memory store of every protagonist in
    `profiles`. Scripted (is_protagonist=False) agents are skipped —
    they don't run the LLM stack so don't need shared context.

    Returns {agent_id: events_written}.
    """
    records = list(records)
    out: dict[str, int] = {}
    for p in profiles:
        if not p.is_protagonist:
            continue
        out[p.agent_id] = inject_shared_memories_into_agent(
            p.agent_id, records,
            memory_service=memory_service,
            skip_uncertain=skip_uncertain,
        )
    return out


__all__ = [
    "SharedMemoryRecord",
    "ArchetypeRecord",
    "ConversationTopicRecord",
    "LifeHistoryRecord",
    "SocialPriorRule",
    "PriorTieRecord",
    "load_shared_memories",
    "load_archetypes",
    "load_conversation_topics",
    "load_social_prior_rules",
    "match_archetype",
    "compute_social_priors_for_population",
    "inject_shared_memories_into_agent",
    "inject_shared_memories_for_protagonists",
    "generate_life_history_for_protagonists",
    "inject_life_history",
    # setup-content-cache (2026-05-16)
    "generate_identity_text_for_protagonists",
    "NEIGHBORHOOD_LANDMARKS",
]


# ===========================================================================
# Conversation topics — Lane Cove hyperlocal discussion seeds (B4)
# ===========================================================================

_DEFAULT_CONVERSATION_TOPICS_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data" / "lanecove" / "conversation_topics.json"
)


@dataclass(frozen=True)
class ConversationTopicRecord:
    """One Lane Cove hyperlocal discussion topic for grounding LLM dialogues."""

    topic_id: str
    label: str
    snippet: str
    polarity: str = "neutral"
    source: str = ""


def load_conversation_topics(
    path: Path | None = None,
) -> tuple[ConversationTopicRecord, ...]:
    """Load Lane Cove conversation topics from JSON.

    Used by `do_something` handler caller (e.g. _setup_aitown_stack) to
    inject `op.args["local_topics"]` so LLM-generated dialogue / actions
    reference real local discourse.
    """
    target = path or _DEFAULT_CONVERSATION_TOPICS_PATH
    if not target.exists():
        return ()
    with target.open(encoding="utf-8") as fh:
        payload = json.load(fh)
    raw_topics = payload.get("topics", [])
    return tuple(
        ConversationTopicRecord(
            topic_id=t.get("topic_id", ""),
            label=t.get("label", ""),
            snippet=t.get("snippet", ""),
            polarity=t.get("polarity", "neutral"),
            source=t.get("source", ""),
        )
        for t in raw_topics
    )


# ===========================================================================
# Archetype templates — Lane Cove resident persona templates (sample-time)
# ===========================================================================

_DEFAULT_ARCHETYPES_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data" / "lanecove" / "archetypes.json"
)


@dataclass(frozen=True)
class ArchetypeRecord:
    """One Lane Cove resident archetype template.

    Used by population.sample_population at generate_identity time:
    each AgentProfile is matched to the best-fitting archetype by ABS
    dimension overlap; that archetype's identity_text_template +
    plan_text_template_examples are then handed to the LLM (or
    deterministically rendered for scripted agents) so the resulting
    persona is grounded in real Lane Cove patterns rather than free-form
    LLM invention.
    """

    archetype_id: str
    label: str
    approx_pct: float
    match_criteria: dict
    personality_bias: dict[str, float]
    digital_bias: dict
    occupation_pool: tuple[str, ...]
    interests_pool: tuple[str, ...]
    identity_text_template: str
    plan_text_template_examples: tuple[str, ...]
    source_urls: tuple[str, ...]
    uncertain: bool = False
    is_fallback: bool = False  # B1 fix: catch-all archetype, used only when no specific match


def load_archetypes(
    path: Path | str | None = None,
) -> list[ArchetypeRecord]:
    """Load archetype templates from `archetypes.json`.

    Returns records in their on-disk order (loosely population-share
    descending). Malformed entries are skipped with a warning.
    """
    target = Path(path) if path is not None else _DEFAULT_ARCHETYPES_PATH
    if not target.exists():
        raise FileNotFoundError(
            f"archetypes.json not found at {target}; "
            f"run `tools/refresh_lanecove_data.py` or pass an explicit path"
        )
    raw = json.loads(target.read_text(encoding="utf-8"))
    entries = raw.get("archetypes", [])
    out: list[ArchetypeRecord] = []
    for i, e in enumerate(entries):
        try:
            rec = ArchetypeRecord(
                archetype_id=str(e["archetype_id"]),
                label=str(e["label"]),
                approx_pct=float(e.get("approx_pct", 0.0)),
                match_criteria=dict(e.get("match_criteria") or {}),
                personality_bias=dict(e.get("personality_bias") or {}),
                digital_bias=dict(e.get("digital_bias") or {}),
                occupation_pool=tuple(e.get("occupation_pool") or ()),
                interests_pool=tuple(e.get("interests_pool") or ()),
                identity_text_template=str(e.get("identity_text_template", "")),
                plan_text_template_examples=tuple(
                    e.get("plan_text_template_examples") or ()
                ),
                source_urls=tuple(e.get("source_urls") or ()),
                uncertain=bool(e.get("uncertain", False)),
                is_fallback=bool(e.get("is_fallback", False)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "archetypes[%d] malformed (%r); skipping entry: %r",
                i, exc, e,
            )
            continue
        out.append(rec)
    return out


def _criterion_match_state(value, allowed) -> str:
    """Three-state match: 'match' / 'mismatch' / 'unknown'.

    - 'unknown' = profile field is None (we can't tell)
    - 'match' = profile value satisfies the allowed set
    - 'mismatch' = profile value is set but NOT in allowed set
    """
    if value is None:
        return "unknown"
    if isinstance(allowed, list):
        return "match" if value in allowed else "mismatch"
    return "match" if value == allowed else "mismatch"


def _criterion_satisfied(value, allowed) -> bool:
    """Backwards-compat wrapper. Returns True only on explicit match."""
    return _criterion_match_state(value, allowed) == "match"


def match_archetype(
    profile,
    archetypes: list[ArchetypeRecord],
) -> ArchetypeRecord | None:
    """Pick the archetype best-fitting `profile` by ABS-dimension overlap.

    Scoring: each match_criteria key that the profile satisfies = 1 point;
    age range = 1 point if profile.age in [min, max]. Highest score wins;
    ties broken by approx_pct (descending — favour high-prevalence
    archetypes for ambiguous profiles).

    Returns None if no archetype scores at least 2 (avoids forcing a
    template onto a profile that doesn't really fit).
    """
    if not archetypes:
        return None

    scored: list[tuple[float, float, ArchetypeRecord]] = []
    for arch in archetypes:
        score = 0.0
        crit = arch.match_criteria

        # Age bracket — HARD constraint (out of range → archetype not viable)
        age_min = crit.get("age_bracket_min")
        age_max = crit.get("age_bracket_max")
        if age_min is not None and age_max is not None:
            if not (age_min <= profile.age <= age_max):
                continue  # skip this archetype entirely
            score += 1.0

        # Field-by-field matches:
        # match → +1, mismatch → -1, unknown → 0.
        # work_mode and housing_tenure are HARD veto when mismatching
        # (they define the archetype's core identity).
        hard_veto_keys = {"work_mode", "housing_tenure"}

        field_pairs = [
            ("housing_tenure", profile.housing_tenure),
            ("community_tenure_5yr", profile.community_tenure_5yr),
            ("work_mode", profile.work_mode),
            ("income_tier", profile.income_tier),
            ("family_composition", profile.family_composition),
            ("dwelling_structure", profile.dwelling_structure),
            ("vehicles_at_dwelling", profile.vehicles_at_dwelling),
            ("year_of_arrival", profile.year_of_arrival_bucket),
            ("english_proficiency", profile.english_proficiency),
            ("education_level", profile.education_level),
            ("volunteer_status", profile.volunteer_status),
            ("household", profile.household),
        ]
        veto = False
        for key, val in field_pairs:
            if key not in crit:
                continue
            state = _criterion_match_state(val, crit[key])
            if state == "match":
                score += 1.0
            elif state == "mismatch":
                if key in hard_veto_keys:
                    veto = True
                    break
                score -= 1.0
        if veto:
            continue

        # Soft criteria — match small + bonus, mismatch no penalty
        if "ethnicity_preference" in crit:
            if _criterion_satisfied(
                profile.ethnicity_group, crit["ethnicity_preference"],
            ):
                score += 0.5

        # unpaid hours — match either child or domestic
        for key in ("unpaid_child_care_hours", "unpaid_domestic_hours"):
            if key in crit:
                pval = getattr(profile, key, None)
                if _criterion_satisfied(pval, crit[key]):
                    score += 0.5

        scored.append((score, arch.approx_pct, arch))

    if not scored:
        return None
    # B1 fix: prefer specific archetypes (is_fallback=False) over catch-all.
    # Specific archetypes still need ≥ 2 score; fallback can match at any
    # score ≥ 1. This avoids the catch-all from out-scoring narrow archetypes
    # by virtue of having broader (and thus more-points) match criteria.
    specifics = [t for t in scored if not t[2].is_fallback]
    fallbacks = [t for t in scored if t[2].is_fallback]

    specifics.sort(key=lambda t: (-t[0], -t[1]))
    if specifics and specifics[0][0] >= 2.0:
        return specifics[0][2]

    fallbacks.sort(key=lambda t: (-t[0], -t[1]))
    if fallbacks and fallbacks[0][0] >= 1.0:
        return fallbacks[0][2]

    return None


# ===========================================================================
# Life history backstory — per-protagonist first-person backstory MemoryEvents
# ===========================================================================
#
# Each protagonist gets ~10 first-person life-history MemoryEvents at sample
# time, generated by one LLM call per protag (asyncio.gather batched). These
# anchor protag retrieval long before any sim event happens — without them,
# day-1 protag has zero past to draw on for dialogue.


import asyncio as _asyncio  # alias to avoid shadowing


@dataclass(frozen=True)
class LifeHistoryRecord:
    """One backstory item — first-person, past-dated."""

    record_id: str
    agent_id: str
    title: str
    content: str
    years_ago: float            # 0.5 → 6 months ago, 8 → 8 years ago
    location_hint: str | None   # optional location_id-like string ("Lane Cove Plaza")
    importance: float           # 0-1
    tags: tuple[str, ...] = ()


_LIFE_HISTORY_TEMPLATES_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data" / "lanecove" / "life_history_templates.json"
)


def _load_life_history_templates_for_archetype(arch_id: str) -> list[str]:
    """B2: load Lane Cove archetype-grounded life-history anchors.

    Returns up to 8 first-person event templates the LLM uses as anchors
    instead of free-form invention. Empty list if file missing or
    archetype not in templates.
    """
    if not _LIFE_HISTORY_TEMPLATES_PATH.exists():
        return []
    try:
        with _LIFE_HISTORY_TEMPLATES_PATH.open(encoding="utf-8") as fh:
            raw = json.load(fh)
        return list(raw.get("templates_by_archetype", {}).get(arch_id, []))
    except Exception:
        return []


# Lane Cove neighborhood landmarks — injected into prompt v2 for grounded stories.
# These are real, recognizable places. LLM SHALL mention specific ones (not just "Lane Cove").
NEIGHBORHOOD_LANDMARKS: tuple[str, ...] = (
    "Lane Cove Plaza",
    "Longueville Road",
    "Epping Road",
    "Pacific Highway",
    "Mowbray Road",
    "Greenwich",
    "Stringybark Creek",
    "Lane Cove West Public School",
    "Lane Cove North",
    "Lane Cove Tunnel",
    "Burns Bay Road",
    "Lane Cove Country Club",
    "Canopy Park",
    "Gallery Lane Cove",
    "St Leonards (commute destination)",
    "Chatswood (commute destination)",
    "Crows Nest Metro (under construction)",
)


_LIFE_HISTORY_PROMPT_V1 = """\
你是 Lane Cove (Sydney NSW 2066) 城市模拟的人物背景作者。请为下面这位 \
agent 写 {n_records} 条第一人称的过去经历（life history backstory），让 \
ta 在 day 0 走进模拟时已经有"我经历过的事"可以聊。

=== Agent ===
- 姓名：{name}
- 年龄：{age}
- 职业：{occupation}
- 身份描述：{identity_text}
- 今天的计划：{plan_text}
- archetype: {archetype_label}（{archetype_id}）
- LifePattern: 偏好 cafe={preferred_cafe}, leisure_park={preferred_leisure_park}, \
weekend={weekend_outing}

=== Life-event anchors (Lane Cove-grounded; vary on these) ===
{life_event_anchors}

=== 输出要求 ===
**只输出 JSON**，no prose, no markdown fence。Schema:
[
  {{
    "title": "短中文 label，≤15 字",
    "content": "1-2 句中文第一人称叙述（'我'开头），描述具体场景 / 感受 / 后续",
    "years_ago": <float 0.5-15.0>,
    "location_hint": "可选 — 具体 Lane Cove 地点（如 'Lane Cove Plaza' / 'Stringybark Creek' / 'Lane Cove Tunnel' / null）",
    "importance": <float 0-1>,
    "tags": ["self-explanatory tag", ...]
  }},
  ...
]

=== 内容指南 ===
- 总共 {n_records} 条，跨度 0.5-15 年（如果 agent 年龄 < 25，跨度 < age-15）
- 至少 4 类不同：搬家 / 工作 / 关系 (邻居 / 家人 / 友谊) / 本地地点首次去 / \
小事故 / 和 Lane Cove 大事件 (封城 / Crows Nest Metro / Galuwa) 的个人交集
- importance 分层：2-3 条 high (0.75+, 改变 trajectory 的事件) / \
4-5 条 mid (0.4-0.6, 日常但记得清楚) / 2-3 条 low (0.2-0.3, 模糊背景)
- **真实质感**：具体地名、具体年份感（"2021 封城那年" / "刚来 Lane Cove 不久"），\
不要泛化（避免"我有过一段难忘的经历"）
- 与 archetype 一致：通勤白领的 backstory 别全是 council 议程；\
退休志愿者的 backstory 别都是 CBD 加班
- **优先变奏 Life-event anchors 中的事件**（如果提供了），加入具体年份 / 名字 / 细节，\
不要忽略 anchors 直接写其它事——这些 anchors 是 Lane Cove 真实居民的典型经历模板
"""


_LIFE_HISTORY_PROMPT_V2 = """\
你是 Lane Cove (Sydney NSW 2066) 城市模拟的人物背景作者。请为下面这位 \
agent 写 {n_records} 条第一人称的过去经历（life history backstory），让 \
ta 在 day 0 走进模拟时已经有"我经历过的事"可以聊。

=== Agent ===
- 姓名：{name}
- 年龄：{age}
- 职业：{occupation}
- **居住地（home）**：{home_location}
- 身份描述：{identity_text}
- 今天的计划：{plan_text}
- archetype: {archetype_label}（{archetype_id}）
- LifePattern:
  - 常去 cafe：{preferred_cafe}
  - 偏好公园 / 散步处：{preferred_leisure_park}
  - 周末外出地：{weekend_outing}

=== Lane Cove 真实地标参考（用具体名称，不要泛化"Lane Cove"）===
{neighborhood_landmarks}

=== Life-event anchors (Lane Cove-grounded; vary on these) ===
{life_event_anchors}

=== 输出要求 ===
**只输出 JSON**，no prose, no markdown fence。Schema:
[
  {{
    "title": "短中文 label，≤15 字",
    "content": "1-3 句中文第一人称叙述（'我'开头），描述具体场景 / 感受 / 后续",
    "years_ago": <float 0.5-15.0>,
    "location_hint": "**SHALL 非空** — 具体 Lane Cove 地点名（必选自上面 landmarks 或 home_location 周边）",
    "importance": <float 0-1>,
    "tags": ["self-explanatory tag", ...]
  }},
  ...
]

=== 内容指南（v2 强化） ===
- 总共 {n_records} 条，跨度 0.5-15 年（agent 年龄 < 25 时跨度 < age-15）
- **每条 SHALL 提及具体地标 + 具体时间**（年份 / 季节 / 节日，如"2021 封城"、
  "上个春天"、"刚到 Lane Cove 那个冬天"）
- 至少 5 类不同：搬家 / 工作 / 关系（邻居 / 家人 / 友谊）/ 本地地点首次去 /
  小事故 / 与 Lane Cove 大事件（封城 / Crows Nest Metro / Galuwa）的个人交集
- importance 分层：3-4 条 high (0.75+, 改变 trajectory 的事件) /
  8-10 条 mid (0.4-0.6, 日常但记得清楚) / 6-8 条 low (0.2-0.3, 模糊背景)
- **真实质感**：具体地名 + 具体年份 / 季节 + 具体人物或邻居（"那个总在 Plaza
  早晨遛狗的老 Mrs. Chen"）。避免泛化（"我有过一段难忘的经历"）
- 与 archetype 一致：通勤白领的 backstory 别全是 council 议程；
  退休志愿者的 backstory 别都是 CBD 加班
- **优先变奏 Life-event anchors 中的事件**（如有），加入具体年份 / 名字 / 细节
- 多样性要求：本人 {n_records} 条 title SHALL 至少 60% 不重复（避免所有条目都是
  "搬来 Lane Cove 那天"这种）
"""


_LIFE_HISTORY_PROMPT_TEMPLATES: dict[str, str] = {
    "v1": _LIFE_HISTORY_PROMPT_V1,
    "v2": _LIFE_HISTORY_PROMPT_V2,
}

# Backward-compat alias (existing callers / tests reference this name)
_DEFAULT_LIFE_HISTORY_PROMPT_TEMPLATE = _LIFE_HISTORY_PROMPT_V2


async def _generate_life_history_for_one(
    profile,
    *,
    llm_client,
    archetype: ArchetypeRecord | None,
    n_records: int = 20,
    model: str = "",
    prompt_version: str = "v2",
    max_retries: int = 2,
) -> list[LifeHistoryRecord]:
    """Single-agent LLM call. Returns list of LifeHistoryRecord.

    setup-content-cache (2026-05-16) refinements:
    - n_records default 10 → 20
    - prompt_version "v2" default (with NEIGHBORHOOD_LANDMARKS + home_location
      + explicit time-and-landmark mention requirement)
    - max_retries=2: JSON parse failures retry up to N times with 0.5s
      backoff. Total attempts = 1 + max_retries. After exhausting, returns
      empty list — caller (`generate_life_history_for_protagonists`) then
      falls back to a template.

    Failures still return [] for caller-side fallback."""
    if prompt_version not in _LIFE_HISTORY_PROMPT_TEMPLATES:
        raise ValueError(
            f"Unknown prompt_version: {prompt_version!r}. "
            f"Available: {list(_LIFE_HISTORY_PROMPT_TEMPLATES)}",
        )

    arch_label = archetype.label if archetype else "general resident"
    arch_id = archetype.archetype_id if archetype else "none"
    lp = profile.life_pattern
    preferred_cafe = (lp.preferred_cafe if lp else None) or "(无)"
    preferred_park = (lp.preferred_leisure_park if lp else None) or "(无)"
    weekend = (lp.weekend_outing_destination if lp else None) or "(无)"

    # B2: Lane Cove-grounded life-event anchors per archetype.
    anchors = _load_life_history_templates_for_archetype(arch_id)
    anchor_block = (
        "\n".join(f"  - {a}" for a in anchors)
        if anchors
        else "(无 archetype 模板锚点；自由生成)"
    )
    # v2-specific block (ignored by v1 template)
    landmarks_block = "\n".join(f"  - {lm}" for lm in NEIGHBORHOOD_LANDMARKS)

    prompt = _LIFE_HISTORY_PROMPT_TEMPLATES[prompt_version].format(
        n_records=n_records,
        name=profile.name,
        age=profile.age,
        occupation=profile.occupation,
        identity_text=profile.identity_text or "(无)",
        plan_text=profile.plan_text or "(无)",
        archetype_label=arch_label,
        archetype_id=arch_id,
        preferred_cafe=preferred_cafe,
        preferred_leisure_park=preferred_park,
        weekend_outing=weekend,
        home_location=getattr(profile, "home_location", "(unknown)"),
        neighborhood_landmarks=landmarks_block,
        life_event_anchors=anchor_block,
    )

    for attempt in range(max_retries + 1):
        try:
            raw = await llm_client.generate(prompt, model=model)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "life_history LLM call failed for %s (attempt %d/%d): %r",
                profile.agent_id, attempt + 1, max_retries + 1, exc,
            )
            if attempt < max_retries:
                await _asyncio.sleep(0.5)
                continue
            return []

        text = (raw or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text.split("\n", 1)[1] if "\n" in text else ""
        try:
            items = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            logger.warning(
                "life_history LLM returned unparseable JSON for %s "
                "(attempt %d/%d); raw=%r",
                profile.agent_id, attempt + 1, max_retries + 1, text[:200],
            )
            if attempt < max_retries:
                await _asyncio.sleep(0.5)
                continue
            return []
        if not isinstance(items, list):
            if attempt < max_retries:
                await _asyncio.sleep(0.5)
                continue
            return []

        out: list[LifeHistoryRecord] = []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            try:
                rec = LifeHistoryRecord(
                    record_id=f"lh_{profile.agent_id}_{i:02d}",
                    agent_id=profile.agent_id,
                    title=str(item.get("title", "")).strip()[:50],
                    content=str(item.get("content", "")).strip(),
                    years_ago=max(0.1, min(50.0, float(item.get("years_ago", 1.0)))),
                    location_hint=(
                        str(item["location_hint"]).strip()
                        if item.get("location_hint") else None
                    ),
                    importance=max(0.0, min(1.0, float(item.get("importance", 0.5)))),
                    tags=tuple(str(t) for t in item.get("tags", [])[:5]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning(
                    "life_history item %d malformed for %s: %r",
                    i, profile.agent_id, exc,
                )
                continue
            if not rec.content:
                continue
            out.append(rec)
        return out

    # Unreachable (loop returns or breaks)
    return []


async def generate_life_history_for_protagonists(
    profiles: list,
    *,
    llm_client,
    archetypes: list[ArchetypeRecord] | None = None,
    n_records_per_protag: int = 20,
    batch_size: int = 5,
    model: str = "",
    prompt_version: str = "v2",
    max_retries: int = 2,
    fallback_to_template: bool = True,
) -> tuple[dict[str, list[LifeHistoryRecord]], list[str]]:
    """Concurrently LLM-generate life-history records for every protagonist.

    Returns `(records_by_agent_id, failed_protag_ids)`:
    - `records_by_agent_id`: agent_id → list[LifeHistoryRecord]; non-protag
      omitted; protag who exhausted retries get fallback template records
      (or empty list if `fallback_to_template=False`)
    - `failed_protag_ids`: agent_ids that fell back / produced empty (audit)

    setup-content-cache (2026-05-16) defaults:
    - n_records_per_protag: 10 → 20
    - prompt_version="v2", max_retries=2
    - fallback_to_template=True: returns template-based records for failed
      protag instead of empty list, so downstream `inject_life_history`
      never has a 0-event agent
    """
    archetypes = archetypes or []
    indices = [i for i, p in enumerate(profiles) if p.is_protagonist]
    out: dict[str, list[LifeHistoryRecord]] = {}
    failed: list[str] = []
    for batch_start in range(0, len(indices), batch_size):
        batch_idx = indices[batch_start:batch_start + batch_size]
        batch_profiles = [profiles[i] for i in batch_idx]
        batch_archetypes = [
            match_archetype(p, archetypes) if archetypes else None
            for p in batch_profiles
        ]
        results = await _asyncio.gather(*[
            _generate_life_history_for_one(
                p, llm_client=llm_client, archetype=arch,
                n_records=n_records_per_protag, model=model,
                prompt_version=prompt_version, max_retries=max_retries,
            )
            for p, arch in zip(batch_profiles, batch_archetypes)
        ])
        for p, arch, recs in zip(batch_profiles, batch_archetypes, results):
            if not recs:
                failed.append(p.agent_id)
                if fallback_to_template:
                    recs = _fallback_template_life_history(p, arch, n=n_records_per_protag)
            out[p.agent_id] = recs
    return out, failed


def _fallback_template_life_history(
    profile,
    archetype: ArchetypeRecord | None,
    *,
    n: int = 20,
) -> list[LifeHistoryRecord]:
    """Fallback when all LLM attempts fail. Uses archetype templates +
    profile fields to synthesize bare-bones records (no LLM)."""
    arch_id = archetype.archetype_id if archetype else "none"
    anchors = _load_life_history_templates_for_archetype(arch_id)
    if not anchors:
        anchors = [
            f"我搬来 Lane Cove 那年",
            f"在 Plaza 第一次买咖啡",
            f"邻居打招呼的那个早晨",
            f"周末去公园散步",
            f"通勤路上的小插曲",
        ]
    out: list[LifeHistoryRecord] = []
    for i in range(min(n, len(anchors) * 3)):
        anchor = anchors[i % len(anchors)]
        out.append(LifeHistoryRecord(
            record_id=f"lh_{profile.agent_id}_{i:02d}",
            agent_id=profile.agent_id,
            title=anchor[:50],
            content=f"我（{profile.name}, {profile.age} 岁）回忆: {anchor}。",
            years_ago=max(0.5, min(15.0, 0.5 + (i % 10))),
            location_hint="Lane Cove Plaza",
            importance=0.4,
            tags=("fallback_template",),
        ))
    return out


# ---------------------------------------------------------------------------
# identity_text — setup-content-cache (2026-05-16)
# ---------------------------------------------------------------------------

_IDENTITY_TEXT_PROMPT_V1 = """\
你为 Lane Cove (Sydney NSW 2066) 城市模拟中的一位虚构居民写一段约 150-200 字
的第一人称自我介绍（identity_text），让 ta 用平实自然的中文口吻介绍自己。

=== Agent 基本 ===
- 姓名：{name}
- 年龄：{age}
- 职业：{occupation}
- 家庭：{household}
- 居住：{home_location}
- archetype: {archetype_label}（{archetype_id}）

=== Lane Cove 真实地标参考 ===
{neighborhood_landmarks}

=== Life history snippets（已生成的传记片段，用 1-2 条作 anchor） ===
{life_history_snippets}

=== 输出要求 ===
- **只输出纯文本**，no JSON, no markdown
- 单段 150-200 字第一人称中文（"我是 ..., XX 岁, 住在 ..."）
- 提及具体地标 + 当前生活节奏 + 兴趣 / 性格 / 偏好
- 自然口语化，不像简历那样列点
- 与 archetype 风格一致
"""

_IDENTITY_TEXT_PROMPT_TEMPLATES: dict[str, str] = {
    "v1": _IDENTITY_TEXT_PROMPT_V1,
}


async def _generate_identity_text_for_one(
    profile,
    *,
    llm_client,
    archetype: ArchetypeRecord | None,
    life_history_snippets: list[str] | None = None,
    model: str = "",
    prompt_version: str = "v1",
    max_retries: int = 2,
    max_chars: int = 500,
) -> str:
    """Single-agent identity_text generation. Returns ~150-200 字 first-person
    Chinese self-introduction.

    Failures (after retries) fall back to a hand-rolled template string;
    never returns empty."""
    if prompt_version not in _IDENTITY_TEXT_PROMPT_TEMPLATES:
        raise ValueError(
            f"Unknown identity_text prompt_version: {prompt_version!r}",
        )

    arch_label = archetype.label if archetype else "general resident"
    arch_id = archetype.archetype_id if archetype else "none"
    landmarks_block = "\n".join(f"  - {lm}" for lm in NEIGHBORHOOD_LANDMARKS)

    snippets = life_history_snippets or []
    snippets_block = (
        "\n".join(f"  - {s[:80]}" for s in snippets[:3])
        if snippets else "(无)"
    )

    prompt = _IDENTITY_TEXT_PROMPT_TEMPLATES[prompt_version].format(
        name=profile.name,
        age=profile.age,
        occupation=profile.occupation,
        household=getattr(profile, "household", "(unknown)"),
        home_location=getattr(profile, "home_location", "(unknown)"),
        archetype_label=arch_label,
        archetype_id=arch_id,
        neighborhood_landmarks=landmarks_block,
        life_history_snippets=snippets_block,
    )

    for attempt in range(max_retries + 1):
        try:
            raw = await llm_client.generate(prompt, model=model)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "identity_text LLM call failed for %s (attempt %d/%d): %r",
                profile.agent_id, attempt + 1, max_retries + 1, exc,
            )
            if attempt < max_retries:
                await _asyncio.sleep(0.5)
                continue
            return _fallback_identity_text(profile)

        text = (raw or "").strip()
        # Strip markdown wrappers if present
        if text.startswith("```"):
            text = text.strip("`")
            # In case of "```text" or "```\n..." headers
            if "\n" in text:
                first_line, rest = text.split("\n", 1)
                if len(first_line) < 20 and not any(c in first_line for c in "我你他她"):
                    text = rest.strip()

        if not text:
            if attempt < max_retries:
                await _asyncio.sleep(0.5)
                continue
            return _fallback_identity_text(profile)

        # Truncate if overlong
        if len(text) > max_chars:
            logger.warning(
                "identity_text truncated for %s (was %d chars → %d)",
                profile.agent_id, len(text), max_chars,
            )
            text = text[:max_chars]

        return text

    return _fallback_identity_text(profile)


def _fallback_identity_text(profile) -> str:
    """Template-based identity_text when all LLM attempts fail."""
    name = getattr(profile, "name", "(无名)")
    age = getattr(profile, "age", "?")
    occupation = getattr(profile, "occupation", "居民")
    home = getattr(profile, "home_location", "Lane Cove")
    return (
        f"我是 {name}，{age} 岁，{occupation}，住在 {home}。"
        f"我平时在 Lane Cove 一带活动，周末偶尔去 Plaza 或公园走走。"
    )


async def generate_identity_text_for_protagonists(
    profiles: list,
    *,
    llm_client,
    archetypes: list[ArchetypeRecord] | None = None,
    life_history_by_agent: dict[str, list[LifeHistoryRecord]] | None = None,
    batch_size: int = 5,
    model: str = "",
    prompt_version: str = "v1",
    max_retries: int = 2,
    max_chars: int = 500,
) -> tuple[dict[str, str], list[str]]:
    """Concurrent identity_text generation for all protag.

    Returns `(identity_by_agent_id, failed_protag_ids)`. Failed protag
    always have a fallback template string (never empty)."""
    archetypes = archetypes or []
    life_history_by_agent = life_history_by_agent or {}
    indices = [i for i, p in enumerate(profiles) if p.is_protagonist]
    out: dict[str, str] = {}
    failed: list[str] = []

    for batch_start in range(0, len(indices), batch_size):
        batch_idx = indices[batch_start:batch_start + batch_size]
        batch_profiles = [profiles[i] for i in batch_idx]
        batch_archetypes = [
            match_archetype(p, archetypes) if archetypes else None
            for p in batch_profiles
        ]
        batch_snippets = [
            [rec.content for rec in life_history_by_agent.get(p.agent_id, [])[:5]]
            for p in batch_profiles
        ]

        results = await _asyncio.gather(*[
            _generate_identity_text_for_one(
                p, llm_client=llm_client, archetype=arch,
                life_history_snippets=snips, model=model,
                prompt_version=prompt_version, max_retries=max_retries,
                max_chars=max_chars,
            )
            for p, arch, snips in zip(
                batch_profiles, batch_archetypes, batch_snippets,
            )
        ], return_exceptions=True)

        for p, result in zip(batch_profiles, results):
            if isinstance(result, Exception):
                logger.warning(
                    "identity_text outer fail for %s: %r", p.agent_id, result,
                )
                failed.append(p.agent_id)
                out[p.agent_id] = _fallback_identity_text(p)
            else:
                # Check if fallback was used by content sniffing
                fallback_marker = "周末偶尔去 Plaza 或公园走走"
                if fallback_marker in result and len(result) < 100:
                    failed.append(p.agent_id)
                out[p.agent_id] = result

    return out, failed


def inject_life_history(
    agent_id: str,
    records: list[LifeHistoryRecord],
    *,
    memory_service,
    sim_start_time: datetime,
) -> int:
    """Write each LifeHistoryRecord as a MemoryEvent[kind="life_history"]
    into agent_id's memory store.

    `sim_start_time` is the canonical "day 0" of the sim (datetime); the
    backstory event's simulated_time is computed as
    `sim_start_time - timedelta(days=record.years_ago * 365)` — gives
    retrieval recency a meaningful (old) anchor. tick=-1, day_index=-1.

    Idempotent — deterministic event_id collision is silently skipped.
    """
    from synthetic_socio_wind_tunnel.memory.models import MemoryEvent

    written = 0
    existing = {e.event_id for e in memory_service.all_for(agent_id)}
    for rec in records:
        event_id = f"lh_{rec.record_id}"
        if event_id in existing:
            continue
        offset_days = rec.years_ago * 365.0
        try:
            sim_time = sim_start_time - timedelta(days=offset_days)
        except (OverflowError, ValueError):
            sim_time = datetime(1990, 1, 1)
        ev = MemoryEvent(
            event_id=event_id,
            agent_id=agent_id,
            tick=-1,
            simulated_time=sim_time,
            kind="life_history",
            content=f"{rec.title} — {rec.content}" if rec.title else rec.content,
            location_id=rec.location_hint,
            urgency=0.0,
            importance=rec.importance,
            tags=("life_history",) + rec.tags,
            day_index=-1,
        )
        memory_service.record(agent_id, ev)
        written += 1
    return written


# Need this import for the function above
from datetime import timedelta  # noqa: E402


# ===========================================================================
# Social priors — pre-built day-0 ties from ABS-derived rules
# ===========================================================================
#
# Without priors the SocialGraphService starts as a 0-encounter blank slate;
# 1000 agents are mutual strangers on day 0, which doesn't match how a real
# Lane Cove resident enters the world (they already know roommates, school
# parents, ethnic-enclave neighbours, commute regulars, volunteer peers).
#
# `data/lanecove/social_priors.json` declares 6 rule types; this loader
# applies them to a sampled population and produces PriorTieRecord items
# that SocialGraphService.preload_ties() ingests.

_DEFAULT_PRIORS_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data" / "lanecove" / "social_priors.json"
)


@dataclass(frozen=True)
class SocialPriorRule:
    """One declarative rule from social_priors.json."""

    rule_id: str
    basis_label: str
    match: dict
    encounter_count_seed: int
    pair_cap_per_agent: int
    comment: str = ""


@dataclass(frozen=True)
class PriorTieRecord:
    """One computed prior tie. Multiple rules may produce ties for the
    same pair — the SocialGraphService merges them by summing
    encounter_count contributions per pair."""

    agent_a: str
    agent_b: str
    encounter_count: int
    rule_id: str
    basis_label: str


def load_social_prior_rules(
    path: Path | str | None = None,
) -> list[SocialPriorRule]:
    """Load social_priors.json rules. Malformed entries skipped."""
    target = Path(path) if path is not None else _DEFAULT_PRIORS_PATH
    if not target.exists():
        raise FileNotFoundError(
            f"social_priors.json not found at {target}"
        )
    raw = json.loads(target.read_text(encoding="utf-8"))
    entries = raw.get("rules", [])
    out: list[SocialPriorRule] = []
    for i, e in enumerate(entries):
        try:
            rec = SocialPriorRule(
                rule_id=str(e["rule_id"]),
                basis_label=str(e.get("basis_label", "")),
                match=dict(e.get("match") or {}),
                encounter_count_seed=int(e.get("encounter_count_seed", 1)),
                pair_cap_per_agent=int(e.get("pair_cap_per_agent", 99)),
                comment=str(e.get("comment", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "social_priors[%d] malformed (%r); skipping: %r", i, exc, e,
            )
            continue
        out.append(rec)
    return out


def _additional_constraint_satisfied(profile, constraint: dict | None) -> bool:
    """Check optional 'additional_constraint' subkey: {field, any_of}."""
    if not constraint:
        return True
    field = constraint.get("field")
    any_of = constraint.get("any_of") or []
    if not field:
        return True
    val = getattr(profile, field, None)
    return val in any_of


def _rule_matches_pair(rule: SocialPriorRule, p1, p2, archetype_lookup) -> bool:
    """Does `rule` match the (p1, p2) pair?"""
    m = rule.match
    mtype = m.get("type")

    if mtype == "same_home_location":
        # roommate / family
        if p1.home_location and p2.home_location:
            if m.get("exclude_self") and p1.agent_id == p2.agent_id:
                return False
            return p1.home_location == p2.home_location
        return False

    if mtype == "same_field":
        field = m.get("field")
        include = m.get("include_values")
        v1 = getattr(p1, field, None)
        v2 = getattr(p2, field, None)
        if v1 is None or v2 is None or v1 != v2:
            return False
        if include and v1 not in include:
            return False
        # Also check additional_constraint on EACH agent
        ac = m.get("additional_constraint")
        if not (_additional_constraint_satisfied(p1, ac)
                and _additional_constraint_satisfied(p2, ac)):
            return False
        return True

    if mtype == "same_field_with_constraint":
        field = m.get("field")
        exclude = m.get("exclude_values") or []
        v1 = getattr(p1, field, None)
        v2 = getattr(p2, field, None)
        if v1 is None or v2 is None or v1 != v2:
            return False
        if v1 in exclude:
            return False
        ac = m.get("additional_constraint")
        if not (_additional_constraint_satisfied(p1, ac)
                and _additional_constraint_satisfied(p2, ac)):
            return False
        return True

    if mtype == "same_archetype_with_age_window":
        a1 = archetype_lookup.get(p1.agent_id)
        a2 = archetype_lookup.get(p2.agent_id)
        if a1 is None or a2 is None:
            return False
        if a1 != a2:
            return False
        window = m.get("age_window", 8)
        return abs(p1.age - p2.age) <= window

    return False


def compute_social_priors_for_population(
    profiles: list,
    *,
    rules: list[SocialPriorRule] | None = None,
    archetypes: list[ArchetypeRecord] | None = None,
    seed: int = 0,
) -> list[PriorTieRecord]:
    """Apply each rule to all unordered pairs; return PriorTieRecord list.

    Implementation:
    - For each rule × pair: if matches, add tie record.
    - Per-agent cap (rule.pair_cap_per_agent): if a rule produces > cap
      ties for one agent, randomly subsample down to cap (seeded).
    - The same pair may appear under multiple rules — caller (preload_ties)
      sums encounter counts per canonical pair.

    Returns may contain duplicate (a, b) keys with different rule_id.
    """
    import random as _random
    if rules is None:
        rules = load_social_prior_rules()
    archetypes = archetypes or []

    # Pre-compute archetype lookup (avoid 1000² re-matches)
    archetype_lookup: dict[str, str | None] = {}
    for p in profiles:
        arch = match_archetype(p, archetypes) if archetypes else None
        archetype_lookup[p.agent_id] = arch.archetype_id if arch else None

    rng = _random.Random(seed)
    out: list[PriorTieRecord] = []

    for rule in rules:
        # First pass: collect all pairs matched by this rule
        candidates: dict[str, list[tuple[str, str, int]]] = {}
        # canonical (a, b) sorted; key by either side for cap accounting
        for i, p1 in enumerate(profiles):
            for j, p2 in enumerate(profiles):
                if i >= j:
                    continue
                if _rule_matches_pair(rule, p1, p2, archetype_lookup):
                    pair_a, pair_b = sorted((p1.agent_id, p2.agent_id))
                    candidates.setdefault(pair_a, []).append(
                        (pair_a, pair_b, rule.encounter_count_seed),
                    )
                    candidates.setdefault(pair_b, []).append(
                        (pair_a, pair_b, rule.encounter_count_seed),
                    )

        # Second pass: per-agent cap. We dedupe pair across both sides.
        seen_pairs: set[tuple[str, str]] = set()
        per_agent_taken: dict[str, int] = {}
        # Sort each agent's candidate list deterministically + shuffle
        # under seed for fairness.
        for agent_id in candidates:
            rng.shuffle(candidates[agent_id])

        # Iterate agents in id-sorted order for determinism
        for agent_id in sorted(candidates):
            kept = 0
            for pair_a, pair_b, count in candidates[agent_id]:
                if (pair_a, pair_b) in seen_pairs:
                    continue
                if kept >= rule.pair_cap_per_agent:
                    break
                # Also check the OTHER side hasn't exceeded its cap
                other = pair_b if agent_id == pair_a else pair_a
                if per_agent_taken.get(other, 0) >= rule.pair_cap_per_agent:
                    continue
                out.append(PriorTieRecord(
                    agent_a=pair_a, agent_b=pair_b,
                    encounter_count=count,
                    rule_id=rule.rule_id,
                    basis_label=rule.basis_label,
                ))
                seen_pairs.add((pair_a, pair_b))
                per_agent_taken[pair_a] = per_agent_taken.get(pair_a, 0) + 1
                per_agent_taken[pair_b] = per_agent_taken.get(pair_b, 0) + 1
                kept += 1

    return out
