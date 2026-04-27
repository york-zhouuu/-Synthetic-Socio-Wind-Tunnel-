#!/usr/bin/env python3
"""
aggregate_face_validity — read Prolific scores CSV → produce
face_validity_report.json.

Usage:
    python3 tools/aggregate_face_validity.py \\
        --scores-csv ~/Downloads/prolific_scores.csv \\
        --narratives data/face_validity/narratives.json \\
        --output data/calibration/face_validity_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from synthetic_socio_wind_tunnel.metrics.face_validity import (
    Narrative,
    assess_face_validity,
    parse_scores_csv,
    write_face_validity_report,
)


_DEFAULT_NARRATIVES = Path(__file__).resolve().parents[1] / "data" / "face_validity" / "narratives.json"
_DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "calibration" / "face_validity_report.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--scores-csv", type=Path, required=True,
                    help="Prolific scores CSV (5 columns: reviewer_id, narrative_id, q1_authenticity, q2_realism, q3_text)")
    ap.add_argument("--narratives", type=Path, default=_DEFAULT_NARRATIVES)
    ap.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    args = ap.parse_args()

    if not args.scores_csv.exists():
        sys.stderr.write(f"error: scores CSV not found: {args.scores_csv}\n")
        return 2
    if not args.narratives.exists():
        sys.stderr.write(
            f"error: narratives JSON not found: {args.narratives}\n"
            "  Run `tools/sample_face_validity.py` first.\n"
        )
        return 2

    narratives_payload = json.loads(args.narratives.read_text())
    narratives = [Narrative(**n) for n in narratives_payload["narratives"]]

    scores = parse_scores_csv(args.scores_csv.read_text())
    if not scores:
        sys.stderr.write(
            f"error: no valid scores parsed from {args.scores_csv}\n"
            "  Expected columns: reviewer_id, narrative_id, q1_authenticity, q2_realism, [q3_text]\n"
        )
        return 2

    status = assess_face_validity(scores, narratives)
    write_face_validity_report(status, args.output)

    print(f"=== face validity summary ===")
    emoji = "✓" if status.passed else "✗"
    print(f"  {emoji} passed = {status.passed}")
    print(f"  overall_avg = {status.overall_avg:.2f} (threshold ≥ 3.5)")
    print(f"  pct_low     = {status.pct_low:.1%} (threshold ≤ 20%)")
    print(f"  n_narratives = {status.n_narratives}, n_reviewers = {status.n_reviewers}")
    print()
    print(f"[report] {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
