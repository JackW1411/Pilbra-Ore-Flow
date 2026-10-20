"""PROVISIONAL GATE PROXY V2, ALL DEPARTURES, NOT THE S0 GATE.

Draught-update test. A call = inbound crossing into, and outbound crossing out of, the working port limit
(SLIP LGATE-243 Port Hedland polygon), with inside runs separated by < merge_gap_hours merged into one call.
For calls by vessels with modal TYPE_CLASS cargo and modal LENGTH >= min_modal_length_m, report the fraction
whose outbound draught (last inside ping) differs from the inbound draught (first inside ping) by more than
the field's resolution. The denominator includes ballast departures; it is not the S0 gate.

Also reports: draught resolution (measured), round/default-value shares, plausibility-bound counts, and a
transit breakdown. The polygon sensitivity test is scripts/s0/polygon_sensitivity.py (imports build_calls).

Run from the repo root:  python scripts/s0/gate_proxy.py   (after scripts/s0/fetch_port_limit.py)
Writes aggregates to results/s0/gate_proxy.txt (committed); per-call rows with CRAFT_IDs to
DATA_ROOT/interim/s0_gate_proxy_calls.csv (gitignored). Parameters: config/project.toml [s0_gate_proxy].
"""
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from paths import DATA, load_config  # noqa: F401  (load_config re-exported for other scripts)
from probe_s0 import MONTHS, ROOT, Tee, load, modal_positive, modal_type, type_class

OUT = Path(__file__).resolve().parents[2] / "results" / "s0" / "gate_proxy.txt"
CSV = DATA / "interim" / "s0_gate_proxy_calls.csv"
LABEL = "provisional gate proxy v2, all departures, not the S0 gate"
EPS = 1e-6


def pct(n, d):
    return f"{n}/{d} ({n / d:.1%})" if d else f"{n}/0 (n/a)"


def working_limit(raw_geom, cfg):
    """Provisional working limit: the SLIP polygon buffered by port_limit.buffer_m (EPSG:7850), capped at 500 m."""
    b = cfg["port_limit"]["buffer_m"]
    if not 0 <= b <= cfg["port_limit"]["max_buffer_m"]:
        raise ValueError(f"port_limit.buffer_m={b} outside [0, {cfg['port_limit']['max_buffer_m']}]")
    return raw_geom.buffer(b) if b else raw_geom


def load_inputs(cfg):
    """AIS rows (both months) with projected x/y, and the UNBUFFERED SLIP polygon, all in EPSG:7850."""
    pl, crs = cfg["port_limit"], cfg["crs"]
    limit = gpd.read_file(DATA / pl["path"]).set_crs(pl["crs"], allow_override=True).to_crs(crs["distance"])
    df = pd.concat([load(m)[0] for m in MONTHS], ignore_index=True)
    pts = gpd.GeoSeries(gpd.points_from_xy(df.LON, df.LAT), crs=crs["ais_input"]).to_crs(crs["distance"])
    df["X"], df["Y"] = pts.x.to_numpy(), pts.y.to_numpy()
    return df, limit.geometry.union_all()


