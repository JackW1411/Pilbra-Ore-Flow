"""S0 feasibility probe on AMSA CTS sub-area data (NW), Jul + Aug 2026.

Run from the repo root:  python scripts/s0/probe_s0.py
Reads DATA_ROOT/raw only (config/project.toml). Writes results/s0/probe_s0.txt (same text as stdout).
Every S0 number in docs/STATUS.md that comes from AMSA data is printed here under a [Pn] tag.
"""
import re
import sys
import zipfile
import zlib
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio

from paths import DATA, ROOT

RAW = DATA / "raw"
OUT = Path(__file__).resolve().parents[2] / "results" / "s0" / "probe_s0.txt"
MONTHS = ["2026-07", "2026-08"]
PROBE_MONTH = "2026-08"

# Ad hoc box around Port Hedland harbour + anchorage. NOT a port limit; statistics only.
BOX = dict(lon=(117.9, 119.3), lat=(-20.45, -19.4))
STATIONARY_KN = 0.5   # probe-only threshold for "stationary"; not the model's SOG threshold
PAIR_RADIUS_M = 200   # boundary-pairing radius for the CRAFT_ID stability test
BIG_M = 150           # "large vessel" cut for the TYPE-filter check


class Tee:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(path, "w", encoding="utf-8", newline="\n")

    def write(self, s):
        sys.__stdout__.write(s)
        self.f.write(s)

    def flush(self):
        sys.__stdout__.flush()
        self.f.flush()


def section(tag, title):
    print(f"\n==== [{tag}] {title}")


def mm(month):
    return month[5:7]


def shp_path(month):
    m = mm(month)
    return RAW / f"sub_2026_{m}/pt/cts_sub-areas_{m}_2026_pt/ct_nw_{m}_2026_pt.shp"


def zip_path(month):
    return RAW / f"amsa_subareas_{month.replace('-', '_')}.zip"


def load(month):
    df = pyogrio.read_dataframe(shp_path(month), read_geometry=False)
    raw_cols = list(df.columns)
    df = df.rename(columns={"longitude": "LON", "latitude": "LAT"}).rename(columns=str.upper)
    # 24-hour clock with a redundant AM/PM suffix (see P2). Parse the first 19 chars; never coerce silently.
    df["TS"] = pd.to_datetime(df["TIMESTAMP"].str.slice(0, 19), format="%d/%m/%Y %H:%M:%S", errors="raise")
    return df, raw_cols


def modal_positive(x):
    x = x[x > 0]
    return x.mode().min() if len(x) else np.nan


def modal_type(x):
    vc = x.dropna().value_counts()
    if vc.empty:
        return np.nan
    top = vc[vc == vc.max()].index
    return sorted(top)[0]  # deterministic tie-break


def type_class(t):
    if not isinstance(t, str):
        return "unknown"
    if t.startswith("Cargo ship"):
        return "cargo"
    if t.startswith("Tanker"):
        return "tanker"
    if t.startswith(("unknown code", "Reserved", "Local ")):
        return "unknown"
    return "other"


def pdf_text(raw):
    """Crude text extraction from Flate streams (stdlib only)."""
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
        try:
            s = zlib.decompress(m.group(1))
        except zlib.error:
            continue
        for tok in re.finditer(rb"\[(.*?)\]\s*TJ|\((.*?)\)\s*Tj", s, re.S):
            seg = tok.group(1) or tok.group(2)
            lits = re.findall(rb"\(((?:\\.|[^\\)])*)\)", seg) if tok.group(1) else [seg]
            out.append("".join(lit.decode("latin1") for lit in lits))
    return " ".join(out)


