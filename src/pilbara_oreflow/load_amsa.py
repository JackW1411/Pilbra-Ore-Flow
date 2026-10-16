"""Read AMSA CTS sub-area point shapefiles. Parse and validate only (docs/load_amsa_contract.md).

load_amsa never cleans: no zero->NaN, no flags, no dedup, no filtering, no reprojection, no sorting.
"""
from __future__ import annotations

import logging
import re
import warnings
from pathlib import Path

import pandas as pd
import pyogrio

log = logging.getLogger(__name__)

FIELDS = ["craft_id", "longitude", "latitude", "course", "speed", "type", "length", "beam", "draught", "timestamp"]
NUMERIC = ["craft_id", "longitude", "latitude", "course", "speed", "length", "beam", "draught"]
# Optional fractional seconds: 3 rows in Jul 2026 carry them (e.g. "03/07/2026 15:15:00.555 PM"); found by load_amsa
# on real data 2026-10-13. Parsed at full precision, not truncated (contract E1 amendment).
TS_RE = re.compile(r"^\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}(\.\d{1,6})? (AM|PM)$")
# Older format (found 2026-10-16 in Mar-May 2026 "cts_nw_" files): UPPERCASE names, LON/LAT, int32 LENGTH/BEAM,
# an all-empty SUBTYPE, and a true 12-hour clock with no leading zeros ("3/03/2026 8:34:06 PM", hours 1-12).
TS_RE_12H = re.compile(r"^\d{1,2}/\d{2}/\d{4} \d{1,2}:\d{2}:\d{2}(\.\d{1,6})? (AM|PM)$")
LEGACY = {"CRAFT_ID": "craft_id", "LON": "longitude", "LAT": "latitude", "COURSE": "course", "SPEED": "speed",
          "TYPE": "type", "LENGTH": "length", "BEAM": "beam", "DRAUGHT": "draught", "TIMESTAMP": "timestamp"}
LEGACY_EMPTY = ["SUBTYPE"]          # dropped only if every value is empty; otherwise E0
# Legacy rows at exactly midnight carry the date only ("27/04/2026"): Mar-May 2026 have 6 such rows and 0 literal
# "12:00:00 AM", while current files have 1-7 literal "00:00:00" rows per month. Parsed as 00:00:00, raw kept, counted.
DATE_ONLY_RE = re.compile(r"^\d{1,2}/\d{2}/\d{4}$")
NAME_RE = re.compile(r"^cts?_nw_(\d{2})_(\d{4})_pt\.shp$", re.I)
EXPECTED_CRS = "EPSG:4326"


class AmsaFormatError(ValueError):
    """Any departure from the AMSA format observed in S0 (contract E0)."""


def find_files(raw_root: Path) -> list[Path]:
    """All NW point shapefiles under raw_root, sorted by (year, month) from the name (contract X6)."""
    files = [p for p in Path(raw_root).rglob("ct*_nw_*_pt.shp") if NAME_RE.match(p.name)]
    return sorted(files, key=lambda p: (int(NAME_RE.match(p.name).group(2)), int(NAME_RE.match(p.name).group(1))))


def _examples(s: pd.Series, n: int = 5) -> list:
    return s.head(n).tolist()


def _file_month(path: Path) -> tuple[int, int]:
    m = NAME_RE.match(path.name)
    if not m:
        raise AmsaFormatError(f"{path.name}: file name does not match ct[s]_nw_MM_YYYY_pt.shp; cannot check its month")
    return int(m.group(2)), int(m.group(1))


def _empty_frame() -> pd.DataFrame:
    df = pd.DataFrame({c: pd.Series(dtype="float64") for c in NUMERIC})
    df["type"] = pd.Series(dtype="string")
    df["timestamp"] = pd.Series(dtype="string")
    df["timestamp_utc"] = pd.Series(dtype="datetime64[ns, UTC]")
    df["source_file"] = pd.Series(dtype="string")
    return df[FIELDS + ["timestamp_utc", "source_file"]]


