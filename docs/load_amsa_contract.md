# load_amsa contract (design only, nothing decided)

Scope: read AMSA CTS sub-area point files (`ct_nw_MM_YYYY_pt.shp` under `DATA_ROOT/raw`) into one frame. Every row below is **DECISION: Jack**. Evidence tags: `P#` = `scripts/s0/output/probe_s0.txt`; fixtures = `tests/synthetic.py`; config = `config/project.toml`.
**Evidence base: only July and August 2026 NW files were inspected. 2014-2025 is [Unverified].**

Known facts used: fields `craft_id, longitude, latitude, course, speed, type, length, beam, draught, timestamp`; float64 except `type`, `timestamp` (str); EPSG:4326; Jul 892,212 / Aug 992,794 rows (P1) [High]. Timestamp is `dd/mm/yyyy HH:MM:SS` 24-hour plus a redundant AM/PM tag; parsing as 12-hour (as the metadata says) silently drops ~49% of rows; 0 tag/hour conflicts in both months (P2) [High]. UTC per metadata; heuristic agrees (P3) [Unverified]. The metadata's field list is wrong in names and types (STATUS.md) [High].

## 1. Returns

| # | Recommendation | Alternative | Why | Cost if wrong | |
|---|---|---|---|---|---|
| R1 columns | Keep the 10 real lowercase names (P1) | Rename to uppercase as the probe did | Matches the files; no mapping layer to drift | Renaming later touches every module | DECISION: Jack |
| R2 dtypes | float64 for the 8 numeric fields as read; `type` as pandas `string` with `<NA>` | Downcast; `length`/`beam` to `Int16` as the metadata claims | P1 shows float64 on disk; metadata types are wrong [High] | Downcasting hides non-integral values [Unverified whether any exist] | DECISION: Jack |
| R3 time | New `timestamp_utc` = `datetime64[ns, UTC]` parsed from chars 0-19 with `%d/%m/%Y %H:%M:%S`; keep the raw string | tz-naive UTC; or drop the raw string | Aware UTC blocks accidental local-time arithmetic (aggregation tz `Australia/Perth` lives in config) | Naive: silent 8 h shifts in daily/monthly bins | DECISION: Jack |
| R4 craft_id | Keep float64 | `Int64`, raising if any value is non-integral | Real values are float64 (P1) [High] and include negatives (`edge_rows()` mirrors a real one) [High]; magnitudes to ~4.5e10 seen in the S0 first-run pair table, not printed by the committed P13 [Med]; integrality across all rows [Unverified] | float64 keys make joins fragile; Int64 fails if a fractional ID exists | DECISION: Jack |
| R5 extra columns | Raise on any column not in the 10 | Pass through; or drop with a warning | Schema drift should be loud (metadata already wrong once) | Raising blocks older years until each schema is mapped | DECISION: Jack |
| R6 geometry | Plain DataFrame from `longitude`/`latitude`; no reprojection | GeoDataFrame in EPSG:4326 | Attributes duplicate the point geometry (P1); EPSG:7850 conversion belongs to distance work (Fixed decision) | GeoDataFrame costs memory on ~1M rows/month | DECISION: Jack |
| R7 order + provenance | Preserve file order; add `source_file` | Sort by `craft_id`, time | Real files are unsorted (`edge_rows()` reversed order); provenance needed for month edges (section 4) | Sorting in load hides input order issues | DECISION: Jack |

## 2. Raises on

