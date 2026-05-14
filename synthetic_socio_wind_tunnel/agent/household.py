"""HouseholdRegistry — sim-level service for household membership lookup.

A2 / realism-household-coupling. Multiple agents in the same household share
a household_id and home_location. This registry exposes the membership graph
so plan generation, perception, and social-priors can query "who lives with
whom".

Construction is from a list of AgentProfile post-sample. Read-only after.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.agent.profile import AgentProfile


@dataclass(frozen=True)
class HouseholdRegistry:
    """Membership lookup keyed by household_id."""

    _members_by_household: dict[str, tuple[str, ...]]
    _household_by_agent: dict[str, str]
    _home_by_household: dict[str, str]
    _profile_by_agent: dict[str, "AgentProfile"]

    @classmethod
    def from_profiles(cls, profiles: list["AgentProfile"]) -> "HouseholdRegistry":
        """Build from a sampled list of AgentProfile.

        Empty household_id is treated as "solo household" using agent_id as
        synthetic household_id (backwards compat with pre-A2 sampling).
        """
        members: dict[str, list[str]] = defaultdict(list)
        household_of: dict[str, str] = {}
        home_of: dict[str, str] = {}
        profile_of: dict[str, "AgentProfile"] = {}
        for p in profiles:
            hh = p.household_id or f"household_{p.agent_id}"
            members[hh].append(p.agent_id)
            household_of[p.agent_id] = hh
            # If multiple agents share this household_id, last write wins for
            # home_location — but in practice they SHOULD all have identical
            # home_location, so the value is consistent.
            home_of[hh] = p.home_location
            profile_of[p.agent_id] = p
        return cls(
            _members_by_household={k: tuple(v) for k, v in members.items()},
            _household_by_agent=dict(household_of),
            _home_by_household=dict(home_of),
            _profile_by_agent=dict(profile_of),
        )

    def members_of(self, household_id: str) -> list["AgentProfile"]:
        """Return all agent profiles in the given household."""
        ids = self._members_by_household.get(household_id, ())
        return [self._profile_by_agent[a] for a in ids if a in self._profile_by_agent]

    def household_of(self, agent_id: str) -> str | None:
        """Return the household_id this agent belongs to."""
        return self._household_by_agent.get(agent_id)

    def home_location_for(self, household_id: str) -> str | None:
        """Return the shared home_location for a household."""
        return self._home_by_household.get(household_id)

    def siblings_of(self, agent_id: str) -> list["AgentProfile"]:
        """Return household members other than self (could be empty)."""
        hh = self._household_by_agent.get(agent_id)
        if hh is None:
            return []
        return [
            p for p in self.members_of(hh) if p.agent_id != agent_id
        ]

    def household_count(self) -> int:
        return len(self._members_by_household)


__all__ = ["HouseholdRegistry"]
