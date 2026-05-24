"""Extract a_44_0290 (33F, profile says retail_worker, 2 kids, Lane Cove学区房)
from all 4 seed-44 snapshots. Same data shape as Hannah extract."""
import ijson
import json
from pathlib import Path
from decimal import Decimal
from collections import defaultdict

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
OUT = REPO / "data/analysis/case_studies/a0290_4variants.json"

BASE = REPO / "data/experiments/20260522_165045_publishable_v7_day4to13_fork_seed44_BACKUP_20260522_213319_FULL_ALLVARIANTS"
SNAPSHOTS = {
    "baseline":           BASE / "variant_baseline" / "seed_44_pid12670_tick4020.snapshot.json",
    "hyperlocal_push":    BASE / "variant_hyperlocal_push" / "seed_44_pid12565_tick4008.snapshot.json",
    "global_distraction": BASE / "variant_global_distraction" / "seed_44_pid12642_tick4020.snapshot.json",
    "phone_friction":     BASE / "variant_phone_friction" / "seed_44_pid12609_tick4020.snapshot.json",
}

HERO = "a_44_0290"


def deci(o):
    if isinstance(o, Decimal): return float(o)
    if isinstance(o, dict): return {k: deci(v) for k, v in o.items()}
    if isinstance(o, list): return [deci(x) for x in o]
    return o


def extract_one(snap_path):
    print(f"  reading {snap_path.name} ({snap_path.stat().st_size/1e6:.0f} MB)...", flush=True)
    out = {
        "snapshot_path": str(snap_path),
        "schema_version": None,
        "tick_index": None, "day_index": None, "simulated_time": None,
        "weather": None, "time_of_day": None,
        "agent_runtime_state": None, "ledger_entity": None,
        "explored_locations": [], "agent_events": [],
        "consumed_feed_item_ids": [], "replan_count_today": 0,
        "push_deliveries": [], "push_contents": {},
        "dialogue_summaries": [], "dialogue_infos": [],
        "known_infos": {}, "share_counts_for_mine": {},
    }

    for top_key in ["schema_version", "tick_index", "day_index", "simulated_time"]:
        with open(snap_path) as f:
            for item in ijson.items(f, top_key):
                out[top_key] = item; break

    with open(snap_path) as f:
        for item in ijson.items(f, "ledger_state.weather"):
            out["weather"] = item; break
    with open(snap_path) as f:
        for item in ijson.items(f, "ledger_state.time_of_day"):
            out["time_of_day"] = item; break
    with open(snap_path) as f:
        for item in ijson.items(f, f"ledger_state.entities.{HERO}"):
            out["ledger_entity"] = deci(item); break
    with open(snap_path) as f:
        for item in ijson.items(f, f"ledger_state.explored_locations.{HERO}"):
            out["explored_locations"] = item; break

    with open(snap_path) as f:
        for item in ijson.items(f, f"agent_runtime_states.{HERO}"):
            out["agent_runtime_state"] = deci(item); break

    with open(snap_path) as f:
        for item in ijson.items(f, f"memory_store_state.agent_events.{HERO}"):
            out["agent_events"] = deci(item); break
    with open(snap_path) as f:
        for item in ijson.items(f, f"memory_store_state.consumed_feed_item_ids.{HERO}"):
            out["consumed_feed_item_ids"] = item; break
    with open(snap_path) as f:
        for item in ijson.items(f, f"memory_store_state.replan_count_today.{HERO}"):
            out["replan_count_today"] = item; break

    delivered_feed_ids = []
    with open(snap_path) as f:
        for entry in ijson.items(f, "attention_service_state.delivery_log.item"):
            if entry.get("recipient_id") == HERO:
                out["push_deliveries"].append(deci(entry))
                delivered_feed_ids.append(entry["feed_item_id"])
    needed = set(delivered_feed_ids)
    if needed:
        with open(snap_path) as f:
            for fid, item in ijson.kvitems(f, "attention_service_state.feed_index"):
                if fid in needed:
                    out["push_contents"][fid] = deci(item)
                    if len(out["push_contents"]) >= len(needed):
                        break

    hero_dlg_ids = []
    with open(snap_path) as f:
        for did, summ in ijson.kvitems(f, "dialogue_service_state.dialogue_summaries"):
            if summ.get("initiator_id") == HERO or summ.get("invitee_id") == HERO:
                out["dialogue_summaries"].append(deci(summ))
                hero_dlg_ids.append(did)

    with open(snap_path) as f:
        for info_id, info in ijson.kvitems(f, "conversation_service_state.infos"):
            if not info_id.startswith("info_dlg_"): continue
            did = info_id[len("info_dlg_"):]
            if HERO in did or any(d in did for d in hero_dlg_ids):
                out["dialogue_infos"].append(deci(info))

    with open(snap_path) as f:
        for item in ijson.items(f, f"conversation_service_state.known.{HERO}"):
            out["known_infos"] = deci(item); break

    with open(snap_path) as f:
        for info_id, count in ijson.kvitems(f, "conversation_service_state.share_count"):
            if HERO in info_id:
                out["share_counts_for_mine"][info_id] = count

    print(f"    done · {len(out['agent_events'])} events · {len(out['push_deliveries'])} pushes · "
          f"{len(out['dialogue_summaries'])} dialogues · {len(out['known_infos'])} known infos · "
          f"{len(out['explored_locations'])} explored", flush=True)
    return out


print(f"Extracting {HERO} (33F retail_worker family_with_kids, seed 44)...", flush=True)
all_data = {"agent_id": HERO, "variants": {}}
for variant, path in SNAPSHOTS.items():
    print(f"\n=== {variant} ===", flush=True)
    all_data["variants"][variant] = extract_one(path)

print(f"\nWriting {OUT}...", flush=True)
json.dump(all_data, open(OUT, "w"), ensure_ascii=False, indent=2)
print(f"  done · {OUT.stat().st_size/1e6:.1f} MB", flush=True)

print("\n=== COMPARISON ACROSS 4 VARIANTS ===")
for v in ["baseline", "hyperlocal_push", "global_distraction", "phone_friction"]:
    d = all_data["variants"][v]
    rs = d.get("agent_runtime_state", {}) or {}
    plan_steps = (rs.get("plan", {}) or {}).get("steps", [])
    plan_desc = ""
    if plan_steps:
        p = plan_steps[0]
        plan_desc = f"{p.get('time','?')} {p.get('action','?')} → {p.get('destination','?')}"
    entity = d.get("ledger_entity", {}) or {}
    n_events = len(d.get("agent_events", []))
    kinds = defaultdict(int)
    for e in d.get("agent_events", []):
        kinds[e.get("kind", "?")] += 1
    n_noticed = sum(1 for e in d.get("agent_events", [])
                    if e.get("kind") == "encounter" and "noticed" in (e.get("tags") or []))
    print(f"\n  ● {v}:  end={entity.get('location_id','?')} (arr {entity.get('arrived_at','?')})")
    print(f"    plan: {plan_desc}")
    print(f"    events: {n_events} | life {kinds['life_history']} / refl {kinds['reflection']} / "
          f"shared {kinds['shared_memory']} / push {kinds['notification']} / "
          f"enc {kinds['encounter']} (noticed {n_noticed}) / act {kinds['action']}")
    print(f"    pushes: delivered {len(d.get('push_deliveries', []))} | "
          f"contents {len(d.get('push_contents', {}))} | consumed {len(d.get('consumed_feed_item_ids', []))}")
    print(f"    dialogues: {len(d.get('dialogue_summaries', []))} | infos: {len(d.get('dialogue_infos', []))}")
