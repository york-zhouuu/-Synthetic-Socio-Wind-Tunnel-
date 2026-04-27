#!/usr/bin/env python3
"""
sample_face_validity — sample M narratives + emit Prolific question template.

Usage:
    python3 tools/sample_face_validity.py \\
        --suite-dir data/experiments/<suite> \\
        --output data/face_validity/narratives.json \\
        --prolific-template data/face_validity/prolific_questions.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from synthetic_socio_wind_tunnel.metrics.face_validity import (
    render_prolific_template,
    sample_narratives,
)


_DEFAULT_OUT = Path(__file__).resolve().parents[1] / "data" / "face_validity" / "narratives.json"
_DEFAULT_TEMPLATE = Path(__file__).resolve().parents[1] / "data" / "face_validity" / "prolific_questions.md"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--suite-dir", type=Path, default=None,
                    help="Suite directory; if absent, uses default variant set")
    ap.add_argument("--M", type=int, default=10)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--variants", default=None,
                    help="Comma-separated variant names; overrides suite-dir scan")
    ap.add_argument("--output", type=Path, default=_DEFAULT_OUT)
    ap.add_argument("--prolific-template", type=Path, default=_DEFAULT_TEMPLATE)
    args = ap.parse_args()

    variant_names = None
    if args.variants:
        variant_names = [v.strip() for v in args.variants.split(",") if v.strip()]

    narratives = sample_narratives(
        suite_dir=args.suite_dir,
        M=args.M,
        seed=args.seed,
        variant_names=variant_names,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(
        {"narratives": [n.model_dump() for n in narratives]},
        indent=2, ensure_ascii=False,
    ))

    template_md = render_prolific_template(narratives)
    args.prolific_template.parent.mkdir(parents=True, exist_ok=True)
    args.prolific_template.write_text(template_md)

    print(f"[done] sampled {len(narratives)} narratives → {args.output}")
    print(f"[done] Prolific template → {args.prolific_template}")
    print()
    print("Next step: upload `prolific_questions.md` to Prolific (or equivalent)")
    print("           recruit ≥20 reviewers; download scores CSV;")
    print("           run `tools/aggregate_face_validity.py --scores-csv <csv>`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
