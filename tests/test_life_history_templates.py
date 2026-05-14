"""B2 audit: life_history templates loaded + prompt anchors injection."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_PATH = ROOT / "data" / "lanecove" / "life_history_templates.json"


class TestTemplatesFile:

    def test_file_exists(self):
        assert TEMPLATES_PATH.exists()

    def test_each_archetype_has_5plus_templates(self):
        with TEMPLATES_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
        templates = data["templates_by_archetype"]
        # We have 12 archetypes; each SHALL have ≥ 5 anchors
        assert len(templates) >= 11
        for arch_id, anchors in templates.items():
            assert len(anchors) >= 5, \
                f"archetype {arch_id} has only {len(anchors)} anchors (< 5)"

    def test_anchors_are_lane_cove_grounded(self):
        with TEMPLATES_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
        all_anchors = "\n".join(
            "\n".join(a)
            for a in data["templates_by_archetype"].values()
        )
        proper_nouns = [
            "Lane Cove", "Plaza", "Cammeray", "Greenwich", "Mowbray",
            "Cameraygal", "Pacific Highway", "St Leonards",
        ]
        # At least 4 distinct Lane Cove proper nouns SHALL appear across anchors
        hits = sum(1 for n in proper_nouns if n in all_anchors)
        assert hits >= 4, f"only {hits}/{len(proper_nouns)} proper nouns found"


class TestLoaderHelper:

    def test_returns_anchors_for_known_archetype(self):
        from synthetic_socio_wind_tunnel.data_loader.lanecove import (
            _load_life_history_templates_for_archetype,
        )
        anchors = _load_life_history_templates_for_archetype("longtime_owner_occupier")
        assert len(anchors) >= 5
        assert all(isinstance(a, str) for a in anchors)

    def test_returns_empty_for_unknown_archetype(self):
        from synthetic_socio_wind_tunnel.data_loader.lanecove import (
            _load_life_history_templates_for_archetype,
        )
        anchors = _load_life_history_templates_for_archetype("nonexistent_xyz")
        assert anchors == []
