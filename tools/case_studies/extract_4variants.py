"""Extract Mary's complete data from all 4 variant snapshots (BL/HP/GD/PF).

For each variant, pull:
- agent_runtime_state (location, plan, ai_town, hints)
- all memory_store agent_events (life_history, reflection, shared_memory, notification, encounter, action)
- consumed_feed_item_ids
- replan_count_today
- push deliveries (delivery_log filtered to Mary)
- push contents (feed_index for Mary's pushes)
- dialogues she was in (dialogue_summaries)
- conversation infos she was in (first-person summaries)
- known (gossip she heard, with hops)
- ledger entity (current location + arrived_at)
- ledger explored_locations
- positions data already extracted separately

Output: data/analysis/case_studies/mary_4variants.json
"""
import ijson
import json
from pathlib import Path
from decimal import Decimal
from collections import defaultdict

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
OUT = REPO / "data/analysis/case_studies/mary_4variants.json"

BASE = REPO / "data/experiments/20260521_185100_publishable_v6_day4to13_fork_seed43_BACKUP_20260522_143245"
SNAPSHOTS = {
    "baseline":           BASE / "variant_baseline" / "seed_43_pid70995_tick4020.snapshot.json",
    "hyperlocal_push":    BASE / "variant_hyperlocal_push" / "seed_43_pid69976_tick4020.snapshot.json",
    "global_distraction": BASE / "variant_global_distraction" / "seed_43_pid88532_tick4020.snapshot.json",
    "phone_friction":     BASE / "variant_phone_friction" / "seed_43_pid70415_tick4020.snapshot.json",
}

MARY = "a_43_0405"

def deci(o):
    if isinstance(o, Decimal): return float(o)
    if isinstance(o, dict): return {k: deci(v) for k, v in o.items()}
    if isinstance(o, list): return [deci(x) for x in o]
    return o


def extract_one(snap_path):
    """Stream through one snapshot, pull all Mary-related data."""
    print(f"  reading {snap_path.name} ({snap_path.stat().st_size/1e6:.0f} MB)...")
    out = {
        "snapshot_path": str(snap_path),
        "schema_version": None,
        "tick_index": None,
        "day_index": None,
        "simulated_time": None,
        "weather": None,
        "time_of_day": None,
        "agent_runtime_state": None,
        "ledger_entity": None,
        "explored_locations": [],
        "agent_events": [],
        "consumed_feed_item_ids": [],
        "replan_count_today": 0,
        "push_deliveries": [],
        "push_contents": {},
        "dialogue_summaries": [],
        "dialogue_infos": [],
        "known_infos": {},
        "share_counts_for_mine": {},
    }

    # Pass 1: top-level metadata
    print("    pass 1: top-level metadata")
    for top_key in ["schema_version", "tick_index", "day_index", "simulated_time"]:
        with open(snap_path) as f:
            for item in ijson.items(f, top_key):
                out[top_key] = item
                break

    # Pass 2: ledger_state.weather / time_of_day / entities for Mary / explored_locations for Mary
    print("    pass 2: ledger_state")
    with open(snap_path) as f:
        for item in ijson.items(f, "ledger_state.weather"):
            out["weather"] = item; break
    with open(snap_path) as f:
        for item in ijson.items(f, "ledger_state.time_of_day"):
            out["time_of_day"] = item; break
    with open(snap_path) as f:
        for item in ijson.items(f, f"ledger_state.entities.{MARY}"):
            out["ledger_entity"] = deci(item); break
    with open(snap_path) as f:
        for item in ijson.items(f, f"ledger_state.explored_locations.{MARY}"):
            out["explored_locations"] = item; break

    # Pass 3: agent_runtime_state for Mary
    print("    pass 3: agent_runtime_state")
    with open(snap_path) as f:
        for item in ijson.items(f, f"agent_runtime_states.{MARY}"):
            out["agent_runtime_state"] = deci(item); break

    # Pass 4: memory_store_state for Mary
    print("    pass 4: memory_store agent_events")
    with open(snap_path) as f:
        for item in ijson.items(f, f"memory_store_state.agent_events.{MARY}"):
            out["agent_events"] = deci(item); break
    with open(snap_path) as f:
        for item in ijson.items(f, f"memory_store_state.consumed_feed_item_ids.{MARY}"):
            out["consumed_feed_item_ids"] = item; break
    with open(snap_path) as f:
        for item in ijson.items(f, f"memory_store_state.replan_count_today.{MARY}"):
            out["replan_count_today"] = item; break

    # Pass 5: attention_service push deliveries to Mary + content lookup
    print("    pass 5: attention_service push deliveries")
    delivered_feed_ids = []
    with open(snap_path) as f:
        for entry in ijson.items(f, "attention_service_state.delivery_log.item"):
            if entry.get("recipient_id") == MARY:
                out["push_deliveries"].append(deci(entry))
                delivered_feed_ids.append(entry["feed_item_id"])
    needed = set(delivered_feed_ids)
    if needed:
        print(f"    pass 6: feed_index content (looking up {len(needed)} push items)")
        with open(snap_path) as f:
            for fid, item in ijson.kvitems(f, "attention_service_state.feed_index"):
                if fid in needed:
                    out["push_contents"][fid] = deci(item)
                    if len(out["push_contents"]) >= len(needed):
                        break

    # Pass 7: dialogue_summaries — Mary involved
    print("    pass 7: dialogues + conversation infos")
    mary_dlg_ids = []
    with open(snap_path) as f:
        for did, summ in ijson.kvitems(f, "dialogue_service_state.dialogue_summaries"):
            if summ.get("initiator_id") == MARY or summ.get("invitee_id") == MARY:
                out["dialogue_summaries"].append(deci(summ))
                mary_dlg_ids.append(did)

    # conversation infos for Mary's dialogues OR mentioning Mary
    with open(snap_path) as f:
        for info_id, info in ijson.kvitems(f, "conversation_service_state.infos"):
            if not info_id.startswith("info_dlg_"): continue
            did = info_id[len("info_dlg_"):]
            if MARY in did or any(d in did for d in mary_dlg_ids):
                out["dialogue_infos"].append(deci(info))

    # Pass 8: Mary's known infos (gossip she heard, including hop counts)
    print("    pass 8: gossip Mary heard")
    with open(snap_path) as f:
        for item in ijson.items(f, f"conversation_service_state.known.{MARY}"):
            out["known_infos"] = deci(item); break

    # Pass 9: share_count for Mary's own infos
    print("    pass 9: share counts for Mary's origin infos")
    # Mary's origin info_ids are info_dlg_d_a_43_0405_*_*
    with open(snap_path) as f:
        for info_id, count in ijson.kvitems(f, "conversation_service_state.share_count"):
            if MARY in info_id:
                out["share_counts_for_mine"][info_id] = count

    print(f"    ✓ done · {len(out['agent_events'])} events · {len(out['push_deliveries'])} pushes · "
          f"{len(out['dialogue_summaries'])} dialogues · {len(out['known_infos'])} known infos · "
          f"{len(out['explored_locations'])} explored locs")
    return out


