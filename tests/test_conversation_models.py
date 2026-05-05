"""Tests for conversation.models — Information / Propagation / ShareEvent."""

from __future__ import annotations

import pytest

from synthetic_socio_wind_tunnel.conversation.models import (
    Information,
    Propagation,
    ShareEvent,
)


class TestInformation:

    def _make(self, **overrides) -> Information:
        base = dict(
            info_id="i1", content="本街市集", category="push",
            salience=0.8, origin_tick=10, origin_agent_id="emma",
            origin_day_index=0,
        )
        base.update(overrides)
        return Information(**base)

    def test_construct_ok(self):
        info = self._make()
        assert info.info_id == "i1"
        assert info.salience == 0.8

    def test_invalid_category_rejected(self):
        with pytest.raises(ValueError, match="category"):
            self._make(category="invalid")

    def test_salience_above_1_rejected(self):
        with pytest.raises(ValueError, match="salience"):
            self._make(salience=1.5)

    def test_salience_below_0_rejected(self):
        with pytest.raises(ValueError, match="salience"):
            self._make(salience=-0.1)

    def test_frozen_cannot_mutate(self):
        info = self._make()
        with pytest.raises(Exception):  # FrozenInstanceError
            info.content = "new"  # type: ignore[misc]


class TestPropagation:

    def test_default_reach_zero(self):
        p = Propagation(info_id="i1", reach=0, max_hops=0, mean_hops=0.0)
        assert p.known_at == {}
        assert p.hops_at == {}

    def test_with_known_agents(self):
        p = Propagation(
            info_id="i1", reach=3, max_hops=2, mean_hops=1.0,
            known_at={"emma": 10, "linda": 20, "john": 30},
            hops_at={"emma": 0, "linda": 1, "john": 2},
        )
        assert p.reach == 3
        assert p.max_hops == 2

    def test_frozen(self):
        p = Propagation(info_id="i1", reach=1, max_hops=0, mean_hops=0.0)
        with pytest.raises(Exception):
            p.reach = 5  # type: ignore[misc]


class TestShareEvent:

    def test_construct(self):
        e = ShareEvent(
            info_id="i1", from_agent="emma", to_agent="linda",
            tick=20, receiver_hops=1,
        )
        assert e.from_agent == "emma"
        assert e.receiver_hops == 1
