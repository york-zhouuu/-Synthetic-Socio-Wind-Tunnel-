# AA: Encounter → dialogue conversion

Memstat dialogue_service tracks live + evicted (completed) + ended_unevicted.
`peak_started` = max(live + evicted + ended_unevicted) over the run.

| variant | enc total | unique pairs | peak dialogues | per 1000 encounters | per unique pair |
|---|---|---|---|---|---|
| baseline | 8.1M | 467,419 | 821 | 0.1024 | 0.0018 |
| hyperlocal_push | 38.4M | 539,890 | 959 | 0.0251 | 0.0018 |
| global_distraction | 10.7M | 452,498 | 859 | 0.0804 | 0.0019 |
| phone_friction | 36.7M | 531,983 | 997 | 0.0272 | 0.0019 |

## Headline

- BL: ~0.10 dialogues per 1000 encounters (low conversion)
- HP/PF: ~0.025 — actually LOWER conversion (because encounter density way up)
- Per-pair: BL ~1.8 dialogues/pair, HP ~1.7 — similar (per-pair rate stable)
- Total dialogues started: BL ~820, HP ~940, GD ~860, PF ~1000

**Interpretation**: HP increases encounter volume 5×, but dialogue per encounter ratio drops.
The dialogue queue saturates / processes the SAME pairs more efficiently. Total dialogue volume
modestly increases (~10-20%) while encounters explode (5×).

→ Encounter ≠ dialogue. The bottleneck is dialogue duration + LLM compute, not encounter availability.
