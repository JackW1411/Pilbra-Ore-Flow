# load_amsa contract (decided 2026-10-13)

Scope: read AMSA CTS sub-area point files (`ct_nw_MM_YYYY_pt.shp` under `DATA_ROOT/raw`) into one frame. R1-R7 and X1 decided 2026-10-13 by Jack (Recommendation column). All remaining rows decided 2026-10-13 by Claude under Jack's explicit delegation ("decide for me"): Recommendation column adopted throughout. Evidence tags: `P#` = `scripts/s0/output/probe_s0.txt`; `F#` = `scripts/s0/output/probe_format.txt`; fixtures = `tests/synthetic.py`; config = `config/project.toml`.
**Evidence base: only July and August 2026 NW files were inspected. 2014-2025 is [Unverified].**

Known facts used: fields `craft_id, longitude, latitude, course, speed, type, length, beam, draught, timestamp`; float64 except `type`, `timestamp` (str); EPSG:4326; Jul 892,212 / Aug 992,794 rows (P1) [High]. Timestamp is `dd/mm/yyyy HH:MM:SS` 24-hour plus a redundant AM/PM tag; parsing as 12-hour (as the metadata says) silently drops ~49% of rows; 0 tag/hour conflicts in both months (P2) [High]. UTC per metadata; heuristic agrees (P3) [Unverified]. The metadata's field list is wrong in names and types (STATUS.md) [High].

## 1. Returns

| # | Recommendation | Alternative | Why | Cost if wrong | |
|---|---|---|---|---|---|
| R1 columns | Keep the 10 real lowercase names (P1) | Rename to uppercase as the probe did | Matches the files; no mapping layer to drift | Renaming later touches every module | **DECIDED 2026-10-13 (Jack): Recommendation** |
| R2 dtypes | float64 for the 8 numeric fields as read; `type` as pandas `string` with `<NA>` | Downcast; `length`/`beam` to `Int16` as the metadata claims | P1 shows float64 on disk; metadata types are wrong [High] | Downcasting hides non-integral values [Unverified whether any exist] | **DECIDED 2026-10-13 (Jack): Recommendation** |
| R3 time | New `timestamp_utc` = `datetime64[ns, UTC]` parsed from chars 0-19 with `%d/%m/%Y %H:%M:%S`; keep the raw string | tz-naive UTC; or drop the raw string | Aware UTC blocks accidental local-time arithmetic (aggregation tz `Australia/Perth` lives in config) | Naive: silent 8 h shifts in daily/monthly bins | **DECIDED 2026-10-13 (Jack): Recommendation** |
| R4 craft_id | Keep float64 | `Int64`, raising if any value is non-integral | Real values are float64 (P1); all whole numbers, no NaN, range -2,146,018,332 to 46,283,679,282, well below 2^53, so an Int64 cast is lossless for Jul/Aug 2026 (F1) [High]; other years [Unverified] | float64 keys make joins fragile; Int64 fails if a fractional ID exists | **DECIDED 2026-10-13 (Jack): Recommendation** |
| R5 extra columns | Raise on any column not in the 10 | Pass through; or drop with a warning | Schema drift should be loud (metadata already wrong once) | Raising blocks older years until each schema is mapped | **DECIDED 2026-10-13 (Jack): Recommendation** |
| R6 geometry | Plain DataFrame from `longitude`/`latitude`; no reprojection | GeoDataFrame in EPSG:4326 | Attributes equal the point geometry: 0 rows differ by > 1e-6 deg, max difference 1.1e-13 deg, no empty geometry (F2) [High]; EPSG:7850 conversion belongs to distance work (Fixed decision) | GeoDataFrame costs memory on ~1M rows/month | **DECIDED 2026-10-13 (Jack): Recommendation** |
| R7 order + provenance | Preserve file order; add `source_file` | Sort by `craft_id`, time | Real files are in neither time nor craft_id order: ~50% of consecutive pairs in order for each key (F4) [High]; provenance needed for month edges (section 4) | Sorting in load hides input order issues | **DECIDED 2026-10-13 (Jack): Recommendation** |

