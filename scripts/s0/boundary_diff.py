"""Which calls does the pilotage-line boundary add relative to the +500 m working limit? Report only.

Boundaries (both from polygon_sensitivity.py logic; config unchanged):
  W = working limit (SLIP polygon + port_limit.buffer_m)
  P = W clipped to south of the handbook §8.1 pilotage latitude
Kept calls under each are compared per vessel by time overlap of [T_IN, T_OUT]:
  - a P call with no overlapping kept W call            -> "no W call in window"
  - several P calls overlapping one kept W call         -> "W call split into n P calls"
The "extra" set is every P call that is not in a one-to-one P<->W relation. Net extra = kept(P) - kept(W).
Draught-unchanged extra calls are described by length bin, dwell inside P, nearest OSM berth to the centroid of
their stationary inside pings, and whether the vessel has any W call (kept or excluded) overlapping the window.
No labels are assigned.

Run from the repo root:  python scripts/s0/boundary_diff.py
Writes scripts/s0/output/boundary_diff.txt (no CRAFT_IDs).
"""
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point, box

from gate_proxy import build_calls, classify_update, load_config, load_inputs, working_limit
from osm_nearest_berth import fetch_osm_berths
from probe_s0 import Tee

OUT = Path(__file__).resolve().parent / "output" / "boundary_diff.txt"
L_BINS = [150, 200, 260, 300, 320, 400]


def kept_calls(df, geom, p):
    x, _, v = build_calls(df, geom, p)
    e = x[x.ELIGIBLE].copy()
    k = e[e.EXCLUDED.isna()].copy()
    k["UPDATE"] = classify_update(k, 0.1)
    return k, e, v