def main():
    sys.stdout = Tee(OUT)
    print(f"S0 probe. pandas {pd.__version__}, pyogrio {pyogrio.__version__}")
    print(f"Probe box (NOT a port limit): lon {BOX['lon']}, lat {BOX['lat']}")

    data = {}
    for month in MONTHS:
        df, raw_cols = load(month)
        data[month] = df
        section("P1", f"{month}: schema and extent (DATA_ROOT/{shp_path(month).relative_to(DATA).as_posix()})")
        info = pyogrio.read_info(shp_path(month))
        print("raw fields:", raw_cols)
        print("raw dtypes:", list(info["dtypes"]))
        print("CRS:", info["crs"], "| features:", info["features"])
        print("SUBTYPE present:", "SUBTYPE" in df.columns)
        print("IMO/MMSI-like fields:", [c for c in raw_cols if re.search("imo|mmsi|call|name", c, re.I)])
        print(f"LON {df.LON.min():.5f}..{df.LON.max():.5f}  LAT {df.LAT.min():.5f}..{df.LAT.max():.5f}")
        print("TS range:", df.TS.min(), "->", df.TS.max())

    section("P2", "timestamp format: AM/PM suffix vs 24-hour value")
    for month, df in data.items():
        hr = df.TIMESTAMP.str.slice(11, 13).astype(int)
        sfx = df.TIMESTAMP.str[-2:]
        conflict = ((hr >= 12) & (sfx == "AM")) | ((hr < 12) & (sfx == "PM"))
        bad12 = pd.to_datetime(df.TIMESTAMP, format="%d/%m/%Y %I:%M:%S %p", errors="coerce").isna()
        print(f"{month}: rows {len(df)}, suffix conflicts {int(conflict.sum())}, "
              f"rows lost if parsed as 12-hour %I..%p: {int(bad12.sum())} ({bad12.mean():.2%})")

    section("P3", "timezone heuristic: hour-of-day profile of moving small craft (whole NW area)")
    print("If TIMESTAMP is UTC, local daylight (AWST = UTC+8, 06-18 local) is 22-10 UTC.")
    for month, df in data.items():
        sc = df[df.TYPE.isin(["Pleasure craft", "Sailing", "Fishing"]) & (df.SPEED > 2)]
        prof = sc.TS.dt.hour.value_counts(normalize=True).sort_index()
        utc_day = prof[(prof.index >= 22) | (prof.index < 10)].sum()
        print(f"{month}: moving small-craft rows {len(sc)}; share in 22-10 UTC window {utc_day:.2%} "
              f"(uniform would be 50%)")
        print("  hour share:", " ".join(f"{h:02d}:{v:.3f}" for h, v in prof.items()))

    section("P4", "release-lag evidence from the downloaded packages")
    for month in MONTHS:
        with zipfile.ZipFile(zip_path(month)) as z:
            for zi in z.infolist():
                print(f"{month} outer: {zi.filename}  zip-mtime {zi.date_time}")
                if zi.filename.endswith(".pdf"):
                    txt = re.sub(r"\s+", "", pdf_text(z.read(zi)))
                    md = re.search(r"MetadataDate:(\d{2}/\d{2}/\d{4})", txt)
                    print(f"  metadata 'Metadata Date': {md.group(1) if md else 'not found'}")
                    th = re.search(r"minimumtimeintervalbetweensuccessivevesselpositionreportsof(\d+)minutes", txt)
                    print(f"  metadata thinning interval (min): {th.group(1) if th else 'not found'}")
                if zi.filename.endswith(".zip"):
                    with zipfile.ZipFile(BytesIO(z.read(zi))) as inner:
                        for ii in inner.infolist():
                            if "ct_nw_" in ii.filename and ii.filename.endswith(".shp"):
                                print(f"  inner: {ii.filename}  zip-mtime {ii.date_time} (zip times carry no timezone)")

    df = data[PROBE_MONTH]
    section("P5", f"{PROBE_MONTH}: TYPE value_counts, whole NW area (rows, distinct CRAFT_ID)")
    vc = df.groupby("TYPE", dropna=False).agg(rows=("CRAFT_ID", "size"), vessels=("CRAFT_ID", "nunique"))
    print("distinct TYPE values (excl NaN):", df.TYPE.nunique())
    print(vc.sort_values("vessels", ascending=False).to_string())

    box = {m: d[d.LON.between(*BOX["lon"]) & d.LAT.between(*BOX["lat"])].sort_values(["CRAFT_ID", "TS"])
           for m, d in data.items()}
    for m, b in box.items():
        print(f"\n[P6] {m}: Hedland probe box rows {len(b)}, vessels {b.CRAFT_ID.nunique()}")

    hb = box[PROBE_MONTH]
    vessels = hb.groupby("CRAFT_ID").agg(
        TYPE_MODAL=("TYPE", modal_type),
        N_TYPE=("TYPE", lambda x: x.nunique(dropna=False)),
        L_MODAL=("LENGTH", modal_positive),
        B_MODAL=("BEAM", modal_positive),
        ROWS=("TYPE", "size"),
    )
    vessels["TYPE_CLASS"] = vessels.TYPE_MODAL.map(type_class)
    vessels["UNCLASSIFIED_SIZE"] = vessels.L_MODAL.isna() | vessels.B_MODAL.isna()

    section("P7", f"{PROBE_MONTH}: LENGTH/BEAM per CRAFT_ID (box)")
    for col in ["LENGTH", "BEAM"]:
        s = hb[col]
        g = hb.groupby("CRAFT_ID")[col]
        nuniq = g.nunique()
        allbad = g.apply(lambda x: (x.isna() | (x == 0)).all())
        changes = g.apply(lambda x: int((x.ne(x.shift()) & x.shift().notna()).sum())).sum()
        print(f"{col}: rows null {s.isna().mean():.2%}, rows zero {(s == 0).mean():.2%}; vessels {len(nuniq)}, "
              f"all null/zero {allbad.mean():.2%}, >1 distinct value {(nuniq > 1).mean():.2%}; "
              f"row-to-row changes {changes} of {len(hb) - len(nuniq)} transitions")

    section("P8", f"{PROBE_MONTH}: per-CRAFT_ID modal TYPE classification (box). Row TYPE kept unchanged.")
    print("vessels by TYPE_CLASS:")
    print(vessels.TYPE_CLASS.value_counts().to_string())
    big = vessels[vessels.L_MODAL >= BIG_M]
    print(f"\nvessels with modal LENGTH >= {BIG_M} m: {len(big)}; by TYPE_CLASS:")
    print(big.TYPE_CLASS.value_counts().to_string())
    print(f"\nby TYPE_MODAL (modal LENGTH >= {BIG_M} m):")
    print(big.TYPE_MODAL.fillna("<NaN>").value_counts().to_string())
    print(f"\nvessels with >1 TYPE value (incl NaN) in month: {(vessels.N_TYPE > 1).sum()} of {len(vessels)}; "
          f"of which modal LENGTH >= {BIG_M} m: {(big.N_TYPE > 1).sum()}")
    mixed = hb[hb.CRAFT_ID.isin(vessels.index[vessels.N_TYPE > 1])].copy()
    mixed["ROW_CLASS"] = mixed.TYPE.map(type_class)
    flips = mixed.groupby("CRAFT_ID").ROW_CLASS.nunique()
    print(f"of those, vessels whose rows span >1 TYPE_CLASS: {(flips > 1).sum()}")

    section("P9", f"{PROBE_MONTH}: unclassified_size reason code (modal L or B missing/zero), box")
    print("all vessels:", int(vessels.UNCLASSIFIED_SIZE.sum()), "of", len(vessels))
    print("by TYPE_CLASS:")
    print(vessels.groupby("TYPE_CLASS").UNCLASSIFIED_SIZE.agg(["sum", "size"]).to_string())
    print("('implausible' dimensions are not defined yet; only missing/zero counted)")

    section("P10", f"{PROBE_MONTH}: modal L/B, TYPE_CLASS == cargo, sized vessels (box)")
    cs = vessels[(vessels.TYPE_CLASS == "cargo") & ~vessels.UNCLASSIFIED_SIZE]
    print("n =", len(cs))
    print(cs[["L_MODAL", "B_MODAL"]].describe(percentiles=[.05, .1, .25, .5, .75, .9, .95]).to_string())
    print("LENGTH, 20 m bins (non-empty):")
    lc = pd.cut(cs.L_MODAL, range(0, 420, 20)).value_counts().sort_index()
    print(lc[lc > 0].to_string())
    print("BEAM, 4 m bins (non-empty):")
    bc = pd.cut(cs.B_MODAL, range(0, 80, 4)).value_counts().sort_index()
    print(bc[bc > 0].to_string())

    section("P11", f"{PROBE_MONTH}: ping intervals within CRAFT_ID, box (minutes)")
    dt = hb.groupby("CRAFT_ID").TS.diff().dt.total_seconds() / 60
    pct = [.05, .25, .5, .75, .95]
    print("all:", dt.describe(percentiles=pct).round(1).to_dict())
    print(f"SOG < {STATIONARY_KN} kn:", dt[hb.SPEED < STATIONARY_KN].describe(percentiles=pct).round(1).to_dict())
    print(f"share < 15 min {(dt < 15).mean():.2%} | > 60 min {(dt > 60).mean():.2%} | > 6 h {(dt > 360).mean():.2%}"
          " (gaps include time spent outside the box between visits)")

    section("P12", f"{PROBE_MONTH}: SPEED distribution, box rows")
    sp = pd.cut(hb.SPEED, [-0.01, 0.1, 0.3, 0.5, 1, 2, 4, 8, 12, 30]).value_counts(normalize=True).sort_index()
    print(sp.map("{:.2%}".format).to_string())

    section("P13", "CRAFT_ID stability Jul -> Aug (position-based pairing at the month boundary)")
    j, a = box["2026-07"], box["2026-08"]
    print(f"box vessels Jul {j.CRAFT_ID.nunique()}, Aug {a.CRAFT_ID.nunique()}, "
          f"IDs in both {len(set(j.CRAFT_ID) & set(a.CRAFT_ID))}")
    jl = j[j.TS >= "2026-07-31 22:00"].groupby("CRAFT_ID").last()
    af = a[a.TS < "2026-08-01 02:00"].groupby("CRAFT_ID").first()
    jl, af = jl[jl.SPEED < STATIONARY_KN], af[af.SPEED < STATIONARY_KN]
    print(f"stationary (SOG < {STATIONARY_KN}) at boundary: Jul-side {len(jl)}, Aug-side {len(af)}")
    # Equirectangular distance is adequate for a sub-km nearest-neighbour match (probe only, not model distance).
    lat0 = np.deg2rad(-20.3)
    rows = []
    for cid, r in jl.iterrows():
        d = np.hypot((af.LON - r.LON) * np.cos(lat0) * 111_320, (af.LAT - r.LAT) * 110_574)
        k = d.idxmin()
        rows.append((cid, k, d.min(), cid == k, r.LENGTH, af.loc[k, "LENGTH"], r.BEAM, af.loc[k, "BEAM"]))
    res = pd.DataFrame(rows, columns=["jul_id", "aug_nn_id", "dist_m", "same_id", "L_jul", "L_aug", "B_jul", "B_aug"])
    close = res[res.dist_m < PAIR_RADIUS_M]
    print(f"pairs within {PAIR_RADIUS_M} m: {len(close)}; same CRAFT_ID: {int(close.same_id.sum())}")
    mis = close[~close.same_id]
    print("mismatches (L_jul, L_aug):", list(zip(mis.L_jul.astype(int), mis.L_aug.astype(int))))
    lmax = mis.L_jul.max() if len(mis) else np.nan
    print(f"max L_jul among mismatches: {lmax}; matched pairs with L_jul > that: "
          f"{int((close.same_id & (close.L_jul > lmax)).sum())}; mismatches with L_jul > that: 0 by construction")
    print(f"smallest L_jul among matched pairs above that: {close[close.same_id & (close.L_jul > lmax)].L_jul.min()}")
    print("matched pairs with identical L/B:", int((close.same_id & (close.L_jul == close.L_aug)
                                                    & (close.B_jul == close.B_aug)).sum()))
    # Class and size from the Aug-side vessel (P8 table); both sides must agree for a matched pair.
    cls = close.aug_nn_id.map(vessels.TYPE_CLASS)
    lm = close.aug_nn_id.map(vessels.L_MODAL)
    big_cargo = (cls == "cargo") & (lm >= BIG_M)
    print(f"pairs whose Aug-side vessel is modal TYPE_CLASS cargo and modal L >= {BIG_M} m: {int(big_cargo.sum())} "
          f"of {len(close)}; of these same CRAFT_ID: {int((big_cargo & close.same_id).sum())}")


if __name__ == "__main__":
    main()