## 2. Raises on

| # | Recommendation (type, message content) | Alternative | Why | Cost if wrong | |
|---|---|---|---|---|---|
| E0 type | Custom `AmsaFormatError(ValueError)` for all below | Built-in `ValueError`/`KeyError` | One `except` in callers; still a `ValueError` | Mixed exception types leak into callers | **DECIDED 2026-10-13 (Claude, delegated): Recommendation** |
| E1 unparsed time | Raise; message: file, count of bad rows, first 5 raw strings | Coerce to NaT and drop | Coercion lost 49% of rows silently in S0 (P2) [High] | Silent row loss is the worst failure seen so far | **DECIDED 2026-10-13 (Claude, delegated): Recommendation** |
| E2 tag contradicts hour | Raise; message: file, count, first 5 strings (fixture `conflicting_suffix_row()`, `13:00:00 AM`) | Trust the 24-hour value and warn | 0 cases in real data (P2), so any case means a new format | Raising may block a file for one bad row | **DECIDED 2026-10-13 (Claude, delegated): Recommendation** |
| E3 missing column | Raise; message: file, missing names, names found | Fill missing with NaN | Downstream needs all 10 | Filling hides a format change | **DECIDED 2026-10-13 (Claude, delegated): Recommendation** |
| E4 header drift between files | Raise when two files in one call differ in names or dtypes; message: both files and the difference | Union columns with NaN | Mixed schemas across years are unverified | Union quietly mixes semantics (e.g. "Minimum draught" wording, STATUS.md) | **DECIDED 2026-10-13 (Claude, delegated): Recommendation** |
| E5 CRS | Raise if the `.prj` is not EPSG:4326 (P1) | Reproject | Unknown datum shift would move every point | Reprojecting an unexpected CRS hides it | **DECIDED 2026-10-13 (Claude, delegated): Recommendation** |
| E6 non-numeric in a numeric field | Raise; message: file, field, examples | Coerce to NaN | Same silent-loss risk as E1 | As E1 | **DECIDED 2026-10-13 (Claude, delegated): Recommendation** |

## 3. Stays out (belongs in `clean`)
load_amsa must not: turn zero `length`/`beam`/`draught` into NaN or judge them implausible (P7: 2.01% / 2.07% zero rows; `edge_rows()` has zero L/B and zero draught) [High]; set any flag (`no_draught`, `static_draught`, `light_departure`, `ais_gap`, `implausible`) or `unclassified_size`; deduplicate vessels or compute modal TYPE/L/B (P8); filter by area, polygon, TYPE, speed or size; reproject; resample or thin pings. Recommendation: load is parse + validate only. Alternative: let load drop exact duplicate rows (see X1). **DECIDED 2026-10-13 (Claude, delegated): Recommendation (load = parse + validate only).**

## 4. Edge cases

| # | Recommendation | Alternative | Why | Cost if wrong | |
|---|---|---|---|---|---|
| X1 duplicate rows | Keep; report count of exact duplicates | Drop exact duplicates in load | Exact duplicates: Jul 0, Aug 1; same craft_id + timestamp: Jul 1, Aug 3 (F5) [High]; `edge_rows()` has one | Dropping in load hides a data-quality signal; keeping inflates counts if clean forgets | **DECIDED 2026-10-13 (Jack): Recommendation** |
| X2 rows outside the file's UTC month | Raise, with file, count and range | Keep and tag with `source_file` | Jul/Aug 2026 files hold only their own UTC month (P1 TS ranges) [High]; other years [Unverified] | Raising may block files with legitimate edge rows | **DECIDED 2026-10-13 (Claude, delegated): Recommendation** |
| X3 calls straddling two files | Accept a list of files and concatenate; no cross-file dedup; `source_file` kept | One file per call | Calls cross month ends (fixture `month_boundary_call`; S0 found 34-37 calls with no observed crossing at data edges, V2) [High] | Per-file loading truncates calls | **DECIDED 2026-10-13 (Claude, delegated): Recommendation** |
| X4 empty or zero-row file | Return an empty frame with the full schema and dtypes, plus a warning | Raise | Lets month loops run | An empty AMSA file may mean a failed extract; never observed [Unverified] | **DECIDED 2026-10-13 (Claude, delegated): Recommendation** |
| X5 mixed schemas 2014-2025 | Validate each file against the 2026 schema; fail (E4/R5) until a year is inspected | Map known variants up front | Listing titles vary by year; Jul/Aug 2017 descriptions omit "North West" (amsa_catalogue.txt) [High]; schemas [Unverified] | Early mapping guesses at fields never seen | **DECIDED 2026-10-13 (Claude, delegated): Recommendation** |
| X6 file naming | Locate by glob `ct_nw_*_pt.shp` under DATA_ROOT; record the path | Read straight from the nested zip | Actual prefix is `ct_nw_`, not the metadata's `cts_nw_` (STATUS.md) [High] | A wrong prefix finds nothing, or the wrong sub-area | **DECIDED 2026-10-13 (Claude, delegated): Recommendation** |

