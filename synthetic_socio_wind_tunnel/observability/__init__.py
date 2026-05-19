"""Runtime instrumentation — structured埋点 covering all worker phases.

See `synthetic_socio_wind_tunnel.observability.instrumentation` for the
RuntimeInstrumentation class. Use `get_instrumentation()` to obtain the
process singleton; call emit methods or `sample_metrics` from桩点.

Three output files per worker (in INSTRUMENTATION_OUTPUT_DIR):
- seed_<N>.memstat.jsonl   periodic memory/CPU samples
- seed_<N>.events.jsonl    discrete events (phase, evict, retry, snapshot)
- seed_<N>.llm.jsonl       per LLM call (sampled for success, 100% for errors)
"""

from synthetic_socio_wind_tunnel.observability.instrumentation import (
    RuntimeInstrumentation,
    get_instrumentation,
    reset_for_tests,
)

__all__ = [
    "RuntimeInstrumentation",
    "get_instrumentation",
    "reset_for_tests",
]
