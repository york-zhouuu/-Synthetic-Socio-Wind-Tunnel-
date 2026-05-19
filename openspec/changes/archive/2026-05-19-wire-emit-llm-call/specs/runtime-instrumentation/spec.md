## ADDED Requirements

### Requirement: emit_llm_call SHALL fire from tier client generate() success path

Every tier client's `generate()` method in `tools/tier_llm_factory.py` (Stub / Gemini / DeepSeek / Anthropic / Volces) SHALL call `get_instrumentation().emit_llm_call(...)` after `_run_with_retry` returns successfully. The call SHALL pass:

- `tier` (sonnet / haiku / nano — passed in via constructor)
- `provider` (stub / gemini / deepseek / anthropic / volces — constructor param)
- `model` (`self._model`)
- `kind` — defaulted to `"unknown"` if caller didn't supply (do_something / generate_message / etc.)
- `agent_id` — defaulted to None if caller didn't supply
- `latency_ms` — measured via `time.perf_counter()` around `_run_with_retry`
- `status="success"`
- `attempt=0` for success (retries are emitted as separate RETRY events)
- `max_attempts=policy.max_attempts`
- `key_id` — index of the key actually used (0 for single-key providers like Anthropic)

emit failures SHALL NOT propagate — try/except per existing instrumentation isolation rule.

#### Scenario: dev smoke subprocess writes llm.jsonl with success records

- **WHEN** dev smoke 50 agent × 1 day runs with `LLM_SAMPLE_RATE=1.0` (force all-sample for test)
- **THEN** `seed_42.llm.jsonl` SHALL exist and contain at least 100 lines, each with `status="success"` and a numeric `latency_ms > 0`

#### Scenario: each tier client wires emit

- **WHEN** dev smoke completes
- **THEN** the set of `tier` values seen in llm.jsonl SHALL include the tiers actually used (at least one of sonnet/haiku/nano)

### Requirement: emit_llm_call SHALL fire from do_something fallback path

`synthetic_socio_wind_tunnel/agent/operations/handlers/do_something.py` handler's except branches (AllKeysOpenError, generic Exception, unparseable response) SHALL emit_llm_call with `status="fallback"` and `exc_class=<full class path>` (or `"unparseable_response"` for the parse-failure branch).

#### Scenario: fallback path emits to llm.jsonl

- **GIVEN** worker hits AllKeysOpenError or unparseable LLM response
- **WHEN** fallback path taken in do_something handler
- **THEN** llm.jsonl SHALL have a record with `status="fallback"` and either `exc_class="...AllKeysOpenError"` or `exc_class="unparseable_response"`
