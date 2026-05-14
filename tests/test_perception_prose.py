"""Tests for SubjectiveView → Chinese prose helper (A1 / realism-perception-loop)."""

from __future__ import annotations

from synthetic_socio_wind_tunnel.perception.models import (
    EntitySnapshot,
    ItemSnapshot,
    SubjectiveView,
)
from synthetic_socio_wind_tunnel.perception.prose import (
    render_subjective_view_prose,
)


def _empty_view() -> SubjectiveView:
    return SubjectiveView(
        observer_id="obs",
        location_id="loc_a",
        location_name="Loc A",
    )


class TestEmpty:

    def test_none_returns_empty_string(self):
        assert render_subjective_view_prose(None) == ""

    def test_empty_view_returns_empty_string(self):
        """没有任何感知 → 不返占位文本，让 caller 整块省略 prompt block。"""
        assert render_subjective_view_prose(_empty_view()) == ""


class TestCrowdInfo:

    def test_5_visible_entities_mentions_5(self):
        view = _empty_view()
        view.entity_snapshots = [
            EntitySnapshot(entity_id=f"a_{i}", location_id="loc_a")
            for i in range(5)
        ]
        prose = render_subjective_view_prose(view)
        assert "5" in prose, f"prose 没含数字 5: {prose!r}"
        assert "人" in prose

    def test_2_visible_entities_mentions_2(self):
        view = _empty_view()
        view.entity_snapshots = [
            EntitySnapshot(entity_id=f"a_{i}", location_id="loc_a")
            for i in range(2)
        ]
        prose = render_subjective_view_prose(view)
        assert "2" in prose

    def test_1_visible_entity_mentions_name(self):
        view = _empty_view()
        view.entity_snapshots = [
            EntitySnapshot(
                entity_id="emma", name="Emma", location_id="loc_a",
                activity="reading",
            ),
        ]
        prose = render_subjective_view_prose(view)
        assert "Emma" in prose
        assert "reading" in prose


class TestItems:

    def test_item_content_appears(self):
        view = _empty_view()
        view.item_snapshots = [
            ItemSnapshot(
                item_id="poster_1",
                name="社区跑步活动海报",
                position_description="贴在街角",
            ),
        ]
        prose = render_subjective_view_prose(view)
        assert "社区跑步活动海报" in prose

    def test_notable_items_prioritized(self):
        view = _empty_view()
        view.item_snapshots = [
            ItemSnapshot(item_id=f"item_{i}", name=f"普通物品{i}")
            for i in range(5)
        ]
        view.item_snapshots.append(
            ItemSnapshot(item_id="notable_1", name="醒目海报", is_notable=True)
        )
        prose = render_subjective_view_prose(view)
        assert "醒目海报" in prose


class TestAmbient:

    def test_ambient_sounds_in_prose(self):
        view = _empty_view()
        view.ambient_sounds = ["人声嘈杂", "咖啡机声"]
        prose = render_subjective_view_prose(view)
        assert "人声嘈杂" in prose

    def test_ambient_smells_in_prose(self):
        view = _empty_view()
        view.ambient_smells = ["咖啡香味"]
        prose = render_subjective_view_prose(view)
        assert "咖啡香味" in prose


class TestLengthCap:

    def test_under_200_chars(self):
        view = _empty_view()
        view.entity_snapshots = [
            EntitySnapshot(entity_id=f"a_{i}", location_id="loc_a")
            for i in range(20)
        ]
        view.item_snapshots = [
            ItemSnapshot(
                item_id=f"item_{i}",
                name=f"非常长的物品名字{i}" * 10,
                is_notable=True,
            )
            for i in range(10)
        ]
        view.ambient_sounds = ["很长的声音描述" * 20]
        view.ambient_smells = ["很长的气味描述" * 20]
        prose = render_subjective_view_prose(view)
        assert len(prose) <= 200, f"prose 超过 200 字: len={len(prose)}"


class TestComposite:

    def test_multiple_senses_combine(self):
        view = _empty_view()
        view.entity_snapshots = [
            EntitySnapshot(entity_id=f"a_{i}", location_id="loc_a")
            for i in range(3)
        ]
        view.item_snapshots = [ItemSnapshot(item_id="poster", name="活动海报")]
        view.ambient_sounds = ["音乐声"]
        prose = render_subjective_view_prose(view)
        assert "3" in prose
        assert "活动海报" in prose
        assert "音乐声" in prose
