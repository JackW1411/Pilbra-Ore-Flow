"""PROVISIONAL GATE PROXY, ALL DEPARTURES, NOT THE S0 GATE.

For each outbound crossing of the working port limit (SLIP LGATE-243 Port Hedland polygon) by a vessel with
modal LENGTH >= min_modal_length_m and modal TYPE_CLASS == cargo: does it report a non-zero draught in the
final inside pings before exit? The denominator is ALL such departures (laden and ballast), because no
draught-free laden-departure definition exists yet (needs berth polygons). It is therefore not the S0 gate.

Run from the repo root:  python scripts/s0/gate_proxy.py   (after scripts/s0/fetch_port_limit.py)
Writes aggregates to scripts/s0/output/gate_proxy.txt (committed) and one row per crossing to
data/interim/s0_gate_proxy_crossings.csv (gitignored; contains CRAFT_IDs).
Parameters come from config/project.toml [s0_gate_proxy]; nothing is tuned here.
"""
import sys
import tomllib
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from probe_s0 import MONTHS, ROOT, Tee, load, modal_positive, modal_type, type_class

OUT = Path(__file__).resolve().parent / "output" / "gate_proxy.txt"
CSV = ROOT / "data" / "interim" / "s0_gate_proxy_crossings.csv"
LABEL = "provisional gate proxy, all departures, not the S0 gate"


def pct(n, d):
    return f"{n}/{d} ({n / d:.1%})" if d else f"{n}/0 (n/a)"