def read_file(path: Path) -> tuple[pd.DataFrame, list[str]]:
    """Read and validate one file. Returns (frame, raw dtype list for drift checks; first item is the schema id)."""
    path = Path(path)
    info = pyogrio.read_info(path)
    crs = info["crs"]
    if crs != EXPECTED_CRS:                                                     # E5
        raise AmsaFormatError(f"{path.name}: CRS {crs!r}, expected {EXPECTED_CRS}")
    cols = list(info["fields"])
    legacy = set(cols) == set(LEGACY) | set(LEGACY_EMPTY)
    names = {c: LEGACY.get(c, c) for c in cols} if legacy else {c: c for c in cols}
    if legacy:
        cols = [names[c] for c in cols if c not in LEGACY_EMPTY]
    missing = [c for c in FIELDS if c not in cols]
    if missing:                                                                 # E3
        raise AmsaFormatError(f"{path.name}: missing columns {missing}; found {cols}")
    extra = [c for c in cols if c not in FIELDS]
    if extra:                                                                   # R5
        raise AmsaFormatError(f"{path.name}: unexpected columns {extra}; expected exactly {FIELDS}")
    src = {names[c]: c for c in info["fields"]}
    dtypes = ["legacy" if legacy else "current"] + [str(info["dtypes"][list(info["fields"]).index(src[c])]) for c in FIELDS]
    year, month = _file_month(path)
    if path.name.lower().startswith("cts_") != legacy:
        raise AmsaFormatError(f"{path.name}: file name prefix does not match its schema "
                              f"({'legacy cts_' if legacy else 'current ct_'} expected)")

    raw = pyogrio.read_dataframe(path, read_geometry=False)
    if legacy:
        for c in LEGACY_EMPTY:
            filled = raw[c].notna() & (raw[c].astype("string").str.strip() != "")
            if filled.any():
                raise AmsaFormatError(f"{path.name}: {c} has {int(filled.sum())} non-empty values; meaning unknown")
        raw = raw.drop(columns=LEGACY_EMPTY).rename(columns=LEGACY)
    if len(raw) == 0:                                                           # X4
        warnings.warn(f"{path.name}: file has zero rows", stacklevel=2)
        return _empty_frame(), dtypes

    df = pd.DataFrame(index=raw.index)
    for c in NUMERIC:                                                           # E6, R2
        s = raw[c]
        if not pd.api.types.is_numeric_dtype(s):
            num = pd.to_numeric(s, errors="coerce")
            bad = s[num.isna() & s.notna()]
            if len(bad):
                raise AmsaFormatError(f"{path.name}: non-numeric values in {c!r}: {_examples(bad)}")
            s = num
        df[c] = s.astype("float64")
    df["type"] = raw["type"].astype("string")
    ts = raw["timestamp"].astype("string")
    df["timestamp"] = ts

    date_only = ts.fillna("").str.match(DATE_ONLY_RE) if legacy else pd.Series(False, index=ts.index)
    ts_parse = ts.where(~date_only, ts + " 12:00:00 AM")
    bad = ts[ts.isna() | ~ts_parse.fillna("").str.match(TS_RE_12H if legacy else TS_RE)]   # E1
    body = ts_parse if legacy else ts.str.slice(0, -3)                          # current: drop redundant " AM"/" PM"
    frac = body.str.contains(".", regex=False).fillna(False)
    fmt = "%d/%m/%Y %I:%M:%S{} %p" if legacy else "%d/%m/%Y %H:%M:%S{}"
    parsed = pd.Series(pd.NaT, index=ts.index, dtype="datetime64[ns]")
    parsed[~frac] = pd.to_datetime(body[~frac], format=fmt.format(""), errors="coerce")
    parsed[frac] = pd.to_datetime(body[frac], format=fmt.format(".%f"), errors="coerce")
    bad = pd.concat([bad, ts[parsed.isna() & ts.notna()]]).drop_duplicates()
    if len(bad):
        raise AmsaFormatError(f"{path.name}: {len(bad)} unparsed timestamps, e.g. {_examples(bad)}")
    hour = parsed.dt.hour
    conflict = ts[(hour >= 12) != (ts_parse.str[-2:] == "PM")]                  # E2 (always 0 for legacy)
    if len(conflict):
        raise AmsaFormatError(f"{path.name}: {len(conflict)} timestamps whose AM/PM tag contradicts the "
                              f"24-hour value, e.g. {_examples(conflict)}")
    df["timestamp_utc"] = parsed.dt.tz_localize("UTC")                          # R3

    outside = df[(parsed.dt.year != year) | (parsed.dt.month != month)]         # X2
    if len(outside):
        raise AmsaFormatError(f"{path.name}: {len(outside)} rows outside {year}-{month:02d} UTC, "
                              f"range {outside.timestamp_utc.min()} to {outside.timestamp_utc.max()}")
    df["source_file"] = pd.Series(path.name, index=df.index, dtype="string")  # R7
    df.attrs["date_only_midnight"] = int(date_only.sum())
    return df[FIELDS + ["timestamp_utc", "source_file"]], dtypes


def load_amsa(paths: Path | str | list) -> pd.DataFrame:
    """Load one or more files in the given order and concatenate (contract X3). File row order is kept (R7).

    The frame's attrs carry a small report: rows per file and exact duplicate rows (X1: kept, counted).
    """
    paths = [Path(paths)] if isinstance(paths, (str, Path)) else [Path(p) for p in paths]
    if not paths:
        raise AmsaFormatError("no files given")
    frames, schemas = [], {}
    for p in paths:
        df, dtypes = read_file(p)
        schemas[p.name] = dtypes
        frames.append(df)
    for name, dt in schemas.items():                                            # E4, within one schema version
        ref = next(d for d in schemas.values() if d[0] == dt[0])
        if dt != ref:
            diff = {f: (a, b) for f, a, b in zip(FIELDS, ref[1:], dt[1:]) if a != b}
            ref_name = next(n for n, d in schemas.items() if d is ref)
            raise AmsaFormatError(f"header drift between {ref_name} and {name}: {diff}")
    out = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0].reset_index(drop=True)
    dup = int(out.duplicated(subset=FIELDS).sum())
    frac = int(out.timestamp.str.contains(".", regex=False).sum())
    out.attrs["report"] = {"rows_per_file": {p.name: len(f) for p, f in zip(paths, frames)},
                           "schema_per_file": {n: d[0] for n, d in schemas.items()},
                           "date_only_midnight_rows": {p.name: f.attrs.get("date_only_midnight", 0)
                                                       for p, f in zip(paths, frames)},
                           "exact_duplicate_rows": dup, "fractional_second_timestamps": frac}
    log.info("load_amsa: %s", out.attrs["report"])
    return out