def main():
    cfg = load_config()
    p = cfg["s0_gate_proxy"]
    sys.stdout = Tee(OUT)
    print("==== pilotage-line boundary (P) vs +500 m working limit (W): extra calls. Report only; config unchanged.")
    df, raw = load_inputs(cfg)
    W = working_limit(raw, cfg)
    south = gpd.GeoSeries([box(110.0, -25.0, 125.0, p["pilotage_lat"])], crs="EPSG:4326").segmentize(0.01)
    P = W.intersection(south.to_crs(cfg["crs"]["distance"]).iloc[0])

    kw, ew, _ = kept_calls(df, W, p)
    kp, _, vp = kept_calls(df, P, p)
    print(f"kept calls: P {len(kp)}, W {len(kw)}, net extra {len(kp) - len(kw):+d}")

    # Overlap P kept calls with W kept calls of the same vessel.
    kp = kp.reset_index(drop=True)
    kp["W_MATCH"] = -1
    kp["ANY_W_OVERLAP"] = False
    for i, r in kp.iterrows():
        cand = kw[(kw.CRAFT_ID == r.CRAFT_ID) & (kw.T_IN <= r.T_OUT) & (kw.T_OUT >= r.T_IN)]
        if len(cand):
            kp.at[i, "W_MATCH"] = cand.index[0]
        anyw = ew[(ew.CRAFT_ID == r.CRAFT_ID) & (ew.T_IN <= r.T_OUT) & (ew.T_OUT >= r.T_IN)]
        kp.at[i, "ANY_W_OVERLAP"] = len(anyw) > 0
    n_per_w = kp[kp.W_MATCH >= 0].groupby("W_MATCH").size()
    kp["SPLIT_N"] = kp.W_MATCH.map(n_per_w).fillna(0).astype(int)
    kp["EXTRA_SET"] = (kp.W_MATCH < 0) | (kp.SPLIT_N > 1)
    no_w = kp.W_MATCH < 0
    print(f"\n[B1] P calls with no overlapping kept W call: {int(no_w.sum())} "
          f"(of which overlapping an excluded W call: {int((no_w & kp.ANY_W_OVERLAP).sum())})")
    print(f"     kept W calls split into >1 P call: {int((n_per_w > 1).sum())}; P calls in those splits: "
          f"{int(n_per_w[n_per_w > 1].sum())}; split sizes {n_per_w[n_per_w > 1].value_counts().sort_index().to_dict()}")
    print(f"     kept W calls with no overlapping kept P call: {len(kw) - kp.W_MATCH[kp.W_MATCH >= 0].nunique()}")
    print(f"     extra set (not one-to-one): {int(kp.EXTRA_SET.sum())} P calls; "
          f"check: no-W {int(no_w.sum())} + split surplus {int((n_per_w[n_per_w > 1] - 1).sum())} "
          f"- unmatched W {len(kw) - kp.W_MATCH[kp.W_MATCH >= 0].nunique()} = net {len(kp) - len(kw):+d}")

    x = kp[kp.EXTRA_SET]
    print(f"\n[B2] draught outcome in the extra set: {x.UPDATE.value_counts().to_dict()}")
    print(f"     draught outcome in one-to-one P calls: {kp[~kp.EXTRA_SET].UPDATE.value_counts().to_dict()}")

    u = x[x.UPDATE == "unchanged"].copy()
    u["DWELL_H"] = (u.T_OUT - u.T_IN).dt.total_seconds() / 3600
    u["L_BIN"] = pd.cut(u.L_MODAL, L_BINS, right=False)
    for attempt in range(5):   # Overpass is intermittently unavailable; every failure is reported
        try:
            berths, url, errors = fetch_osm_berths(cfg)
            errors = [f"attempt {attempt + 1}"] + errors if attempt else errors
            break
        except SystemExit as exc:
            print(f"  OSM fetch attempt {attempt + 1} failed: {exc}", file=sys.__stderr__)
            time.sleep(60)
    else:
        raise SystemExit("OSM berths unavailable after 5 attempts")
    cents = []
    for r in u.itertuples():
        seg = vp.loc[r.I0:r.I1]
        st = seg[seg.INSIDE & (seg.SPEED < p["stationary_kn"])]
        cents.append(Point(st.X.mean(), st.Y.mean()) if len(st) else None)
    u["NEAREST"], u["DIST_M"] = None, np.nan
    for i, c in zip(u.index, cents):
        if c is None:
            continue
        d = berths.distance(c)
        u.at[i, "NEAREST"], u.at[i, "DIST_M"] = berths.name.iloc[int(d.argmin())], float(d.min())
    print(f"\n[B3] draught-unchanged calls in the extra set: {len(u)} (OSM via {url}; failed before: {errors or 'none'})")
    print("  by modal-length bin: " + ", ".join(f"{b}: {int((u.L_BIN == b).sum())}" for b in u.L_BIN.cat.categories))
    print(f"  dwell hours inside P: {u.DWELL_H.describe(percentiles=[.1, .5, .9]).round(1).to_dict()}")
    print(f"  in a split W call: {int((u.SPLIT_N > 1).sum())}; no kept W call in window: {int((u.W_MATCH < 0).sum())}; "
          f"vessel has any W call (kept or excluded) overlapping the window: {int(u.ANY_W_OVERLAP.sum())}")
    print("  nearest OSM berth to stationary-ping centroid: " + ", ".join(
        f"{k}: {n}" for k, n in u.NEAREST.fillna("<no stationary ping>").value_counts().items()))
    print(f"  distance to nearest OSM berth (m): {u.DIST_M.describe(percentiles=[.5, .9]).round(0).to_dict()}")
    print("  per call (no IDs): modal L | dwell h | in split W call (n) | any W overlap | nearest OSM berth | distance m")
    for r in u.sort_values(["NEAREST", "DWELL_H"]).itertuples():
        print(f"    {r.L_MODAL:5.0f} | {r.DWELL_H:6.1f} | {r.SPLIT_N:2d} | {str(r.ANY_W_OVERLAP):5s} | "
              f"{str(r.NEAREST):6s} | {r.DIST_M:6.0f}")


if __name__ == "__main__":
    main()
