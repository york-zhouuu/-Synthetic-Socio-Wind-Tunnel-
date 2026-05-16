"""data_loader — load curated, real-world data into the simulation.

Currently:
- `lanecove`: Lane Cove (Sydney NSW 2066) shared community memories,
  conversation topic seeds, and (future) social-structure priors derived
  from public sources (Council, ABS Census, local news).

These loaders are run-start helpers — they take a MemoryService /
SocialGraphService / etc. and inject pre-computed records BEFORE the sim
loop starts, so protagonist agents have realistic local context to draw
from in their first dialogues / do_something prompts.
"""

from synthetic_socio_wind_tunnel.data_loader.lanecove import (
    NEIGHBORHOOD_LANDMARKS,
    ArchetypeRecord,
    ConversationTopicRecord,
    LifeHistoryRecord,
    PriorTieRecord,
    SharedMemoryRecord,
    SocialPriorRule,
    compute_social_priors_for_population,
    generate_identity_text_for_protagonists,
    generate_life_history_for_protagonists,
    inject_life_history,
    inject_shared_memories_for_protagonists,
    inject_shared_memories_into_agent,
    load_archetypes,
    load_conversation_topics,
    load_shared_memories,
    load_social_prior_rules,
    match_archetype,
)
from synthetic_socio_wind_tunnel.data_loader.setup_cache import (
    SimulationContentCache,
    is_cache_complete,
    load_setup_cache,
    save_setup_cache,
)

__all__ = [
    "SharedMemoryRecord",
    "ArchetypeRecord",
    "ConversationTopicRecord",
    "LifeHistoryRecord",
    "SocialPriorRule",
    "PriorTieRecord",
    "load_shared_memories",
    "load_archetypes",
    "load_conversation_topics",
    "load_social_prior_rules",
    "match_archetype",
    "compute_social_priors_for_population",
    "inject_shared_memories_into_agent",
    "inject_shared_memories_for_protagonists",
    "generate_life_history_for_protagonists",
    "generate_identity_text_for_protagonists",
    "NEIGHBORHOOD_LANDMARKS",
    "inject_life_history",
    # setup-content-cache (2026-05-16)
    "SimulationContentCache",
    "load_setup_cache",
    "save_setup_cache",
    "is_cache_complete",
]
