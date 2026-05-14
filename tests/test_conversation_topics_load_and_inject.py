"""Tests for B4 conversation_topics: load + inject into do_something prompt."""

from __future__ import annotations

from synthetic_socio_wind_tunnel.agent.operations.handlers.do_something import (
    _build_do_something_prompt,
)
from synthetic_socio_wind_tunnel.data_loader import (
    ConversationTopicRecord,
    load_conversation_topics,
)


class TestLoadConversationTopics:

    def test_loads_lane_cove_topics(self):
        topics = load_conversation_topics()
        assert len(topics) >= 8, f"expected ≥ 8 Lane Cove topics, got {len(topics)}"
        for t in topics:
            assert isinstance(t, ConversationTopicRecord)
            assert t.topic_id
            assert t.snippet

    def test_topic_snippets_are_chinese_lane_cove_grounded(self):
        topics = load_conversation_topics()
        # At least one Lane Cove proper noun should appear across the snippets
        proper_nouns = ["Lane Cove", "Plaza", "Mowbray", "Epping", "Cameraygal"]
        all_text = "\n".join(t.snippet for t in topics)
        assert any(noun in all_text for noun in proper_nouns), \
            "topics seem too generic — no Lane Cove proper nouns"


class TestPromptInjection:

    def _base_args(self) -> dict:
        return {
            "agent_name": "emma",
            "current_location_id": "cafe_main",
            "current_time": "2026-04-21 10:00",
        }

    def test_no_local_topics_no_section(self):
        prompt = _build_do_something_prompt(self._base_args())
        assert "Recent local topics" not in prompt

    def test_empty_local_topics_no_section(self):
        args = self._base_args()
        args["local_topics"] = ()
        prompt = _build_do_something_prompt(args)
        assert "Recent local topics" not in prompt

    def test_topics_appear_in_prompt(self):
        args = self._base_args()
        args["local_topics"] = (
            "Mowbray Road 数据中心提案",
            "Plaza 停车 1 小时限制",
        )
        prompt = _build_do_something_prompt(args)
        assert "Recent local topics" in prompt
        assert "Mowbray Road" in prompt
        assert "Plaza" in prompt