| # | Recommendation (type, message content) | Alternative | Why | Cost if wrong | |
|---|---|---|---|---|---|
| E0 type | Custom `AmsaFormatError(ValueError)` for all below | Built-in `ValueError`/`KeyError` | One `except` in callers; still a `ValueError` | Mixed exception types leak into callers | DECISION: Jack |
| E1 unparsed time | Raise; message: file, count of bad rows, first 5 raw strings | Coerce to NaT and drop | Coercion lost 49% of rows silently in S0 (P2) [High] | Silent row loss is the worst failure seen so far | DECISION: Jack |
| E2 tag contradicts hour | Raise; message: file, count, first 5 strings (fixture `conflicting_suffix_row()`, `13:00:00 AM`) | Trust the 24-hour value and warn | 0 cases in real data (P2), so any case means a new format | Raising may block a file for one bad row | DECISION: Jack |
| E3 missing column | Raise; message: file, missing names, names found | Fill missing with NaN | Downstream needs all 10 | Filling hides a format change | DECISION: Jack |
| E4 header drift between files | Raise when two files in one call differ in names or dtypes; message: both files and the difference | Union columns with NaN | Mixed schemas across years are unverified | Union quietly mixes semantics (e.g. "Minimum draught" wording, STATUS.md) | DECISION: Jack |
| E5 CRS | Raise if the `.prj` is not EPSG:4326 (P1) | Reproject | Unknown datum shift would move every point | Reprojecting an unexpected CRS hides it | DECISION: Jack |
| E6 non-numeric in a numeric field | Raise; message: file, field, examples | Coerce to NaN | Same silent-loss risk as E1 | As E1 | DECISION: Jack |

## 3. Stays out (belongs in `clean`)
load_amsa must not: turn zero `length`/`beam`/`draught` into NaN or judge them implausible (P7: 2.01% / 2.07% zero rows; `edge_rows()` has zero L/B and zero draught) [High]; set any flag (`no_draught`, `static_draught`, `light_departure`, `ais_gap`, `implausible`) or `unclassified_size`; deduplicate vessels or compute modal TYPE/L/B (P8); filter by area, polygon, TYPE, speed or size; reproject; resample or thin pings. Recommendation: load is parse + validate only. Alternative: let load drop exact duplicate rows (see X1). **DECISION: Jack**

## 4. Edge cases

| # | Recommendation | Alternative | Why | Cost if wrong | |
|---|---|---|---|---|---|
| X1 duplicate rows | Keep; report count of exact duplicates | Drop exact duplicates in load | Within-vessel ping intervals of 0.0 min exist (P11 min) [High]; whether they are full-row duplicates [Unverified]; `edge_rows()` has one | Dropping in load hides a data-quality signal; keeping inflates counts if clean forgets | DECISION: Jack |
| X2 rows outside the file's UTC month | Raise, with file, count and range | Keep and tag with `source_file` | Jul/Aug 2026 files hold only their own UTC month (P1 TS ranges) [High]; other years [Unverified] | Raising may block files with legitimate edge rows | DECISION: Jack |
| X3 calls straddling two files | Accept a list of files and concatenate; no cross-file dedup; `source_file` kept | One file per call | Calls cross month ends (fixture `month_boundary_call`; S0 found 34-37 calls with no observed crossing at data edges, V2) [High] | Per-file loading truncates calls | DECISION: Jack |
| X4 empty or zero-row file | Return an empty frame with the full schema and dtypes, plus a warning | Raise | Lets month loops run | An empty AMSA file may mean a failed extract; never observed [Unverified] | DECISION: Jack |
| X5 mixed schemas 2014-2025 | Validate each file against the 2026 schema; fail (E4/R5) until a year is inspected | Map known variants up front | Listing titles vary by year; Jul/Aug 2017 descriptions omit "North West" (amsa_catalogue.txt) [High]; schemas [Unverified] | Early mapping guesses at fields never seen | DECISION: Jack |
| X6 file naming | Locate by glob `ct_nw_*_pt.shp` under DATA_ROOT; record the path | Read straight from the nested zip | Actual prefix is `ct_nw_`, not the metadata's `cts_nw_` (STATUS.md) [High] | A wrong prefix finds nothing, or the wrong sub-area | DECISION: Jack |

## Open questions
1. Are all `craft_id` values integral across a whole month? (R4) [Unverified]
2. Are 0-minute intervals (P11) exact duplicate rows or distinct reports? (X1)
3. Is the AMSA timestamp truly UTC? (P3 heuristic only)
4. Do 2014-2025 files share the 2026 field names, dtypes, timestamp format and CRS? (X5)
5. Can a file contain rows from a neighbouring month? (X2)
6. Should load accept zips directly, or only extracted shapefiles? (X6)
7. Does load return one frame for many files, or one per file? (X3)
