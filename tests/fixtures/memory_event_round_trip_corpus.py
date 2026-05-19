"""Hand-crafted MemoryEvent corpus for byte-equivalence round-trip tests.

Generated programmatically (not a static JSON file) because MemoryEvent
references `datetime` instances which aren't JSON-serializable. Pytest
imports this module to get the corpus.

50 events covering all 11 MemoryKind values × edge fields:
- embedding: None / empty tuple / 1536-dim
- content: ASCII / Unicode / emoji / control chars
- simulated_time: epoch / future / current
- importance: None edge / 0.0 / 1.0
- participants / tags: empty / single / many

The corpus is the **ground truth** for what "equivalent serialization"
means. If you change _event_to_json's output structure, this corpus
must be updated **deliberately** + paired with the consumer
(_event_from_json) update.
"""

from __future__ import annotations

from datetime import datetime, timezone

from synthetic_socio_wind_tunnel.memory.models import MemoryEvent

_BASE_TIME = datetime(2026, 4, 22, 8, 0, 0)
_EPOCH = datetime(1970, 1, 1, 0, 0, 0)
_FUTURE = datetime(2099, 12, 31, 23, 59, 59)


def _events_for_kind_action() -> list[MemoryEvent]:
    return [
        # Simple
        MemoryEvent(
            event_id="ev_action_001", agent_id="a_001", tick=10,
            simulated_time=_BASE_TIME, kind="action",
            content="walked to cafe", location_id="cafe_42",
        ),
        # With actor
        MemoryEvent(
            event_id="ev_action_002", agent_id="a_002", tick=11,
            simulated_time=_BASE_TIME, kind="action",
            content="ordered coffee", actor_id="barista_3",
            location_id="cafe_42", importance=0.3,
        ),
        # With participants + tags
        MemoryEvent(
            event_id="ev_action_003", agent_id="a_003", tick=12,
            simulated_time=_BASE_TIME, kind="action",
            content="joined book club", location_id="library_5",
            participants=("a_004", "a_005", "a_006"),
            tags=("social", "weekly", "afternoon"),
            importance=0.8,
        ),
        # Edge: epoch time + min importance
        MemoryEvent(
            event_id="ev_action_004", agent_id="a_004", tick=0,
            simulated_time=_EPOCH, kind="action",
            content="boundary case", importance=0.0,
        ),
        # Edge: future time + max importance
        MemoryEvent(
            event_id="ev_action_005", agent_id="a_005", tick=999999,
            simulated_time=_FUTURE, kind="action",
            content="far future", importance=1.0,
        ),
    ]


def _events_for_kind_encounter() -> list[MemoryEvent]:
    return [
        MemoryEvent(
            event_id="ev_enc_001", agent_id="a_010", tick=20,
            simulated_time=_BASE_TIME, kind="encounter",
            content="passed agent a_011 at cowper_st",
            actor_id="a_011", location_id="street_cowper",
            importance=0.4,
        ),
        MemoryEvent(
            event_id="ev_enc_002", agent_id="a_010", tick=21,
            simulated_time=_BASE_TIME, kind="encounter",
            content="encounter with empty fields",
        ),
        MemoryEvent(
            event_id="ev_enc_003", agent_id="a_012", tick=22,
            simulated_time=_BASE_TIME, kind="encounter",
            content="dense encounter location_with_underscores",
            actor_id="a_013", location_id="loc_with_long_name_001",
            participants=("a_013",), tags=("close", "midday"),
        ),
        MemoryEvent(
            event_id="ev_enc_004", agent_id="a_014", tick=23,
            simulated_time=_BASE_TIME, kind="encounter",
            content="unicode encounter 在 Cowper 街口附近", actor_id="a_015",
        ),
        MemoryEvent(
            event_id="ev_enc_005", agent_id="a_016", tick=24,
            simulated_time=_BASE_TIME, kind="encounter",
            content="emoji 🚶‍♀️ 👀 🧑‍🤝‍🧑", actor_id="a_017",
        ),
    ]


def _events_for_kind_reflection() -> list[MemoryEvent]:
    return [
        MemoryEvent(
            event_id="ev_ref_001", agent_id="a_020", tick=288,
            simulated_time=_BASE_TIME, kind="reflection",
            content="I noticed my routine takes me past the same people",
            importance=0.85,
        ),
        MemoryEvent(
            event_id="ev_ref_002", agent_id="a_021", tick=576,
            simulated_time=_BASE_TIME, kind="reflection",
            content="Long reflection " + "x" * 5000,  # ~5KB content
            tags=("insight", "weekly"), importance=0.9,
        ),
        MemoryEvent(
            event_id="ev_ref_003", agent_id="a_022", tick=864,
            simulated_time=_BASE_TIME, kind="reflection",
            content="Reflection with related links",
            related_memory_ids=("ev_action_001", "ev_enc_001", "ev_ref_001"),
        ),
        MemoryEvent(
            event_id="ev_ref_004", agent_id="a_023", tick=1152,
            simulated_time=_BASE_TIME, kind="reflection",
            content="reflection control chars: tab\there newline\nhere",
        ),
        MemoryEvent(
            event_id="ev_ref_005", agent_id="a_024", tick=1440,
            simulated_time=_BASE_TIME, kind="reflection",
            content="reflection with 1536-dim embedding",
            embedding=tuple(float(i) * 0.001 for i in range(1536)),
        ),
    ]