def build_calls(df, geom, p):
    """One row per call. Pure function of the AIS rows, the polygon and the parameters."""
    shapely.prepare(geom)
    inside = shapely.contains_xy(geom, df.X.to_numpy(), df.Y.to_numpy())
    ever = np.unique(df.CRAFT_ID.to_numpy()[inside])
    keep = df.CRAFT_ID.isin(ever).to_numpy()
    v = df[keep].assign(INSIDE=inside[keep]).sort_values(["CRAFT_ID", "TS"]).reset_index(drop=True)

    first_of_vessel = v.CRAFT_ID.ne(v.CRAFT_ID.shift())
    v["RUN"] = (first_of_vessel | v.INSIDE.ne(v.INSIDE.shift())).cumsum()
    runs = v[v.INSIDE].groupby("RUN").agg(
        CRAFT_ID=("CRAFT_ID", "first"), START=("TS", "first"), END=("TS", "last"),
        I0=("TS", lambda s: s.index[0]), I1=("TS", lambda s: s.index[-1])).sort_values(["CRAFT_ID", "START"])
    # Merge runs of the same vessel separated by < merge_gap_hours outside.
    gap_h = (runs.START - runs.groupby("CRAFT_ID").END.shift()).dt.total_seconds() / 3600
    runs["CALL"] = (runs.CRAFT_ID.ne(runs.CRAFT_ID.shift()) | ~(gap_h < p["merge_gap_hours"])).cumsum()
    calls = runs.groupby("CALL").agg(CRAFT_ID=("CRAFT_ID", "first"), I0=("I0", "first"), I1=("I1", "last"),
                                     N_RUNS=("I0", "size"))

    last_idx = v.groupby("CRAFT_ID").apply(lambda g: g.index[-1], include_groups=False)
    first_idx = v.groupby("CRAFT_ID").apply(lambda g: g.index[0], include_groups=False)
    rec = []
    for c in calls.itertuples():
        seg = v.loc[c.I0:c.I1]
        ins = seg[seg.INSIDE]
        has_in = c.I0 != first_idx[c.CRAFT_ID]          # a ping (outside) exists before the call
        has_out = c.I1 != last_idx[c.CRAFT_ID]          # a ping (outside) exists after the call
        rec.append(dict(
            CRAFT_ID=c.CRAFT_ID, N_RUNS=c.N_RUNS, N_INSIDE=len(ins),
            T_IN=ins.TS.iloc[0], T_OUT=ins.TS.iloc[-1],
            INBOUND_OBSERVED=has_in, OUTBOUND_OBSERVED=has_out,
            GAP_IN_MIN=(v.TS[c.I0] - v.TS[c.I0 - 1]).total_seconds() / 60 if has_in else np.nan,
            GAP_OUT_MIN=(v.TS[c.I1 + 1] - v.TS[c.I1]).total_seconds() / 60 if has_out else np.nan,
            ANY_STATIONARY=bool((ins.SPEED < p["stationary_kn"]).any()),
            MIN_LAT=ins.LAT.min(), MIN_SOG=ins.SPEED.min(),
            DRAUGHT_IN=ins.DRAUGHT.iloc[0], DRAUGHT_OUT=ins.DRAUGHT.iloc[-1],
            DRAUGHT_MAX=ins.DRAUGHT.max(), FIRST_OUT=v.TS[c.I1 + 1] if has_out else pd.NaT,
            I0=c.I0, I1=c.I1))
    x = pd.DataFrame(rec)

    vin = v[v.INSIDE]
    vessels = vin.groupby("CRAFT_ID").agg(TYPE_MODAL=("TYPE", modal_type), L_MODAL=("LENGTH", modal_positive),
                                          B_MODAL=("BEAM", modal_positive))
    vessels["TYPE_CLASS"] = vessels.TYPE_MODAL.map(type_class)
    vessels["UNCLASSIFIED_SIZE"] = vessels.L_MODAL.isna() | vessels.B_MODAL.isna()
    x = x.join(vessels, on="CRAFT_ID")
    x["ELIGIBLE"] = (x.TYPE_CLASS == p["type_class"]) & (x.L_MODAL >= p["min_modal_length_m"])

    reason = pd.Series(pd.NA, index=x.index, dtype="object")
    reason[~x.INBOUND_OBSERVED] = "no inbound crossing observed (inside at vessel's first ping)"
    reason[reason.isna() & ~x.OUTBOUND_OBSERVED] = "no outbound crossing observed (inside at vessel's last ping)"
    reason[reason.isna() & ~x.ANY_STATIONARY] = f"transit (no inside ping < {p['stationary_kn']} kn)"
    x["EXCLUDED"] = reason
    x["AIS_GAP"] = (x.GAP_IN_MIN > p["crossing_gap_min"]) | (x.GAP_OUT_MIN > p["crossing_gap_min"])
    return x, vin, v


