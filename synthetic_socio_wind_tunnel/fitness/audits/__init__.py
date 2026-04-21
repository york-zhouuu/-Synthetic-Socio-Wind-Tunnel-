"""Individual audit category functions."""

from synthetic_socio_wind_tunnel.fitness.audits.cost import audit_cost_baseline
from synthetic_socio_wind_tunnel.fitness.audits.e1 import audit_e1_digital_lure
from synthetic_socio_wind_tunnel.fitness.audits.e2 import audit_e2_spatial_unlock
from synthetic_socio_wind_tunnel.fitness.audits.e3 import audit_e3_shared_perception
from synthetic_socio_wind_tunnel.fitness.audits.ledger import audit_ledger_observability
from synthetic_socio_wind_tunnel.fitness.audits.phase1_baseline import (
    audit_phase1_baseline,
)
from synthetic_socio_wind_tunnel.fitness.audits.phase2_gaps import audit_phase2_gaps
from synthetic_socio_wind_tunnel.fitness.audits.profile import audit_profile_distribution
from synthetic_socio_wind_tunnel.fitness.audits.scale import audit_scale_baseline
from synthetic_socio_wind_tunnel.fitness.audits.site import audit_site_fitness

__all__ = [
    "audit_cost_baseline",
    "audit_e1_digital_lure",
    "audit_e2_spatial_unlock",
    "audit_e3_shared_perception",
    "audit_ledger_observability",
    "audit_phase1_baseline",
    "audit_phase2_gaps",
    "audit_profile_distribution",
    "audit_scale_baseline",
    "audit_site_fitness",
]
