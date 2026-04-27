# Calibration data sources — Lane Cove

This doc lists the three external data snapshots `agent-calibration` consumes,
with download steps and field-mapping notes. All are static JSON shipped in
git at `data/calibration/`.

| File | Source | Purpose |
|---|---|---|
| `abs_census_lanecove_2021.json` | ABS Census 2021 Lane Cove SA2 | Population calibration (6 dims) |
| `abs_travel_survey_sydney_2021.json` | BTS NSW Household Travel Survey 2021 | OD matrix + departure-time |
| `lanecove_popular_times.json` | Outscraper Google Maps API | Per-POI hourly visit ground truth |

---

## 1. ABS Census 2021 Lane Cove SA2

**Source URL**: https://www.abs.gov.au/census/find-census-data/quickstats/2021/SAL11857
(Lane Cove SAL = Suburb and Locality 11857; SA2 = Statistical Area 2 ≈ same area)

**Fields needed** (use ABS DataPack or QuickStats CSV exports):

| ABS table | Our dim | Bucket mapping |
|---|---|---|
| G01 Age | `age` | 5-yr buckets `0-4`, `5-9`, ..., `85+` |
| G01 Sex | `gender` | `male` / `female`; `non_binary` = 0 (ABS Census 2021 binary only) |
| G31 Tenure type | `housing_tenure` | `Owned outright` + `Owned with mortgage` → `owner_occupier`; `Rented` → `renter`; `Public housing/other` → `public_housing` |
| G17 Total weekly income | `income_tier` | bottom 30% → `low`; middle 40% → `mid`; top 30% → `high` (cut by Lane Cove medians) |
| G09 Ancestry | `ethnicity_group` | top 5 ancestries individually + `other`; record `_migrant-1gen` markers from G05 birthplace |
| G46 Method of travel to work | `work_mode` | `Train/Bus/Car driver/...` → `commute`; `Worked at home` → `remote`; `Did not work` → `nonworking`; shift inferred from occupation if available else conservative `commute` |

**JSON schema** (`data/calibration/abs_census_lanecove_2021.json`):

```jsonc
{
  "source": "ABS Census 2021 Lane Cove SA2 (SAL11857)",
  "downloaded": "YYYY-MM-DD",
  "url": "https://www.abs.gov.au/...",
  "total_population": <int>,
  "distributions": {
    "age": {"0-4": 0.063, "5-9": 0.061, ..., "85+": 0.012},
    "gender": {"male": 0.487, "female": 0.513, "non_binary": 0.0},
    "housing_tenure": {"owner_occupier": 0.58, "renter": 0.39, "public_housing": 0.03},
    "income_tier": {"low": 0.31, "mid": 0.42, "high": 0.27},
    "ethnicity_group": {"AU-born": 0.55, ..., "other": 0.07},
    "work_mode": {"commute": 0.41, "remote": 0.18, "shift": 0.07, "nonworking": 0.34}
  }
}
```

All distributions MUST sum to 1.0 (validated by `PopulationProfile`).

---

## 2. ABS Travel Survey 2021 (Sydney)

**Source URL**: https://www.transport.nsw.gov.au/data-and-research/passenger-travel/surveys/household-travel-survey
(Open Data — NSW Household Travel Survey)

**Fields needed**:
- Journey-to-work OD matrix at SA2 level (subset to rows/cols touching Lane Cove)
- Departure-time histogram (hourly bins, weekday)

**JSON schema**:

```jsonc
{
  "source": "BTS NSW Household Travel Survey 2021",
  "downloaded": "YYYY-MM-DD",
  "url": "...",
  "od_matrix": {
    "sa2_codes": ["lane_cove", "north_sydney", "ryde", ...],
    "matrix": [[100, 80, 60, ...], ...]  // counts; rows = origin, cols = dest
  },
  "departure_time_distribution": {
    "5": 0.01, "6": 0.04, "7": 0.18, "8": 0.32, "9": 0.18, ...  // hour → fraction
  }
}
```

**Modeling note**: sim uses location_ids inside Lane Cove only; we map all
sim destinations to a single "lane_cove" SA2 row, and ABS-claim "outbound"
trips to neighboring SA2s map to "agent leaves community" as
home → far-from-home destination. Disclose this approximation in
publishable report.

---

## 3. Lane Cove Popular Times (Outscraper)

**Source**: Outscraper Google Maps API (https://outscraper.com)

**Setup**:
1. Sign up at https://outscraper.com (free tier: 500 businesses/month)
2. Get API key from dashboard
3. `export OUTSCRAPER_API_KEY=...`
4. `python3 tools/fetch_popular_times.py --num-pois 20`

Output written to `data/calibration/lanecove_popular_times.json` automatically.
**Commit the JSON to git** so subsequent runs don't need API access.

**Re-fetching**: Re-run the script (Outscraper handles freshness). Quota:
20 POIs × 1 fetch = 20 businesses; well within 500/month free tier.

**JSON schema** (per `tools/fetch_popular_times.py`):

```jsonc
{
  "source": "Outscraper Google Maps API",
  "fetched": "YYYY-MM-DD",
  "query": "Lane Cove NSW Australia",
  "n_pois": 20,
  "pois": [
    {
      "id": "...",
      "name": "...",
      "place_id": "...",
      "category": "cafe",
      "lat": -33.812, "lon": 151.165,
      "popularity": [
        // 7 lists of 24 ints each (% of weekly peak), Mon..Sun
        [0, 0, 0, 5, 15, 30, 45, ..., 10, 0],
        ...
      ]
    },
    ...
  ]
}
```

**Fallback** if Outscraper free tier ever changes policy: SerpAPI
(https://serpapi.com) also offers Google Maps populartimes; rewrite
`fetch_popular_times.py` to use it (HTTP + parse, ~50 LOC change).

---

## Re-running calibration after data refresh

```bash
# After updating any of the three JSONs:
python3 tools/run_calibration.py --mode all --seed 42

# Output:
data/calibration/calibration_report.json
```

`tools/run_variant_suite.py --mode publishable` reads the report; if any
section is `state: missing-data` or `acceptance_level: failing`, the suite
report flags `[unpublishable preview]` per validation-strategy spec.

---

## Privacy & licensing

- ABS Census + Travel Survey: Creative Commons BY 4.0 (Australian Government). Cite
  when publishing.
- Outscraper: paid SaaS scraping Google data. Their ToS allows storing
  fetched data; Google data itself is subject to Google's ToS. Use is
  research-only; don't redistribute the JSON beyond academic context.
- All three contain only aggregated statistics — no PII.
