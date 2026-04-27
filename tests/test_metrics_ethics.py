"""Tests for synthetic_socio_wind_tunnel.metrics.ethics."""

from __future__ import annotations

from synthetic_socio_wind_tunnel.metrics.ethics import ETHICS_STATEMENT


class TestEthicsStatement:

    def test_constant_exists_and_is_string(self):
        assert isinstance(ETHICS_STATEMENT, str)
        assert len(ETHICS_STATEMENT) > 100

    def test_contains_required_keywords(self):
        # Anchor against research-design Part V — these words MUST stay
        # so docs ↔ code consistency is auditable.
        # We strip line breaks before matching to allow markdown wrapping.
        flat = ETHICS_STATEMENT.replace("\n", "").replace(" ", "")
        for keyword in ("云室", "dual-use", "不主张", "真实世界部署"):
            assert keyword in flat, (
                f"ETHICS_STATEMENT missing required keyword {keyword!r}; "
                "may have drifted from research-design Part V"
            )

    def test_starts_with_section_header(self):
        assert ETHICS_STATEMENT.startswith("## Research Posture Statement")
