"""Extract all real dialogue summaries (LLM-generated first-person narratives)
for Mary / Mike / Frank from the simulation snapshot.

Output: data/analysis/case_studies/dialogues.json
"""
import ijson
import json
from pathlib import Path
from decimal import Decimal
from collections import defaultdict

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
SNAP = REPO / "data/experiments/20260521_185100_publishable_v6_day4to13_fork_seed43_BACKUP_20260522_143245/variant_hyperlocal_push/seed_43_pid69976_tick4020.snapshot.json"
OUT = REPO / "data/analysis/case_studies/dialogues.json"


def decimal_to_float(o):
    if isinstance(o, Decimal): return float(o)
    if isinstance(o, dict): return {k: decimal_to_float(v) for k, v in o.items()}
    if isinstance(o, list): return [decimal_to_float(x) for x in o]
    return o


TARGETS = {
    "a_43_0012": "frank",
    "a_43_0405": "mary",
    "a_43_0192": "mike",
}

# Collect:
# 1. Dialogues that involve target agents (as initiator or invitee)
# 2. Their conversation info content (LLM summary)

print("Streaming dialogue_summaries...")
my_dialogues = defaultdict(list)  # target_aid → [dialogue summary dict]
all_dialogue_summaries = {}
with open(SNAP) as f:
    for did, summ in ijson.kvitems(f, "dialogue_service_state.dialogue_summaries"):
        init = summ.get("initiator_id", "")
        invitee = summ.get("invitee_id", "")
        all_dialogue_summaries[did] = decimal_to_float(summ)
        for t in TARGETS:
            if init == t or invitee == t:
                my_dialogues[t].append(decimal_to_float(summ))

for t, lbl in TARGETS.items():
    print(f"  {lbl} ({t}): {len(my_dialogues[t])} dialogue summaries")

print("\nStreaming conversation_service_state.infos to find dialogue contents...")
info_content = {}
with open(SNAP) as f:
    for info_id, info in ijson.kvitems(f, "conversation_service_state.infos"):
        if not info_id.startswith("info_dlg_"):
            continue
        # info_id = info_dlg_{dialogue_id}
        did = info_id[len("info_dlg_"):]
        for t in TARGETS:
            if t in did:
                info_content[did] = decimal_to_float(info)
                break

print(f"  Matched {len(info_content)} dialogue info entries\n")

# Build per-target enriched dialogue list with content + day inference
TICKS_PER_DAY = 288

def tick_to_day(tick):
    # Tick is global cumulative since simulation start
    # Day 0 = ticks 0-287, etc.
    return tick // TICKS_PER_DAY

out = {}
for t, lbl in TARGETS.items():
    rich = []
    for summ in my_dialogues[t]:
        did = summ["dialogue_id"]
        info = info_content.get(did, {})
        partner_id = summ["invitee_id"] if summ["initiator_id"] == t else summ["initiator_id"]
        rich.append({
            "dialogue_id": did,
            "partner": partner_id,
            "location": summ.get("target_location_id"),
            "started_tick": summ.get("started_tick"),
            "ended_tick": summ.get("ended_tick"),
            "day_estimate": tick_to_day(summ.get("started_tick", 0)),
            "msg_count": summ.get("message_count"),
            "end_reason": summ.get("end_reason"),
            "content": info.get("content", ""),
            "origin_agent": info.get("origin_agent_id"),
            "salience": info.get("salience", 0),
        })
    rich.sort(key=lambda x: x["started_tick"] or 0)
    out[lbl] = rich

json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=2)
print(f"Written {OUT} ({OUT.stat().st_size / 1e3:.0f} KB)")

# Summary
print("\n=== Summary ===")
for lbl, dialogues in out.items():
    print(f"\n{lbl}: {len(dialogues)} dialogues")
    for d in dialogues:
        c = d["content"][:120].replace("\n", " ")
        print(f"  tick {d['started_tick']} (~day {d['day_estimate']}) · with {d['partner']} at {d['location']}")
        print(f"    {c}...")
