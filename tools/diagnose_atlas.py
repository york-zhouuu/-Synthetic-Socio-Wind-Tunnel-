#!/usr/bin/env python3
"""
Diagnose connectivity of an Atlas JSON file.

Usage:
    python3 tools/diagnose_atlas.py [path/to/atlas.json]

Reports:
- Building / outdoor / connection counts
- Number of connected components and their sizes
- Share of locations in the largest component (the main connectivity metric)
- Number of completely isolated locations (no connections at all)
- Share of buildings with at least one "entrance" connection
- Distribution of building ID prefixes (helps spot mock / importer quirks)
"""

from __future__ import annotations
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


def diagnose(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    buildings: dict = data.get("buildings", {})
    outdoors: dict = data.get("outdoor_areas", {})
    connections: list = data.get("connections", [])

    all_ids = set(buildings) | set(outdoors)

    adj: dict[str, set[str]] = defaultdict(set)
    for c in connections:
        adj[c["from_id"]].add(c["to_id"])
        adj[c["to_id"]].add(c["from_id"])
    # Snapshot keys BEFORE DFS — defaultdict would otherwise auto-create empty
    # sets on read and inflate the "no connections" check below.
    referenced: set[str] = set(adj.keys())

    # Connected components via iterative DFS
    visited: set[str] = set()
    components: list[list[str]] = []
    for start in all_ids:
        if start in visited:
            continue
        stack = [start]
        comp: list[str] = []
        while stack:
            n = stack.pop()
            if n in visited:
                continue
            visited.add(n)
            comp.append(n)
            for nb in adj.get(n, ()):
                if nb not in visited:
                    stack.append(nb)
        components.append(comp)

    components.sort(key=len, reverse=True)
    largest = set(components[0]) if components else set()

    isolated = [n for n in all_ids if n not in referenced]
    iso_b = sum(1 for b in buildings if b not in referenced)
    iso_o = sum(1 for o in outdoors if o not in referenced)

    entrance_buildings = set()
    for c in connections:
        if c.get("path_type") == "entrance":
            if c["from_id"] in buildings:
                entrance_buildings.add(c["from_id"])
            if c["to_id"] in buildings:
                entrance_buildings.add(c["to_id"])

    # Enrichment metrics
    # "Named" excludes generic placeholders ("House" from the Riverview infill,
    # "building_123" defaults from OSM when no name tag is present).
    anon_re = re.compile(r"^(building_\d+|house)$", re.IGNORECASE)
    named_buildings = 0
    typed_buildings = 0
    affordance_covered = 0
    reside_covered = 0
    poi_covered = 0  # has a POI-bound affordance (not just default residential)
    overture_source_counts: Counter = Counter()
    for bid, b in buildings.items():
        bname = (b.get("name") or "")
        if bname and not anon_re.match(bname):
            named_buildings += 1
        btype = b.get("building_type") or ""
        if btype and btype != "residential":
            typed_buildings += 1
        affs = b.get("affordances") or []
        if len(affs) > 0:
            affordance_covered += 1
            activities = {a.get("activity_type") for a in affs
                          if isinstance(a, dict)}
            if "reside" in activities:
                reside_covered += 1
            # A "POI-bound" affordance is anything that isn't just the default
            # inferred residential marker.
            if activities - {"reside"}:
                poi_covered += 1
        src = (b.get("osm_tags") or {}).get("overture:primary_source")
        overture_source_counts[src or "osm_only"] += 1

    def prefix(id_: str) -> str:
        m = re.match(r"^([a-z]+_)", id_)
        return m.group(1) if m else "other"

    b_prefixes = Counter(prefix(k) for k in buildings).most_common(8)

    main_share = (len(largest) / len(all_ids)) if all_ids else 0.0
    b_in_main = sum(1 for b in buildings if b in largest)
    o_in_main = sum(1 for o in outdoors if o in largest)

    return {
        "path": str(path),
        "totals": {
            "buildings": len(buildings),
            "outdoors": len(outdoors),
            "locations": len(all_ids),
            "connections": len(connections),
            "components": len(components),
        },
        "main_component": {
            "size": len(largest),
            "share_of_all": main_share,
            "buildings_in_main": b_in_main,
            "buildings_share_in_main": b_in_main / max(1, len(buildings)),
            "outdoors_in_main": o_in_main,
            "outdoors_share_in_main": o_in_main / max(1, len(outdoors)),
        },
        "isolated": {
            "total": len(isolated),
            "buildings": iso_b,
            "outdoors": iso_o,
            "samples": isolated[:8],
        },
        "entrance_coverage": {
            "buildings_with_entrance": len(entrance_buildings),
            "share": len(entrance_buildings) / max(1, len(buildings)),
        },
        "enrichment": {
            "named_building_share": named_buildings / max(1, len(buildings)),
            "typed_building_share": typed_buildings / max(1, len(buildings)),
            "affordance_covered_share": affordance_covered / max(1, len(buildings)),
            "reside_covered_share": reside_covered / max(1, len(buildings)),
            "poi_covered_share": poi_covered / max(1, len(buildings)),
            "poi_covered_count": poi_covered,
            "overture_source_counts": dict(overture_source_counts),
        },
        "building_prefixes": b_prefixes,
        "top_components": [len(c) for c in components[:6]],
    }


def format_report(r: dict) -> str:
    lines = []
    lines.append(f"=== Atlas Diagnostic: {r['path']} ===\n")
    t = r["totals"]
    lines.append(f"Totals: {t['buildings']} buildings, {t['outdoors']} outdoors, "
                 f"{t['locations']} total, {t['connections']} connections, "
                 f"{t['components']} components")

    m = r["main_component"]
    lines.append(
        f"Main component: {m['size']} nodes "
        f"({m['share_of_all']:.1%} of all)"
    )
    lines.append(
        f"  buildings in main: {m['buildings_in_main']} "
        f"({m['buildings_share_in_main']:.1%})"
    )
    lines.append(
        f"  outdoors in main:  {m['outdoors_in_main']} "
        f"({m['outdoors_share_in_main']:.1%})"
    )

    iso = r["isolated"]
    lines.append(f"Isolated (no connections): {iso['total']} "
                 f"(buildings={iso['buildings']}, outdoors={iso['outdoors']})")
    if iso["samples"]:
        lines.append(f"  samples: {iso['samples']}")

    e = r["entrance_coverage"]
    lines.append(f"Buildings with 'entrance' connection: "
                 f"{e['buildings_with_entrance']} / {t['buildings']} ({e['share']:.1%})")

    lines.append(f"Top component sizes: {r['top_components']}")

    en = r["enrichment"]
    lines.append("")
    lines.append(f"Named buildings: {en['named_building_share']:.1%}")
    lines.append(f"Typed buildings (non-residential default): {en['typed_building_share']:.1%}")
    lines.append(f"Buildings with ANY affordance: {en['affordance_covered_share']:.1%}")
    lines.append(f"  of which: reside (inferred default): {en['reside_covered_share']:.1%}")
    lines.append(f"  of which: POI-bound (real activity): "
                 f"{en['poi_covered_share']:.1%} ({en['poi_covered_count']} bldgs)")
    lines.append("Overture source breakdown:")
    for src, n in sorted(en["overture_source_counts"].items(),
                         key=lambda kv: -kv[1]):
        lines.append(f"  {src}: {n}")

    lines.append("\nBuilding ID prefixes (top):")
    for p, n in r["building_prefixes"]:
        lines.append(f"  {p}: {n}")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("atlas", nargs="?", default="data/lanecove_atlas.json",
                    help="Path to atlas JSON (default: data/lanecove_atlas.json)")
    ap.add_argument("--json", action="store_true",
                    help="Output JSON instead of formatted text")
    args = ap.parse_args()

    path = Path(args.atlas)
    if not path.exists():
        print(f"Error: {path} not found", file=sys.stderr)
        return 2

    report = diagnose(path)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_report(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