## Open questions
1. ~~Are all `craft_id` values integral?~~ Yes for Jul/Aug 2026 (F1); other years unverified. (R4)
2. ~~Are 0-minute intervals exact duplicates?~~ Partly: Aug has 1 exact duplicate and 3 same-key rows; Jul 0 and 1 (F5). What the same-key, non-identical rows contain is unexamined. (X1)
8. New from F3: draught 25.5 (AIS "25.5 m or more" code) appears 129 times in Jul, 0 in Aug; length reaches 708 m (Jul) and beam 96 m (Aug), inside AIS encoding limits but beyond real ships. Per section 3 these belong to `clean`; listed so the boundary is explicit. No heading field exists.
3. Is the AMSA timestamp truly UTC? (P3 heuristic only)
4. Do 2014-2025 files share the 2026 field names, dtypes, timestamp format and CRS? (X5)
5. Can a file contain rows from a neighbouring month? (X2)
6. Should load accept zips directly, or only extracted shapefiles? (X6)
7. Does load return one frame for many files, or one per file? (X3)

## Open questions parked for `clean` (2026-10-13, Jack)
Not load_amsa work; no probe run. Recorded so they are not lost.
C1. Same craft_id + timestamp but not identical rows (Jul 1, Aug 3; F5): which columns differ, and which row clean keeps. [Unverified]
C2. Negative craft_id coverage in the CRAFT_ID stability test: negative IDs exist (Jul 30,383 rows, Aug 26,515; F1), but whether any of the 112 boundary pairs (P13) had a negative ID was not checked. [Unverified]
C3. Draught 25.5 rows (AIS "25.5 m or more" code; Jul 129, Aug 0; F3): treatment in clean (value, flag, or NaN) undecided. [Unverified]

### Decisions for `clean` (2026-10-13, Claude under Jack's delegation)
- C1: `clean` drops exact duplicate rows, then keeps the first row (file order) per `craft_id` + `timestamp_utc`; both counts are reported. Alternative: keep all and let calls tolerate zero intervals. Cost if wrong: one ping per affected key (4 rows in Jul+Aug, F5).
- C2: not blocking. CRAFT_ID stability is [Med] already; negative-ID coverage stays a diagnostic open question.
- C3: draught 25.5 is the AIS "25.5 m or more" code (ITU-R M.1371, [Med]: cited, not re-read), not a measurement. `clean` sets such pings' draught to NaN and marks them `implausible`. This is the only `implausible` rule; no physical draught bound is defined (CLAUDE.md open item stands for any wider rule).

### Amendment 2026-10-13: fractional seconds (E1)
Running load_amsa on the real files raised E1 on 3 July 2026 timestamps with milliseconds (e.g. `03/07/2026 15:15:00.555 PM`); August has none. S0's 19-character parse had truncated them silently. Decision (Claude, delegated): accept an optional `.fff` part and parse it at full precision; the count is reported in `attrs["report"]`. Every other non-matching string still raises. Fixture: `synthetic.fractional_seconds_row()`.
