## ADDED Requirements

### Requirement: run_variant_suite SHALL expose --num-protagonists CLI flag

`tools/run_variant_suite.py` MUST accept a `--num-protagonists` integer
argument that controls how many sampled agents are flagged
`is_protagonist=True` (Sonnet tier; LLM-driven decisions; receive
ai-town injections).

Default behaviour SHALL be `max(1, args.agents // 10)` (10% of population),
preserving current dev-mode speed.

Publishable runs SHOULD pass an explicit higher value (e.g. `--num-protagonists 500`
for `--agents 1000`) so variant-push effects are not diluted by a 90%
scripted-only population (A2 disclosure).

The value SHALL be forwarded to `run_seed_with_metrics(...,
num_protagonists=...)` for each seed.

#### Scenario: default is 10% of agents
- **WHEN** `run_variant_suite.py --agents 100` is invoked without
  `--num-protagonists`
- **THEN** the run SHALL use `num_protagonists = 10`

#### Scenario: explicit value overrides
- **WHEN** `run_variant_suite.py --agents 1000 --num-protagonists 500`
  is invoked
- **THEN** the run SHALL use `num_protagonists = 500` and at least 500
  sampled agents SHALL have `is_protagonist == True`

#### Scenario: minimum 1 protagonist
- **WHEN** `--agents 5` is invoked without `--num-protagonists`
- **THEN** the run SHALL use `num_protagonists = max(1, 5 // 10) = 1`