def _events_for_kind_conversation() -> list[MemoryEvent]:
    return [
        MemoryEvent(
            event_id="ev_conv_001", agent_id="a_030", tick=50,
            simulated_time=_BASE_TIME, kind="conversation",
            content="chatted with a_031 about books",
            actor_id="a_031", participants=("a_031",),
        ),
        MemoryEvent(
            event_id="ev_conv_002", agent_id="a_032", tick=51,
            simulated_time=_BASE_TIME, kind="conversation",
            content="Long convo summary: " + "话题 " * 200,
            actor_id="a_033", participants=("a_033",),
            importance=0.6,
        ),
        MemoryEvent(
            event_id="ev_conv_003", agent_id="a_034", tick=52,
            simulated_time=_BASE_TIME, kind="conversation",
            content="3-way", actor_id="a_035",
            participants=("a_035", "a_036"),
        ),
        MemoryEvent(
            event_id="ev_conv_004", agent_id="a_037", tick=53,
            simulated_time=_BASE_TIME, kind="conversation",
            content="last_access set", actor_id="a_038",
            last_access=datetime(2026, 4, 23, 10, 0),
        ),
        MemoryEvent(
            event_id="ev_conv_005", agent_id="a_039", tick=54,
            simulated_time=_BASE_TIME, kind="conversation",
            content="weird quote 'single' \"double\" \\ backslash",
            actor_id="a_040",
        ),
    ]


def _events_for_kind_daily_summary() -> list[MemoryEvent]:
    return [
        MemoryEvent(
            event_id="ev_ds_001", agent_id="a_050", tick=287,
            simulated_time=_BASE_TIME, kind="daily_summary",
            content="Day 0: routine, library visit, evening tea",
            day_index=0, importance=0.7,
        ),
        MemoryEvent(
            event_id="ev_ds_002", agent_id="a_051", tick=575,
            simulated_time=_BASE_TIME, kind="daily_summary",
            content="Day 1: " + "事件 " * 100,
            day_index=1, importance=0.7,
        ),
        MemoryEvent(
            event_id="ev_ds_003", agent_id="a_052", tick=863,
            simulated_time=_BASE_TIME, kind="daily_summary",
            content="Day 2 short", day_index=2,
        ),
        MemoryEvent(
            event_id="ev_ds_004", agent_id="a_053", tick=1151,
            simulated_time=_BASE_TIME, kind="daily_summary",
            content="Day 3 with tags", day_index=3,
            tags=("intervention_start",),
        ),
        MemoryEvent(
            event_id="ev_ds_005", agent_id="a_054", tick=1439,
            simulated_time=_BASE_TIME, kind="daily_summary",
            content="Day 4", day_index=4, importance=0.7,
        ),
    ]


def _events_for_kind_life_history() -> list[MemoryEvent]:
    return [
        MemoryEvent(
            event_id="ev_lh_001", agent_id="a_060", tick=0,
            simulated_time=_BASE_TIME, kind="life_history",
            content="I grew up in Lane Cove, worked at the library for 10 years",
            day_index=-1, importance=0.95,
            tags=("pre_sim", "backstory"),
        ),
        MemoryEvent(
            event_id="ev_lh_002", agent_id="a_061", tick=0,
            simulated_time=_EPOCH, kind="life_history",
            content="第一人称中文背景：" + "我曾经 " * 500,  # ~5KB unicode
            day_index=-1, importance=0.95,
        ),
        MemoryEvent(
            event_id="ev_lh_003", agent_id="a_062", tick=0,
            simulated_time=_BASE_TIME, kind="life_history",
            content="lh with embedding",
            embedding=tuple([0.5] * 128),  # smaller embedding
        ),
        MemoryEvent(
            event_id="ev_lh_004", agent_id="a_063", tick=0,
            simulated_time=_BASE_TIME, kind="life_history",
            content="lh with many participants",
            participants=tuple(f"family_{i}" for i in range(20)),
        ),
        MemoryEvent(
            event_id="ev_lh_005", agent_id="a_064", tick=0,
            simulated_time=_BASE_TIME, kind="life_history",
            content="lh with empty embedding tuple",
            embedding=(),
        ),
    ]


def _events_for_other_kinds() -> list[MemoryEvent]:
    """5 kinds × 4 events each = 20 events covering remaining MemoryKind values."""
    out = []
    for kind in ("notification", "observation", "speech", "task_received", "shared_memory"):
        for i in range(4):
            out.append(MemoryEvent(
                event_id=f"ev_{kind}_{i:03d}",
                agent_id=f"a_{kind[:3]}_{i}",
                tick=100 + i,
                simulated_time=_BASE_TIME,
                kind=kind,
                content=f"{kind} content #{i}",
                importance=0.5,
            ))
    return out


def build_corpus() -> list[MemoryEvent]:
    """50 hand-crafted MemoryEvent covering all kinds × edge cases."""
    events = (
        _events_for_kind_action()
        + _events_for_kind_encounter()
        + _events_for_kind_reflection()
        + _events_for_kind_conversation()
        + _events_for_kind_daily_summary()
        + _events_for_kind_life_history()
        + _events_for_other_kinds()
    )
    return events


CORPUS = build_corpus()