def main():
    cfg = tomllib.loads((ROOT / "config" / "project.toml").read_text(encoding="utf-8"))
    p, pl, crs = cfg["s0_gate_proxy"], cfg["port_limit"], cfg["crs"]
    tz = cfg["aggregation"]["timezone"]
    sys.stdout = Tee(OUT)
    print(f"==== {LABEL.upper()}")
    print(f"port limit: {pl['source']} ({pl['path']}, {pl['crs']}); equivalence to handbook §4.3 [Unverified]")
    print(f"params: {p}; aggregation timezone {tz}; geometric tests in {crs['distance']}")

    limit = gpd.read_file(ROOT / pl["path"]).set_crs(pl["crs"], allow_override=True).to_crs(crs["distance"])
    limit_geom = limit.geometry.union_all()

    df = pd.concat([load(m)[0] for m in MONTHS], ignore_index=True)
    data_start, data_end = df.TS.min(), df.TS.max()
    print(f"AIS rows {len(df)} ({MONTHS[0]}..{MONTHS[-1]}), TS {data_start} -> {data_end} (taken as UTC)")

    pts = gpd.GeoSeries(gpd.points_from_xy(df.LON, df.LAT), crs=crs["ais_input"]).to_crs(crs["distance"])
    minx, miny, maxx, maxy = limit_geom.bounds
    cand = (pts.x.between(minx, maxx) & pts.y.between(miny, maxy)).to_numpy()
    df["INSIDE"] = False
    df.loc[cand, "INSIDE"] = pts[cand].within(limit_geom).to_numpy()
    ever_in = df.loc[df.INSIDE, "CRAFT_ID"].unique()
    # Keep ALL rows of vessels that were ever inside, so the first ping after an exit is never cut off.
    v = df[df.CRAFT_ID.isin(ever_in)].sort_values(["CRAFT_ID", "TS"]).reset_index(drop=True)

    # Vessel attributes from rows inside the limit (both months), modal values; row TYPE kept unchanged.
    ins = v[v.INSIDE]
    vessels = ins.groupby("CRAFT_ID").agg(TYPE_MODAL=("TYPE", modal_type), L_MODAL=("LENGTH", modal_positive),
                                         B_MODAL=("BEAM", modal_positive))
    vessels["TYPE_CLASS"] = vessels.TYPE_MODAL.map(type_class)
    vessels["UNCLASSIFIED_SIZE"] = vessels.L_MODAL.isna() | vessels.B_MODAL.isna()

    # Runs of consecutive inside pings per vessel; an exit is the last ping of a run followed by an outside ping.
    v["RUN"] = (v.INSIDE != v.groupby("CRAFT_ID").INSIDE.shift()).cumsum()
    nxt = v.groupby("CRAFT_ID")[["INSIDE", "TS"]].shift(-1)
    rows = []
    for (cid, run), r in v[v.INSIDE].groupby(["CRAFT_ID", "RUN"], sort=False):
        last_i = r.index[-1]
        has_next = pd.notna(nxt.at[last_i, "TS"])
        rec = dict(CRAFT_ID=cid, RUN=run, RUN_START=r.TS.iloc[0], LAST_IN=r.TS.iloc[-1],
                   RUN_STARTS_AT_DATA_START=r.index[0] == v.index[v.CRAFT_ID == cid][0],
                   EXIT_OBSERVED=bool(has_next), FIRST_OUT=nxt.at[last_i, "TS"] if has_next else pd.NaT,
                   ANY_STATIONARY=bool((r.SPEED < p["stationary_kn"]).any()), N_INSIDE=len(r))
        for k in p["final_pings"]:
            tail = r.DRAUGHT.iloc[-k:]
            rec[f"DRAUGHT_POS_LAST{k}"] = bool((tail > 0).any())
        rec["DRAUGHT_LAST"] = r.DRAUGHT.iloc[-1]
        rows.append(rec)
    x = pd.DataFrame(rows).join(vessels, on="CRAFT_ID")
    x["GAP_MIN"] = (x.FIRST_OUT - x.LAST_IN).dt.total_seconds() / 60
    nxt_run = x.groupby("CRAFT_ID").RUN_START.shift(-1)
    x["REENTRY_H"] = (nxt_run - x.FIRST_OUT).dt.total_seconds() / 3600
    x["REENTRY_CHECK_INCOMPLETE"] = x.REENTRY_H.isna() & (data_end - x.FIRST_OUT < pd.Timedelta(hours=p["reentry_hours"]))

    # Population: eligible vessels
    elig = (x.TYPE_CLASS == p["type_class"]) & (x.L_MODAL >= p["min_modal_length_m"])
    print(f"\n[G1] inside runs (all vessels): {len(x)}; vessels ever inside: {len(vessels)}")
    print(f"  runs by non-eligible vessels (context, not in proxy): {int((~elig).sum())}")
    print(f"    TYPE_CLASS != {p['type_class']}: {int((x.TYPE_CLASS != p['type_class']).sum())}; "
          f"cargo but unclassified_size: {int(((x.TYPE_CLASS == p['type_class']) & x.UNCLASSIFIED_SIZE).sum())}; "
          f"cargo, sized, modal L < {p['min_modal_length_m']} m: "
          f"{int(((x.TYPE_CLASS == p['type_class']) & ~x.UNCLASSIFIED_SIZE & (x.L_MODAL < p['min_modal_length_m'])).sum())}")

    e = x[elig].copy()
    print(f"\n[G2] eligible-vessel inside runs: {len(e)} (vessels {e.CRAFT_ID.nunique()})")
    # Exclusion cascade; each run gets the first reason that applies.
    reason = pd.Series(pd.NA, index=e.index, dtype="object")
    reason[~e.EXIT_OBSERVED] = "no exit observed (inside at data end)"
    reason[reason.isna() & (e.REENTRY_H < p["reentry_hours"])] = f"re-entry within {p['reentry_hours']} h (not a departure)"
    reason[reason.isna() & ~e.ANY_STATIONARY] = f"transit (no inside ping < {p['stationary_kn']} kn)"
    e["EXCLUDED"] = reason
    print("  exclusions (first applicable reason):")
    print(e.EXCLUDED.fillna("-- kept as departure").value_counts().to_string())

    d = e[e.EXCLUDED.isna()].copy()
    d["AIS_GAP"] = d.GAP_MIN > p["crossing_gap_min"]
    print(f"\n[G3] departures: {len(d)} (vessels {d.CRAFT_ID.nunique()})")
    print(f"  flagged ais_gap at crossing (gap > {p['crossing_gap_min']} min, kept, reported): {pct(int(d.AIS_GAP.sum()), len(d))}")
    print(f"  re-entry check incomplete (exit < {p['reentry_hours']} h before data end, kept): "
          f"{int(d.REENTRY_CHECK_INCOMPLETE.sum())}")
    print(f"  inside run began at the vessel's first ping in the data (arrival before {data_start:%Y-%m-%d}, kept): "
          f"{int(d.RUN_STARTS_AT_DATA_START.sum())}")
    print(f"  crossing gap minutes: {d.GAP_MIN.describe(percentiles=[.5, .95]).round(1).to_dict()}")

    print(f"\n[G4] {LABEL}")
    for k in p["final_pings"]:
        col = f"DRAUGHT_POS_LAST{k}"
        print(f"  draught > 0 in last {k} inside ping(s): {pct(int(d[col].sum()), len(d))}"
              f"  | excl. ais_gap: {pct(int(d.loc[~d.AIS_GAP, col].sum()), int((~d.AIS_GAP).sum()))}")
    print(f"  last inside ping draught == 0: {int((d.DRAUGHT_LAST == 0).sum())}; NaN: {int(d.DRAUGHT_LAST.isna().sum())}")
    print("  Note: draught > 0 does not show the value was updated after loading (static_draught not tested here).")

    print(f"\n[G5] by month of exit (FIRST_OUT), UTC and {tz}")
    d["MONTH_UTC"] = d.FIRST_OUT.dt.strftime("%Y-%m")
    d["MONTH_LOCAL"] = d.FIRST_OUT.dt.tz_localize("UTC").dt.tz_convert(tz).dt.strftime("%Y-%m")
    k1 = f"DRAUGHT_POS_LAST{p['final_pings'][0]}"
    for col in ["MONTH_UTC", "MONTH_LOCAL"]:
        g = d.groupby(col)[k1].agg(["sum", "size"])
        for m, r in g.iterrows():
            print(f"  {col} {m}: departures {int(r['size'])}, draught > 0 in last ping {pct(int(r['sum']), int(r['size']))}")
    start_l = data_start.tz_localize("UTC").tz_convert(tz)
    end_l = data_end.tz_localize("UTC").tz_convert(tz)
    print(f"  local data coverage {start_l} -> {end_l}: local {MONTHS[0]} misses its first "
          f"{(start_l - start_l.normalize().replace(day=1)).total_seconds() / 3600:.1f} h; "
          f"local month after {MONTHS[-1]} holds only {(end_l - end_l.normalize().replace(day=1)).total_seconds() / 3600:.1f} h. "
          "Partial local months are incomplete, not comparable.")

    CSV.parent.mkdir(parents=True, exist_ok=True)
    x.join(e[["EXCLUDED"]]).to_csv(CSV, index=False)
    print(f"\nper-crossing table (gitignored): {CSV.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
