# Raw calibration data — sources

Files here are local-only working copies (gitignored except this README and
small per-area excerpts). Download steps below.

## ABS Census 2021 — Lane Cove SA2 (code 121011686)

**Source 1: General Community Profile DataPack (CSV bundle, ~34 MB)**
- URL: https://www.abs.gov.au/census/find-census-data/datapacks
- Choice: Geography "Statistical Area Level 2 (SA2)", Pack "General Community Profile"
- Region: NSW
- File downloaded: `2021_GCP_SA2_for_NSW_short-header.zip`
- Tables we read:
  - `G01` — Age × Sex (population baseline)
  - `G33` — Tenure type (housing)
  - `G17A/B/C` — Total personal weekly income
  - `G09A/B/C` — Ancestry (top responses)
  - `G46A/B` — Method of travel to work
  - `G47A-F` — Place of work × method (for OD matrix)

**Source 2: QuickStats LGA report (PDF, single page)**
- URL: https://www.abs.gov.au/census/find-census-data/quickstats/2021/LGA14700
- File downloaded: `2021 Lane Cove, Census All persons QuickStats.pdf`
- Used as cross-reference for medians (median age 37, median household income $2801,
  M/F 49.0/51.0). LGA Lane Cove (39,438 ppl) is broader than SA2 Lane Cove (~21k);
  we calibrate against SA2 since the structured CSV is at that level.

## Geography choice

Atlas extent ≈ Lane Cove suburb (clipped south of harbour). Closest single SA2 is
**121011686 Lane Cove** (4.47 km², ~21k people). Atlas slightly over-extends into
SA2 121011399 (Chatswood West / Lane Cove North) — calibration assumes demographic
homogeneity across this small over-extension. Future iteration could blend two
SA2s by area share.

## Downloaded snapshot

Run `python3 tools/convert_abs_census.py` to refresh the JSON output from these
raw files. Convert script reads from `~/Downloads/2021_GCP_SA2_for_NSW_short-header/`
(or `--datapack-dir`).
