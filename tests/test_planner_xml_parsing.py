"""Tests for Planner XML parsing + synonym mapping (lightweight-llm-format)."""

from __future__ import annotations

import logging

from synthetic_socio_wind_tunnel.agent.planner import (
    _normalize_action,
    _normalize_social_intent,
    _parse_xml_plan,
)


class TestBasicXMLParsing:

    def test_basic_xml(self):
        xml = (
            "<plan>"
            "<step><time>8:00</time><destination>cafe</destination>"
            "<action>move</action><duration>30</duration>"
            "<social>alone</social></step>"
            "</plan>"
        )
        steps = _parse_xml_plan(xml)
        assert len(steps) == 1
        assert steps[0].time == "8:00"
        assert steps[0].destination == "cafe"
        assert steps[0].action == "move"
        assert steps[0].duration_minutes == 30
        assert steps[0].social_intent == "alone"

    def test_multiple_steps(self):
        xml = "<plan>"
        for i in range(5):
            xml += (
                f"<step><time>{8+i}:00</time>"
                f"<destination>loc_{i}</destination>"
                "<action>move</action><duration>30</duration>"
                "<social>alone</social></step>"
            )
        xml += "</plan>"
        steps = _parse_xml_plan(xml)
        assert len(steps) == 5
        assert steps[0].destination == "loc_0"
        assert steps[4].destination == "loc_4"


class TestActionSynonyms:

    def test_visit_maps_to_move(self):
        assert _normalize_action("visit") == "move"
        assert _normalize_action("VISIT") == "move"

    def test_work_maps_to_stay(self):
        assert _normalize_action("work") == "stay"

    def test_go_home_maps_to_move(self):
        assert _normalize_action("go_home") == "move"

    def test_commute_maps_to_move(self):
        assert _normalize_action("commute") == "move"

    def test_chat_maps_to_interact(self):
        assert _normalize_action("chat") == "interact"

    def test_wander_maps_to_explore(self):
        assert _normalize_action("wander") == "explore"

    def test_phrase_with_first_word_action(self):
        # LLM 写 "visit cafe to find note" → 取 "visit" → move
        assert _normalize_action("visit cafe to find note") == "move"


class TestSocialSynonyms:

    def test_private_maps_to_alone(self):
        assert _normalize_social_intent("private") == "alone"

    def test_open_maps_to_open_to_chat(self):
        assert _normalize_social_intent("open") == "open_to_chat"

    def test_social_maps_to_seeking_company(self):
        assert _normalize_social_intent("social") == "seeking_company"

    def test_friendly_maps_to_open_to_chat(self):
        assert _normalize_social_intent("friendly") == "open_to_chat"


class TestUnknownFallback:

    def test_unknown_action_falls_back_to_stay(self, caplog):
        with caplog.at_level(logging.DEBUG, logger="synthetic_socio_wind_tunnel.agent.planner"):
            assert _normalize_action("flying") == "stay"
        assert any("flying" in rec.message for rec in caplog.records)

    def test_unknown_social_falls_back_to_alone(self, caplog):
        with caplog.at_level(logging.DEBUG, logger="synthetic_socio_wind_tunnel.agent.planner"):
            assert _normalize_social_intent("xenomorphic") == "alone"
        assert any("xenomorphic" in rec.message for rec in caplog.records)

    def test_empty_action_falls_back_to_stay(self):
        assert _normalize_action("") == "stay"

    def test_empty_social_falls_back_to_alone(self):
        assert _normalize_social_intent("") == "alone"


class TestMissingFields:

    def test_missing_optional_fields(self):
        # 缺 destination / duration / social → 默认值
        xml = "<plan><step><time>9:00</time><action>move</action></step></plan>"
        steps = _parse_xml_plan(xml)
        assert len(steps) == 1
        assert steps[0].destination is None
        assert steps[0].duration_minutes == 30  # 默认
        assert steps[0].social_intent == "alone"  # 默认

    def test_missing_time_skips_step(self):
        xml = (
            "<plan>"
            "<step><action>move</action><destination>cafe</destination></step>"
            "<step><time>10:00</time><action>stay</action></step>"
            "</plan>"
        )
        steps = _parse_xml_plan(xml)
        # 第一个 step 缺 time → 跳过；第二个 step 留下
        assert len(steps) == 1
        assert steps[0].time == "10:00"


class TestInvalidXML:

    def test_invalid_xml_returns_empty(self):
        assert _parse_xml_plan("sorry, I cannot help") == []

    def test_empty_string_returns_empty(self):
        assert _parse_xml_plan("") == []

    def test_no_root_wraps_and_retries(self):
        """LLM 漏 <plan> 根 → wrap 后能解析。"""
        xml = (
            "<step><time>8:00</time><destination>cafe</destination>"
            "<action>move</action></step>"
        )
        steps = _parse_xml_plan(xml)
        assert len(steps) == 1
        assert steps[0].destination == "cafe"

    def test_markdown_code_block(self):
        """LLM 有时把 XML 包在 markdown code block 里。"""
        xml = (
            "```xml\n"
            "<plan><step><time>8:00</time><action>move</action></step></plan>\n"
            "```"
        )
        steps = _parse_xml_plan(xml)
        assert len(steps) == 1


class TestActivityPreservation:

    def test_llm_action_preserved_to_activity(self):
        """LLM 没显式 <activity> → <action> 文本作 activity。"""
        xml = (
            "<plan><step><time>8:00</time>"
            "<action>visit cafe to find note</action>"
            "<destination>cafe</destination></step></plan>"
        )
        steps = _parse_xml_plan(xml)
        assert len(steps) == 1
        assert steps[0].action == "move"  # 同义词归一化
        assert steps[0].activity == "visit cafe to find note"  # 原文保留

    def test_explicit_activity_preferred(self):
        """LLM 提供 <activity> → 用它，不被 <action> 文本覆盖。"""
        xml = (
            "<plan><step><time>8:00</time>"
            "<action>visit</action>"
            "<activity>going to cafe for morning ritual</activity>"
            "</step></plan>"
        )
        steps = _parse_xml_plan(xml)
        assert steps[0].activity == "going to cafe for morning ritual"