def classify_update(c, res):
    """Draught-update outcome for kept calls. Zero draught is no_draught (not testable), never a measured 0."""
    out = pd.Series("unchanged", index=c.index, dtype="object")
    out[(c.DRAUGHT_IN == 0) | c.DRAUGHT_IN.isna()] = "no_draught at inbound"
    out[(out == "unchanged") & ((c.DRAUGHT_OUT == 0) | c.DRAUGHT_OUT.isna())] = "no_draught at outbound"
    d = c.DRAUGHT_OUT - c.DRAUGHT_IN
    t = out == "unchanged"
    out[t & (d > res + EPS)] = "increased"
    out[t & (d < -res - EPS)] = "decreased"
    return out


def main():
    cfg = load_config()
    p, tz = cfg["s0_gate_proxy"], cfg["aggregation"]["timezone"]
    sys.stdout = Tee(OUT)
    print(f"==== {LABEL.upper()}")
    print(f"port limit: {cfg['port_limit']['source']}; equivalence to handbook §4.3 [Unverified]")
    print(f"params: {p}; aggregation timezone {tz}; geometric tests in {cfg['crs']['distance']}")

    df, raw_geom = load_inputs(cfg)
    geom = working_limit(raw_geom, cfg)
    print(f"working limit: SLIP polygon + {cfg['port_limit']['buffer_m']} m buffer (EPSG:7850), "
          f"area {geom.area / 1e6:.1f} km2 (unbuffered {raw_geom.area / 1e6:.1f})")
    print(f"AIS rows {len(df)} ({MONTHS[0]}..{MONTHS[-1]}), TS {df.TS.min()} -> {df.TS.max()} (taken as UTC)")
    x, vin, v = build_calls(df, geom, p)

    section = lambda t, s: print(f"\n[{t}] {s}")
    section("V1", f"calls (all vessels): {len(x)}; vessels: {x.CRAFT_ID.nunique()}; "
                  f"calls merged from >1 inside run: {int((x.N_RUNS > 1).sum())}")
    ne = x[~x.ELIGIBLE]
    print(f"  non-eligible calls (context, not in proxy): {len(ne)}: TYPE_CLASS != {p['type_class']} "
          f"{int((ne.TYPE_CLASS != p['type_class']).sum())}; cargo unclassified_size "
          f"{int(((ne.TYPE_CLASS == p['type_class']) & ne.UNCLASSIFIED_SIZE).sum())}; cargo, sized, L < "
          f"{p['min_modal_length_m']} m {int(((ne.TYPE_CLASS == p['type_class']) & ~ne.UNCLASSIFIED_SIZE).sum())}")

    e = x[x.ELIGIBLE].copy()
    section("V2", f"eligible calls: {len(e)} (vessels {e.CRAFT_ID.nunique()}). Exclusions, first applicable reason:")
    print(e.EXCLUDED.fillna("-- kept").value_counts().to_string())
    k = e[e.EXCLUDED.isna()].copy()
    print(f"  kept calls: {len(k)}; flagged ais_gap at either crossing (> {p['crossing_gap_min']} min, kept): "
          f"{pct(int(k.AIS_GAP.sum()), len(k))}")

    # Draught field properties, eligible vessels' inside rows.
    rows = vin[vin.CRAFT_ID.isin(e.CRAFT_ID)].DRAUGHT
    pos = rows[rows > 0]
    tenths = np.abs(pos * 10 - np.round(pos * 10)) < 1e-4
    uniq = np.sort(pos.unique())
    section("V3", f"draught field, eligible vessels' inside rows (n={len(rows)})")
    print(f"  zero {pct(int((rows == 0).sum()), len(rows))}; NaN {int(rows.isna().sum())}; "
          f">= AIS cap {p['ais_cap_m']} m: {int((rows >= p['ais_cap_m'] - EPS).sum())}")
    print(f"  positive values on a 0.1 m grid: {pct(int(tenths.sum()), len(pos))}; "
          f"smallest step between distinct values: {np.diff(uniq).min():.3f} m")
    res = 0.1 if tenths.all() else float(np.diff(uniq).min())
    print(f"  resolution used: {res} m ({'all positive values on 0.1 m grid' if tenths.all() else 'min observed step'})")
    whole = np.abs(pos - np.round(pos)) < 1e-4
    half = np.abs(pos * 2 - np.round(pos * 2)) < 1e-4
    print(f"  whole metres {pct(int(whole.sum()), len(pos))}; on 0.5 m {pct(int(half.sum()), len(pos))} "
          f"(uniform on 0.1 m grid would give 10% / 20%)")
    print("  top 10 values (share of positive rows): " + ", ".join(
        f"{v:.1f}:{s:.2%}" for v, s in pos.round(1).value_counts(normalize=True).head(10).items()))

    k["UPDATE"] = classify_update(k, res)
    section("V4", LABEL)
    print(k.UPDATE.value_counts().to_string())
    testable = k[~k.UPDATE.str.startswith("no_draught")]
    changed = testable.UPDATE.isin(["increased", "decreased"])
    print(f"  ** draught changed by > {res} m between inbound and outbound: {pct(int(changed.sum()), len(testable))} "
          f"of testable calls; {pct(int(changed.sum()), len(k))} of all kept calls")
    ng = testable[~testable.AIS_GAP]
    print(f"  excl. ais_gap calls: {pct(int(ng.UPDATE.isin(['increased', 'decreased']).sum()), len(ng))}")
    dd = (testable.DRAUGHT_OUT - testable.DRAUGHT_IN)
    print(f"  delta (out - in) m: {dd.describe(percentiles=[.05, .25, .5, .75, .95]).round(2).to_dict()}")
    whole_in = np.abs(testable.DRAUGHT_IN - np.round(testable.DRAUGHT_IN)) < 1e-4
    whole_out = np.abs(testable.DRAUGHT_OUT - np.round(testable.DRAUGHT_OUT)) < 1e-4
    print(f"  testable calls with whole-metre inbound {pct(int(whole_in.sum()), len(testable))}, "
          f"outbound {pct(int(whole_out.sum()), len(testable))}")

    section("V5", "plausibility bounds, kept calls (counts; nothing corrected)")
    print(f"  any inside draught >= AIS cap {p['ais_cap_m']} m: {int((k.DRAUGHT_MAX >= p['ais_cap_m'] - EPS).sum())}")
    print(f"  outbound draught > {p['review_above_m']} m (above indicative outer-channel depth, review only): "
          f"{int((k.DRAUGHT_OUT > p['review_above_m']).sum())}")
    print(f"  draught decreased in port by > {res} m (unexpected at a loading port): "
          f"{int((k.UPDATE == 'decreased').sum())}")
    print(f"  outbound draught range: {k.DRAUGHT_OUT[k.DRAUGHT_OUT > 0].min()} - {k.DRAUGHT_OUT.max()} m")

    section("V6", "by month of outbound crossing (FIRST_OUT): testable calls, changed")
    t2 = testable.assign(CH=changed, MU=testable.FIRST_OUT.dt.strftime("%Y-%m"),
                         ML=testable.FIRST_OUT.dt.tz_localize("UTC").dt.tz_convert(tz).dt.strftime("%Y-%m"))
    for col, name in [("MU", "UTC"), ("ML", tz)]:
        for m, g in t2.groupby(col):
            print(f"  {name} {m}: {pct(int(g.CH.sum()), len(g))}")
    print("  local Jul 2026 misses its first 8 h; local Sep 2026 holds only 8 h (UTC month files).")

    tr = e[e.EXCLUDED.fillna("").str.startswith("transit")]
    section("V7", f"transits (eligible, no inside ping < {p['stationary_kn']} kn): {len(tr)}")
    south = tr.MIN_LAT < p["pilotage_lat"]
    print(f"  entered south of handbook §8.1 pilotage latitude ({p['pilotage_lat']}): {pct(int(south.sum()), len(tr))}")
    print("  southernmost latitude reached: " + pd.cut(tr.MIN_LAT, [-20.45, -20.3, -20.2, -20.1667, -20.1, -20.0, -19.9])
          .value_counts().sort_index().to_string().replace("\n", "; "))
    print(f"  inside pings per transit: {tr.N_INSIDE.describe(percentiles=[.5, .9]).round(1).to_dict()}")
    print(f"  min SOG inside: {tr.MIN_SOG.describe(percentiles=[.1, .5, .9]).round(2).to_dict()}")
    print(f"  transits with an outbound crossing that also had a stationary call by the same vessel: "
          f"{int(tr.CRAFT_ID.isin(k.CRAFT_ID).sum())}")

    # Where do transit vessels stop? Outside pings within 24 h after the transit (before the vessel re-enters).
    # "Harbour" here = south of the pilotage latitude AND within the working polygon's bounding box (EPSG:7850),
    # so other ports in the NW sub-area are not counted.
    minx, miny, maxx, maxy = geom.bounds
    in_bbox = lambda d: d.X.between(minx, maxx) & d.Y.between(miny, maxy) & (d.LAT < p["pilotage_lat"])
    south_stop, any_stop, nxt = 0, 0, 0
    for t in tr.itertuples():
        if not t.OUTBOUND_OBSERVED:
            continue
        nxt += 1
        after = v.loc[t.I1 + 1:]
        after = after[(after.CRAFT_ID == t.CRAFT_ID) & (after.TS <= t.FIRST_OUT + pd.Timedelta(hours=24))]
        after = after.loc[:after.index[after.INSIDE.to_numpy()].min() - 1] if after.INSIDE.any() else after
        stop = after[after.SPEED < p["stationary_kn"]]
        any_stop += len(stop) > 0
        south_stop += bool(in_bbox(stop).any())
    print(f"  of {nxt} transits with an outbound crossing: stationary OUTSIDE the polygon within 24 h after: "
          f"{any_stop}; of which stationary south of the pilotage latitude within the polygon bbox (harbour area, "
          f"outside the polygon): {south_stop}")
    elig_rows = v[v.CRAFT_ID.isin(e.CRAFT_ID) & (v.SPEED < p["stationary_kn"]) & in_bbox(v)]
    out_rows = elig_rows[~elig_rows.INSIDE]
    print(f"  eligible vessels, stationary pings south of the pilotage latitude within the polygon bbox: {len(elig_rows)}; "
          f"inside polygon {int(elig_rows.INSIDE.sum())}; outside: "
          f"{len(out_rows)} rows, {out_rows.CRAFT_ID.nunique()} vessels")

    section("V8", "calls with unchanged draught (|out - in| <= resolution), kept calls; descriptive only")
    k["DWELL_H"] = (k.T_OUT - k.T_IN).dt.total_seconds() / 3600
    k["L_BIN"] = pd.cut(k.L_MODAL, [150, 200, 260, 300, 320, 400], right=False)
    un, ch = k[k.UPDATE == "unchanged"], k[k.UPDATE.isin(["increased", "decreased"])]
    print(f"  unchanged: {len(un)} of {len(k)} kept calls ({len(testable)} testable)")
    for col, name in [("FIRST_OUT", "UTC exit month")]:
        print(f"  by {name}: " + ", ".join(f"{m}: {n}" for m, n in un[col].dt.strftime("%Y-%m").value_counts().sort_index().items()))
    print("  by modal-length bin (m; bins are not a size-class decision): unchanged / changed")
    for b in k.L_BIN.cat.categories:
        print(f"    {str(b):>12}: {int((un.L_BIN == b).sum()):>4} / {int((ch.L_BIN == b).sum()):>4}")
    pc = [.1, .25, .5, .75, .9]
    print(f"  dwell hours inside (first to last inside ping), unchanged: {un.DWELL_H.describe(percentiles=pc).round(1).to_dict()}")
    print(f"  dwell hours inside, changed:                               {ch.DWELL_H.describe(percentiles=pc).round(1).to_dict()}")
    print(f"  unchanged with dwell < 12 h: {int((un.DWELL_H < 12).sum())}; >= 24 h: {int((un.DWELL_H >= 24).sum())}")
    print(f"  unchanged: inbound draught {un.DRAUGHT_IN.describe(percentiles=[.5]).round(1).to_dict()}")
    print(f"  unchanged calls merged from >1 inside run: {int((un.N_RUNS > 1).sum())}")

    CSV.parent.mkdir(parents=True, exist_ok=True)
    x.join(k[["UPDATE"]]).to_csv(CSV, index=False)
    print(f"\nper-call table (gitignored): DATA_ROOT/{CSV.relative_to(DATA).as_posix()}")


if __name__ == "__main__":
    main()
