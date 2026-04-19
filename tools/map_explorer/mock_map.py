"""
Deprecated shim. The Lane Cove production loader moved to
`synthetic_socio_wind_tunnel.cartography.lanecove`; the fictional 新苑里
demo moved to `tools.map_explorer.demo_map`.

This file keeps `from tools.map_explorer.mock_map import ...` working
during the transition, but emits a `DeprecationWarning`. Remove after
downstream scripts have been updated.
"""
import warnings

warnings.warn(
    "tools.map_explorer.mock_map is deprecated; "
    "use synthetic_socio_wind_tunnel.cartography.lanecove "
    "(production Lane Cove loader) or tools.map_explorer.demo_map "
    "(fictional 新苑里 demo) instead.",
    DeprecationWarning,
    stacklevel=2,
)

from synthetic_socio_wind_tunnel.cartography.lanecove import (  # noqa: E402,F401
    create_atlas_from_osm,
    _infill_riverview,
    OSM_DATA_PATH,
    ENRICHED_DATA_PATH,
    ATLAS_CACHE_PATH,
    PROJ_CENTER_PATH,
)
from tools.map_explorer.demo_map import (  # noqa: E402,F401
    create_atlas,
    create_demo_knowledge_maps,
    create_ledger_with_demo_knowledge,
)
