"""PushTemplate validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from synthetic_socio_wind_tunnel.policy_hack import PushTemplate


def _kw(**overrides):
    base = dict(
        template_id="t1", topic_id="hp_t1",
        base_content="本街 {location}",
        audience_variants={"default": "本街 {location} 默认内容"},
        target_audience_tags=("default",),
        base_salience=0.7,
    )
    base.update(overrides)
    return base


class TestPushTemplate:

    def test_construct_ok(self):
        t = PushTemplate(**_kw())
        assert t.template_id == "t1"
        assert t.base_salience == 0.7

    def test_missing_default_variant_rejected(self):
        with pytest.raises(ValidationError, match="default"):
            PushTemplate(**_kw(audience_variants={"parents": "x"}))

    def test_empty_target_audience_rejected(self):
        with pytest.raises(ValidationError, match="non-empty"):
            PushTemplate(**_kw(target_audience_tags=()))

    def test_salience_above_1_rejected(self):
        with pytest.raises(ValidationError):
            PushTemplate(**_kw(base_salience=1.5))

    def test_salience_negative_rejected(self):
        with pytest.raises(ValidationError):
            PushTemplate(**_kw(base_salience=-0.1))

    def test_frozen(self):
        t = PushTemplate(**_kw())
        with pytest.raises(Exception):
            t.template_id = "x"  # type: ignore[misc]
