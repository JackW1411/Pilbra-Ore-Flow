"""Format probe for load_amsa decisions (docs/load_amsa_contract.md). Report only.

Run from the repo root:  python scripts/s0/probe_format.py
Reads the Jul and Aug 2026 NW shapefiles from DATA_ROOT/raw (with geometry). Writes scripts/s0/output/probe_format.txt.
Values are counted as read from the file: nothing is cleaned, dropped or corrected.

Range limits for [F3] come from the AIS position/static message field definitions (ITU-R M.1371) as commonly
documented; [Med]: cited from the spec, not re-read for this probe.
"""
import sys

import numpy as np
import pandas as pd
import pyogrio
import shapely

from probe_s0 import MONTHS, Tee, shp_path
from pathlib import Path

OUT = Path(__file__).resolve().parent / "output" / "probe_format.txt"
FIELDS = ["craft_id", "longitude", "latitude", "course", "speed", "type", "length", "beam", "draught", "timestamp"]
# (field, sentinel values to count, valid min, valid max). Valid ranges exclude the sentinels.
CHECKS = [
    ("longitude", [181.0], -180.0, 180.0),
    ("latitude", [91.0], -90.0, 90.0),
    ("speed", [102.3], 0.0, 102.2),          # SOG 102.3 = not available
    ("course", [360.0], 0.0, 359.9),         # COG 360.0 = not available
    ("length", [], 0.0, 1022.0),             # bow + stern dimension fields, each max 511 m
    ("beam", [], 0.0, 126.0),                # port + starboard dimension fields, each max 63 m
    ("draught", [25.5], 0.0, 25.4),          # 25.5 = 25.5 m or greater
]


def section(tag, title):
    print(f"\n==== [{tag}] {title}")


def main():
    sys.stdout = Tee(OUT)
    print("format probe; files as read, nothing corrected")
    frames = {}
    for m in MONTHS:
        g = pyogrio.read_dataframe(shp_path(m))
        frames[m] = g
        print(f"{m}: {len(g)} rows, columns {[c for c in g.columns if c != 'geometry']}, CRS {g.crs.to_string()}")

    section("F1", "craft_id: whole numbers?")
    for m, g in frames.items():
        c = g.craft_id
        nonwhole = c.notna() & (np.floor(c) != c)
        print(f"{m}: min {c.min():.1f}, max {c.max():.1f}, NaN {int(c.isna().sum())}, negative {int((c < 0).sum())}, "
              f"non-whole {int(nonwhole.sum())}, distinct {c.nunique()}, |max| below 2^53: {bool(c.abs().max() < 2 ** 53)}")

    section("F2", "point geometry vs longitude/latitude columns (degrees)")
    for m, g in frames.items():
        geom = g.geometry.values
        empty = shapely.is_empty(geom) | pd.isna(geom)
        x, y = shapely.get_x(geom), shapely.get_y(geom)
        dx, dy = np.abs(x - g.longitude.to_numpy()), np.abs(y - g.latitude.to_numpy())
        diff = (dx > 1e-6) | (dy > 1e-6)
        print(f"{m}: null/empty geometry {int(empty.sum())}; rows differing by > 1e-6 deg {int(np.nansum(diff))}; "
              f"largest |dlon| {np.nanmax(dx):.3e}, largest |dlat| {np.nanmax(dy):.3e}")

    section("F3", "AIS sentinels and out-of-range values per numeric field")
    print("heading field present: " + str(any("head" in c.lower() for c in frames[MONTHS[0]].columns)))
    for m, g in frames.items():
        print(f"{m}:")
        for f, sentinels, lo, hi in CHECKS:
            v = g[f]
            sent = {s: int((v == s).sum()) for s in sentinels}
            below, above = int((v < lo).sum()), int(((v > hi) & ~v.isin(sentinels)).sum())
            print(f"  {f:9s} NaN {int(v.isna().sum()):6d} | sentinels {sent} | < {lo}: {below} | > {hi} (excl. sentinels): "
                  f"{above} | observed {v.min()}..{v.max()}")
        print(f"  craft_id  NaN {int(g.craft_id.isna().sum())} (no range defined)")

    section("F4", "row order within each file")
    for m, g in frames.items():
        ts = pd.to_datetime(g.timestamp.str.slice(0, 19), format="%d/%m/%Y %H:%M:%S", errors="raise")
        t_ok = (ts.diff().dropna() >= pd.Timedelta(0)).mean()
        c_ok = (g.craft_id.diff().dropna() >= 0).mean()
        key = pd.DataFrame({"c": g.craft_id.to_numpy(), "t": ts.to_numpy()})
        prev = key.shift()
        lex = ((key.c > prev.c) | ((key.c == prev.c) & (key.t >= prev.t)))[1:].mean()
        print(f"{m}: consecutive pairs in time order {t_ok:.2%}; craft_id non-decreasing {c_ok:.2%}; "
              f"(craft_id, time) order {lex:.2%}")

    section("F5", "exact duplicate rows (all 10 attribute columns identical, raw values)")
    for m, g in frames.items():
        d = g[FIELDS]
        exact = int(d.duplicated(keep="first").sum())
        same_key = int(d.duplicated(subset=["craft_id", "timestamp"], keep="first").sum())
        print(f"{m}: exact duplicates (rows beyond the first copy) {exact}; "
              f"context: rows sharing craft_id + timestamp with an earlier row {same_key}")


if __name__ == "__main__":
    main()