# ──────────────────────────────────────────────────────────────────────
print("Extracting Mary's data from 4 variant snapshots...")
all_data = {"agent_id": MARY, "variants": {}}
for variant, path in SNAPSHOTS.items():
    print(f"\n=== {variant} ===")
    all_data["variants"][variant] = extract_one(path)

print(f"\nWriting {OUT}...")
json.dump(all_data, open(OUT, "w"), ensure_ascii=False, indent=2)
size_mb = OUT.stat().st_size / 1e6
print(f"  done · {size_mb:.1f} MB")

# Summary comparison
print("\n=== COMPARISON ACROSS 4 VARIANTS ===")
for v in ["baseline", "hyperlocal_push", "global_distraction", "phone_friction"]:
    d = all_data["variants"][v]
    rs = d.get("agent_runtime_state", {}) or {}
    plan_steps = (rs.get("plan", {}) or {}).get("steps", [])
    plan_desc = ""
    if plan_steps:
        p = plan_steps[0]
        plan_desc = f"{p.get('time','?')} {p.get('action','?')} → {p.get('destination','?')}  ({p.get('reason','-')})"
    entity = d.get("ledger_entity", {}) or {}
    n_events = len(d.get("agent_events", []))
    kinds = defaultdict(int)
    for e in d.get("agent_events", []):
        kinds[e.get("kind", "?")] += 1
    print(f"\n  ● {v}:")
    print(f"    current location: {entity.get('location_id', '?')} (arrived {entity.get('arrived_at','?')})")
    print(f"    plan: {plan_desc}")
    print(f"    explored locations: {len(d.get('explored_locations', []))}")
    print(f"    events: {n_events} (life {kinds['life_history']} / refl {kinds['reflection']} / "
          f"shared {kinds['shared_memory']} / push {kinds['notification']} / "
          f"enc {kinds['encounter']} / act {kinds['action']})")
    print(f"    pushes delivered: {len(d.get('push_deliveries', []))}")
    print(f"    distinct push contents: {len(d.get('push_contents', {}))}")
    print(f"    consumed push ids: {len(d.get('consumed_feed_item_ids', []))}")
    print(f"    dialogues: {len(d.get('dialogue_summaries', []))}")
    print(f"    dialogue infos (incl. others mentioning Mary): {len(d.get('dialogue_infos', []))}")
    print(f"    gossip known (hops>=0): {len(d.get('known_infos', {}))}")
    own_infos_shared = sum(d.get("share_counts_for_mine", {}).values())
    print(f"    her own dialogues shared by total {own_infos_shared} agents")
