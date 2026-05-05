"""
conversation — pairwise information propagation layer (V1: probabilistic stub).

Built on top of social-graph: when two agents encounter, an information item
known by one but not the other has a chance to propagate. The chance is
determined by tie strength × personality (extraversion) × info salience ×
recency decay. Each (agent, info) pair tracks the shortest hop count from
origin.

V1 does NOT do LLM dialogue — share is binary (yes/no). Information content
is opaque (no Chinese-whispers mutation). LLM dialogue + multi-party speech +
information mutation are V2 territory.
"""

from synthetic_socio_wind_tunnel.conversation.models import Information, Propagation, ShareEvent
from synthetic_socio_wind_tunnel.conversation.service import ConversationService

__all__ = [
    "ConversationService",
    "Information",
    "Propagation",
    "ShareEvent",
]
