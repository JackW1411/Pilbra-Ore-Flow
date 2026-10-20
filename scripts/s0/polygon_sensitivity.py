"""Port-limit polygon sensitivity: buffer the UNBUFFERED SLIP polygon in EPSG:7850 and count calls.

Run from the repo root:  python scripts/s0/polygon_sensitivity.py
Writes results/s0/polygon_sensitivity.txt. Same call definition as gate_proxy.py (build_calls).
Buffers come from config [s0_gate_proxy].buffers_m. The polygon includes land; buffering moves both edges,
only the seaward one matters. Buffers are relative to the unbuffered SLIP polygon; the working limit is +port_limit.buffer_m (config).
"""
import sys

import shapely
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

from gate_proxy import build_calls, classify_update, load_config, load_inputs, working_limit
from probe_s0 import Tee

OUT = Path(__file__).resolve().parents[2] / "results" / "s0" / "polygon_sensitivity.txt"


def main():
    cfg = load_config()
    p = cfg["s0_gate_proxy"]
    sys.stdout = Tee(OUT)
    print("==== port-limit polygon sensitivity (SLIP LGATE-243 Port Hedland, buffered in EPSG:7850)")
    df, geom = load_inputs(cfg)
    parts = list(getattr(geom, "geoms", [geom]))
    print(f"working polygon: {len(parts)} part(s); interior rings (holes) per part: "
          f"{[len(q.interiors) for q in parts]}; part areas km2: {[round(q.area / 1e6, 1) for q in parts]}")
    # Harbour stationary pings (south of the handbook §8.1 pilotage latitude) inside vs outside, eligible-size cargo rows.

    minx, miny, maxx, maxy = geom.bounds  # restrict to the polygon bbox so other NW ports are excluded
    h = df[(df.LAT < p["pilotage_lat"]) & (df.SPEED < p["stationary_kn"])
           & df.X.between(minx, maxx) & df.Y.between(miny, maxy)]
    h = h[h.TYPE.fillna("").str.startswith("Cargo ship") & (h.LENGTH >= p["min_modal_length_m"])]
    hin = shapely.contains_xy(geom, h.X.to_numpy(), h.Y.to_numpy())
    print(f"row-level check (row TYPE Cargo*, row LENGTH >= {p['min_modal_length_m']} m, SOG < {p['stationary_kn']} kn, "
          f"south of {p['pilotage_lat']}, within polygon bbox): {len(h)} rows; inside polygon {int(hin.sum())}, outside {int((~hin).sum())}")
    ho = h[~hin]
    if len(ho):
        print(f"  outside rows lon {ho.LON.min():.4f}..{ho.LON.max():.4f}, lat {ho.LAT.min():.4f}..{ho.LAT.max():.4f}")
    base = None
    print(f"{'buffer_m':>8} {'area_km2':>9} {'calls_all':>9} {'eligible':>8} {'kept':>5} {'transit':>7} "
          f"{'no_in':>5} {'no_out':>6} {'ais_gap':>7} {'testable':>8} {'changed':>7} {'parts':>5} {'holes':>5}  kept vs 0 m")
    rows = []
    for b in p["buffers_m"]:
        g = geom.buffer(b) if b else geom
        x, _, _ = build_calls(df, g, p)
        e = x[x.ELIGIBLE]
        k = e[e.EXCLUDED.isna()]
        u = classify_update(k, 0.1)
        tst = ~u.str.startswith("no_draught")
        ex = e.EXCLUDED.fillna("")
        gp = list(getattr(g, "geoms", [g]))
        holes = sum(len(q.interiors) for q in gp)
        rows.append((b, g.area / 1e6, len(x), len(e), len(k), int(ex.str.startswith("transit").sum()),
                     int(ex.str.startswith("no inbound").sum()), int(ex.str.startswith("no outbound").sum()),
                     int(k.AIS_GAP.sum()), int(tst.sum()), int(u.isin(["increased", "decreased"]).sum()), len(gp), holes))
        if b == 0:
            base = len(k)
    for r in rows:
        print(f"{r[0]:>8} {r[1]:>9.1f} {r[2]:>9} {r[3]:>8} {r[4]:>5} {r[5]:>7} {r[6]:>5} {r[7]:>6} {r[8]:>7} "
              f"{r[9]:>8} {r[10]:>7} {r[11]:>5} {r[12]:>5}  {r[4] - base:+d} ({(r[4] - base) / base:+.1%})")
    print("changed = draught differs by > 0.1 m between inbound and outbound (resolution from gate_proxy.txt V3).")

    # Pilotage-line boundary (handbook §8.1: "south of Latitude 20°10.000'S within the Port Limits"):
    # working limit (SLIP + buffer_m) clipped to south of pilotage_lat. Line built in EPSG:4326, densified, projected.
    work = working_limit(geom, cfg)
    south = gpd.GeoSeries([box(110.0, -25.0, 125.0, p["pilotage_lat"])], crs="EPSG:4326").segmentize(0.01)
    clip = work.intersection(south.to_crs(cfg["crs"]["distance"]).iloc[0])
    names = ["calls_all", "eligible", "kept", "transit", "no_in", "no_out", "ais_gap", "testable", "changed"]
    def summary(g):
        x, _, _ = build_calls(df, g, p)
        e = x[x.ELIGIBLE]
        k = e[e.EXCLUDED.isna()]
        u = classify_update(k, 0.1)
        ex = e.EXCLUDED.fillna("")
        return dict(zip(names, [len(x), len(e), len(k), int(ex.str.startswith("transit").sum()),
                                int(ex.str.startswith("no inbound").sum()), int(ex.str.startswith("no outbound").sum()),
                                int(k.AIS_GAP.sum()), int((~u.str.startswith("no_draught")).sum()),
                                int(u.isin(["increased", "decreased"]).sum())])), k
    sw, kw = summary(work)
    sc, kc = summary(clip)
    print()
    print(f"==== pilotage-line boundary vs working limit (+{cfg['port_limit']['buffer_m']} m); config unchanged")
    print(f"clip area {clip.area / 1e6:.1f} km2 vs working {work.area / 1e6:.1f} km2")
    print("difference (pilotage-line minus working limit): " + ", ".join(f"{n} {sc[n] - sw[n]:+d}" for n in names))
    dw = ((kw.T_OUT - kw.T_IN).dt.total_seconds() / 3600).median()
    dc = ((kc.T_OUT - kc.T_IN).dt.total_seconds() / 3600).median()
    print(f"difference in median kept-call duration inside (h): {dc - dw:+.1f}")
    print(f"difference in changed share of testable: {sc['changed'] / sc['testable'] - sw['changed'] / sw['testable']:+.1%}")


if __name__ == "__main__":
    main()
