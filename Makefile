.PHONY: help test test-cartography enrich-map fetch-overture conflate \
        regenerate-atlas diagnose-atlas clean-atlas-cache

help:
	@echo "Targets:"
	@echo "  test               Run full pytest suite"
	@echo "  test-cartography   Run only cartography tests (+ lane cove connectivity gate)"
	@echo "  enrich-map         Full enrichment chain: fetch-overture → conflate → regenerate-atlas → diagnose-atlas"
	@echo "  fetch-overture     Pull Overture buildings + places for Lane Cove"
	@echo "  conflate           Merge OSM + Overture into data/lanecove_enriched.geojson"
	@echo "  regenerate-atlas   Delete atlas cache and import from the best-available source"
	@echo "  diagnose-atlas     Print connectivity + enrichment metrics on current atlas"
	@echo "  clean-atlas-cache  Remove data/lanecove_atlas.json so next load rebuilds"

test:
	python3 -m pytest tests/ -v

test-cartography:
	python3 -m pytest tests/test_cartography.py -v

fetch-overture:
	python3 tools/fetch_overture.py

conflate:
	python3 tools/enrich_map.py

clean-atlas-cache:
	rm -f data/lanecove_atlas.json

regenerate-atlas: clean-atlas-cache
	python3 -c "from tools.map_explorer.mock_map import create_atlas_from_osm; create_atlas_from_osm()"

diagnose-atlas:
	python3 tools/diagnose_atlas.py

enrich-map: fetch-overture conflate regenerate-atlas diagnose-atlas
	@echo "Enrichment pipeline complete."
