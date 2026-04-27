"""Tests for synthetic_socio_wind_tunnel.metrics.face_validity."""

from __future__ import annotations

import pytest

from synthetic_socio_wind_tunnel.metrics.face_validity import (
    Narrative,
    Score,
    assess_face_validity,
    parse_scores_csv,
    render_prolific_template,
    sample_narratives,
)


# ---------------------------------------------------------------------------
# Narrative sampling
# ---------------------------------------------------------------------------

class TestSampleNarratives:

    def test_M_narratives_returned(self):
        narratives = sample_narratives(M=10, variant_names=["baseline", "hyperlocal_push"])
        assert len(narratives) == 10

    def test_each_variant_has_at_least_one_narrative(self):
        variants = ["baseline", "hyperlocal_push", "global_distraction", "shared_anchor"]
        narratives = sample_narratives(M=10, variant_names=variants)
        seen = {n.variant_name for n in narratives}
        assert seen == set(variants)

    def test_M_smaller_than_variants_raises(self):
        with pytest.raises(ValueError, match="too small"):
            sample_narratives(M=2, variant_names=["a", "b", "c", "d"])

    def test_seed_reproducibility(self):
        a = sample_narratives(M=10, seed=42, variant_names=["baseline"])
        b = sample_narratives(M=10, seed=42, variant_names=["baseline"])
        assert [(n.agent_id, n.variant_name) for n in a] == \
               [(n.agent_id, n.variant_name) for n in b]
        assert [n.summary_text for n in a] == [n.summary_text for n in b]

    def test_narrative_text_contains_profile_excerpt(self):
        narratives = sample_narratives(M=4, variant_names=["baseline"])
        for n in narratives:
            assert n.profile_excerpt
            assert len(n.summary_text) > 50


# ---------------------------------------------------------------------------
# Acceptance assessment
# ---------------------------------------------------------------------------

class TestAssessFaceValidity:

    def _scores(self, n_pairs, q1_q2):
        """Build n_pairs scores all with given (q1, q2) ratings."""
        return [
            Score(reviewer_id=f"r{i}", narrative_id=f"n{i % 10:02d}",
                  authenticity=q1_q2[0], realism=q1_q2[1])
            for i in range(n_pairs)
        ]

    def test_pass_at_threshold(self):
        # avg=3.5 (just at), pct_low=0% (well below)
        scores = self._scores(200, (3, 4))  # avg = 3.5
        narratives = []
        result = assess_face_validity(scores, narratives)
        assert result.overall_avg == pytest.approx(3.5)
        assert result.pct_low == 0.0
        assert result.passed is True

    def test_fail_when_avg_too_low(self):
        scores = self._scores(200, (3, 3))  # avg = 3.0
        result = assess_face_validity(scores, [])
        assert result.overall_avg == pytest.approx(3.0)
        assert result.passed is False

    def test_fail_when_pct_low_too_high(self):
        # Half rate (1, 1), half rate (5, 5) → avg=3 high but pct_low=50%
        low = [Score(reviewer_id=f"r{i}", narrative_id="n0",
                     authenticity=1, realism=1) for i in range(100)]
        high = [Score(reviewer_id=f"r{100+i}", narrative_id="n0",
                      authenticity=5, realism=5) for i in range(100)]
        result = assess_face_validity(low + high, [])
        # avg = 3.0 (boundary), but real failure is pct_low = 50%
        assert result.passed is False
        assert result.pct_low == 0.5

    def test_empty_scores_returns_failing(self):
        result = assess_face_validity([], [])
        assert result.passed is False
        assert result.overall_avg == 0.0

    def test_n_reviewers_counted(self):
        scores = self._scores(100, (4, 4))  # 100 unique reviewer_ids
        result = assess_face_validity(scores, [])
        assert result.n_reviewers == 100

    def test_pass_with_realistic_distribution(self):
        # Avg ≈ 4, pct_low ≈ 5%; well above thresholds
        import random
        rng = random.Random(42)
        scores = []
        for r in range(20):
            for n in range(10):
                q1 = rng.choices([2, 3, 4, 5], weights=[1, 3, 5, 4])[0]
                q2 = rng.choices([2, 3, 4, 5], weights=[1, 3, 5, 4])[0]
                scores.append(Score(reviewer_id=f"r{r:02d}", narrative_id=f"n{n:02d}",
                                    authenticity=q1, realism=q2))
        result = assess_face_validity(scores, [])
        assert result.passed is True
        assert result.overall_avg > 3.5
        assert result.pct_low < 0.20


# ---------------------------------------------------------------------------
# Parsing + rendering
# ---------------------------------------------------------------------------

class TestParseScoresCsv:

    def test_basic_parse(self):
        csv_text = (
            "reviewer_id,narrative_id,q1_authenticity,q2_realism,q3_text\n"
            "r1,n0,4,5,\n"
            "r1,n1,3,4,\"some text\"\n"
        )
        scores = parse_scores_csv(csv_text)
        assert len(scores) == 2
        assert scores[0].reviewer_id == "r1"
        assert scores[0].authenticity == 4
        assert scores[1].free_text == "some text"

    def test_skips_invalid_rows(self):
        csv_text = (
            "reviewer_id,narrative_id,q1_authenticity,q2_realism\n"
            "r1,n0,4,5\n"
            "r2,n0,not_an_int,5\n"  # invalid
            "r3,n0,3,4\n"
        )
        scores = parse_scores_csv(csv_text)
        assert len(scores) == 2  # one bad row skipped


class TestRenderProlificTemplate:

    def test_template_contains_narratives(self):
        narratives = sample_narratives(M=4, variant_names=["baseline"])
        md = render_prolific_template(narratives)
        for n in narratives:
            assert n.narrative_id in md
        assert "Q1" in md and "Q2" in md and "Q3" in md
        assert "1–5" in md or "1-5" in md or "Likert" in md

    def test_template_contains_lane_cove_brief(self):
        md = render_prolific_template([])
        assert "Lane Cove" in md


# ---------------------------------------------------------------------------
# Hot path isolation
# ---------------------------------------------------------------------------

class TestHotPathIsolation:

    def test_runtime_does_not_import_face_validity(self):
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-c", (
                "import sys; "
                "import synthetic_socio_wind_tunnel.agent.runtime; "
                "import synthetic_socio_wind_tunnel.agent.planner; "
                "assert 'synthetic_socio_wind_tunnel.metrics.face_validity' not in sys.modules"
            )],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr
