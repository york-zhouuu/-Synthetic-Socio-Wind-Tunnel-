"""Audit social_priors rules on a 1000-agent sample (B3).

Loads LANE_COVE_PROFILE × 1000 agents, runs compute_social_priors_for_population,
and reports per-rule tie counts + coverage statistics.

Usage:
    python3 tools/audit_social_priors.py [--seed N] [--size N]
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--size", type=int, default=1000)
    args = p.parse_args()

    from synthetic_socio_wind_tunnel.agent.population import (
        LANE_COVE_PROFILE,
        sample_population,
    )
    from synthetic_socio_wind_tunnel.data_loader import (
        compute_social_priors_for_population,
        load_archetypes,
        load_social_prior_rules,
    )

    print(f"[audit] Loading archetypes + rules...")
    archetypes = load_archetypes()
    rules = load_social_prior_rules()
    print(f"[audit] {len(archetypes)} archetypes, {len(rules)} rules")

    print(f"[audit] Sampling {args.size} agents @ seed={args.seed}...")
    profile = LANE_COVE_PROFILE.model_copy(
        update={"name": "audit", "size": args.size},
    )
    agents = sample_population(profile, seed=args.seed, generate_identity=False)

    print(f"[audit] Computing social priors...")
    priors = compute_social_priors_for_population(
        agents, rules=rules, archetypes=archetypes, seed=args.seed,
    )
    print(f"[audit] Total tie records: {len(priors)}")

    rule_ties: dict[str, int] = defaultdict(int)
    pair_seen: set[tuple[str, str]] = set()
    distinct_pairs: dict[str, set] = defaultdict(set)
    for rec in priors:
        rule_id = rec.rule_id
        rule_ties[rule_id] += 1
        pair = tuple(sorted([rec.agent_a, rec.agent_b]))
        pair_seen.add(pair)
        distinct_pairs[rule_id].add(pair)

    print()
    print("=" * 60)
    print(f"{'rule':<28}{'records':>10}{'distinct_pairs':>17}")
    print("=" * 60)
    for rule in rules:
        n_rec = rule_ties.get(rule.rule_id, 0)
        n_pair = len(distinct_pairs.get(rule.rule_id, set()))
        print(f"{rule.rule_id:<28}{n_rec:>10}{n_pair:>17}")
    print("=" * 60)
    print(f"{'TOTAL distinct pairs':<28}{'':>10}{len(pair_seen):>17}")
    print()

    # Sanity assertions for next step's automated test:
    fired_rules = {r for r, n in rule_ties.items() if n > 0}
    print(f"[audit] Rules that fired ≥ 1 tie: {len(fired_rules)}/{len(rules)}")
    if len(fired_rules) < len(rules):
        missing = {r.rule_id for r in rules} - fired_rules
        print(f"[audit] Rules that did NOT fire: {sorted(missing)}")

    if len(pair_seen) > 100_000:
        print(f"[audit] ⚠ excessive pairs: {len(pair_seen)} > 100K threshold")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
