"""Port calls and laden departures (docs/laden_departure.md). No draught is used to decide laden status.

Call: inbound to outbound crossing of the port limit; inside runs separated by < G hours outside are one call.
Laden departure needs all of:
  (a) a stationary dwell >= D_min hours at an iron-ore loading berth;
  (b) the final stationary dwell (>= final_dwell_min_h) before exit is at a loading berth;
  (c) the last inside ping is within T_max of that dwell's end, and no re-entry within X hours of exit.
Ineligible vessels (TYPE, size) are never laden departures. Calls whose exit is not observed get <NA>, as do
calls whose only failure is a loader dwell < D_min that was already under way when the data starts.
Dwell duration counts observed time only: ping intervals > dwell_max_interval_min are excluded, not bridged.
All geometry in EPSG:7850.
"""
from __future__ import annotations

import json

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import Polygon

from .config import data_root


# ---------------------------------------------------------------- geometry inputs
def load_port_limit(cfg: dict):
    """Working port limit: SLIP LGATE-243 polygon + port_limit.buffer_m (capped), EPSG:7850."""
    pl = cfg["port_limit"]
    b = pl["buffer_m"]
    if not 0 <= b <= pl["max_buffer_m"]:
        raise ValueError(f"port_limit.buffer_m={b} outside [0, {pl['max_buffer_m']}]")
    g = gpd.read_file(data_root(cfg) / pl["path"]).set_crs(pl["crs"], allow_override=True)
    geom = g.to_crs(cfg["crs"]["distance"]).geometry.union_all()
    return geom.buffer(b) if b else geom


def load_berths(cfg: dict) -> gpd.GeoDataFrame:
    """Berth polygons from the saved OSM response named in config [berths], with roles from config."""
    bc = cfg["berths"]
    els = json.loads((data_root(cfg) / bc["osm_file"]).read_text(encoding="utf-8"))["elements"]
    rows = []
    for e in els:
        name = e.get("tags", {}).get("name")
        if name is None:
            continue
        role = "loader" if name in bc["loader_names"] else "other"
        rows.append({"name": name, "role": role, "multi_user": name in bc.get("multi_user_names", []),
                     "geometry": Polygon([(n["lon"], n["lat"]) for n in e["geometry"]])})
    missing = set(bc["loader_names"]) - {r["name"] for r in rows}
    if missing:
        raise ValueError(f"loader berths not found in {bc['osm_file']}: {sorted(missing)}")
    return gpd.GeoDataFrame(rows, crs="EPSG:4326").to_crs(cfg["crs"]["distance"])


# ---------------------------------------------------------------- helpers
def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Inclusive (start, end) index pairs of consecutive True values."""
    if not mask.any():
        return []
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1) - 1
    return list(zip(starts.tolist(), ends.tolist()))


def _nearest_berth(x, y, berths, buffer_m) -> np.ndarray:
    """Index of the nearest berth polygon within buffer_m of each point, else -1."""
    best = np.full(len(x), -1)
    best_d = np.full(len(x), np.inf)
    pts = shapely.points(x, y)
    for j, geom in enumerate(berths.geometry.values):
        d = shapely.distance(geom, pts)
        take = (d <= buffer_m) & (d < best_d)
        best[take], best_d[take] = j, d[take]
    return best


# ---------------------------------------------------------------- calls
def build_calls(pings: pd.DataFrame, vessels: pd.DataFrame, port_limit, berths: gpd.GeoDataFrame,
                cfg: dict) -> pd.DataFrame:
    """One row per call. `pings` must come from clean() (sorted by craft_id, time; x/y in EPSG:7850)."""
    c = cfg["calls"]
    G, DMIN, TMAX, X = (pd.Timedelta(hours=c[k]) for k in ("merge_gap_h", "d_min_h", "t_max_h", "reentry_x_h"))
    FINAL_MIN = pd.Timedelta(hours=c["final_dwell_min_h"])
    GAP = pd.Timedelta(minutes=c["crossing_gap_min"])
    DGAP = pd.Timedelta(minutes=c["dwell_max_interval_min"])
    if "multi_user" not in berths:
        berths = berths.assign(multi_user=False)

    shapely.prepare(port_limit)
    inside_all = shapely.contains_xy(port_limit, pings.x.to_numpy(), pings.y.to_numpy())
    ever = pd.unique(pings.craft_id.to_numpy()[inside_all])
    keep = pings.craft_id.isin(ever).to_numpy()
    p = pings[keep].reset_index(drop=True)
    inside = inside_all[keep]
    if len(p) == 0:
        return pd.DataFrame()
    t = p.timestamp_utc
    cid = p.craft_id.to_numpy()
    stationary = (p.speed < c["sog_stationary_kn"]).to_numpy()
    berth_ix = np.full(len(p), -1)
    berth_ix[stationary] = _nearest_berth(p.x.to_numpy()[stationary], p.y.to_numpy()[stationary],
                                          berths, c["berth_buffer_m"])

    new_vessel = np.concatenate([[True], cid[1:] != cid[:-1]])
    first_ix = pd.Series(np.arange(len(p))).groupby(cid).transform("min").to_numpy()
    last_ix = pd.Series(np.arange(len(p))).groupby(cid).transform("max").to_numpy()

    # inside runs -> calls (merge runs < G apart, measured inside-to-inside)
    runs = []
    run_id = np.cumsum(new_vessel | np.concatenate([[True], inside[1:] != inside[:-1]]))
    for _, idx in pd.Series(np.arange(len(p)))[inside].groupby(run_id[inside]):
        runs.append((idx.iloc[0], idx.iloc[-1]))
    calls_ix = []
    for s, e in runs:
        if calls_ix and cid[calls_ix[-1][0]] == cid[s] and t.iloc[s] - t.iloc[calls_ix[-1][1]] < G:
            calls_ix[-1] = (calls_ix[-1][0], e)
        else:
            calls_ix.append((s, e))

    roles = berths.role.to_numpy()
    names = berths.name.to_numpy()
    multi = berths.multi_user.to_numpy()
    rows = []
    for n, (s, e) in enumerate(calls_ix):
        v = cid[s]
        in_obs, out_obs = s > first_ix[s], e < last_ix[e]
        t_in, t_out = t.iloc[s], t.iloc[e]
        t_exit = t.iloc[e + 1] if out_obs else pd.NaT
        gap_in = (t_in - t.iloc[s - 1]) if in_obs else pd.NaT
        gap_out = (t_exit - t_out) if out_obs else pd.NaT
        ais_gap = bool((in_obs and gap_in > GAP) or (out_obs and gap_out > GAP))

        dwells = []
        for a, b in _runs(stationary[s:e + 1]):
            a, b = a + s, b + s
            bi = berth_ix[a:b + 1]
            j, share = -1, 0.0
            if (bi >= 0).any():
                vals, cnt = np.unique(bi[bi >= 0], return_counts=True)
                j = int(vals[cnt.argmax()])
                share = cnt.max() / len(bi)
            if share < c["berth_inside_frac"]:
                j = -1
            dt = t.iloc[a:b + 1].diff().iloc[1:]
            dwells.append(dict(a=a, start=t.iloc[a], end=t.iloc[b], dur=dt[dt <= DGAP].sum(),
                               role=roles[j] if j >= 0 else "none", berth=names[j] if j >= 0 else None,
                               multi=bool(multi[j]) if j >= 0 else False))
        loader = [d for d in dwells if d["role"] == "loader" and d["dur"] >= DMIN]
        sig = [d for d in dwells if d["dur"] >= FINAL_MIN]
        final = sig[-1] if sig else None

        reasons = []
        vrow = vessels.loc[v]
        eligible = bool(vrow.eligible)
        if not eligible:
            reasons.append(str(vrow.ineligible_reason))
        if not loader:
            reasons.append("no_loader_dwell_ge_dmin")
        if final is None or final["role"] != "loader":
            reasons.append("final_dwell_not_loader")
        elif t_out - final["end"] > TMAX:
            reasons.append("exit_after_tmax")
        nxt = n + 1 < len(calls_ix) and cid[calls_ix[n + 1][0]] == v
        if out_obs and nxt and t.iloc[calls_ix[n + 1][0]] - t_exit < X:
            reasons.append("reentry_within_x")
        elif out_obs and not nxt and t.iloc[last_ix[e]] - t_exit < X:
            reasons.append("reentry_check_incomplete")              # informational: data ends too soon
        if not in_obs:
            reasons.append("no_inbound_observed")                   # informational
        blocking = [r for r in reasons if r not in ("reentry_check_incomplete", "no_inbound_observed")]
        truncated = (not in_obs and blocking == ["no_loader_dwell_ge_dmin"]
                     and bool(dwells) and dwells[0]["a"] == s and dwells[0]["role"] == "loader")
        if truncated:
            reasons.append("loader_dwell_truncated")                # dwell started before the data: unknown
        if not eligible:
            laden = False
        elif not out_obs or truncated:
            laden = pd.NA
        else:
            laden = len(blocking) == 0
        if not out_obs:
            reasons.append("no_outbound_observed")

        ins_rows = np.flatnonzero(inside[s:e + 1]) + s
        lead = max(loader, key=lambda d: d["dur"]) if loader else None
        rows.append(dict(
            call_id=n, craft_id=v, t_in=t_in, t_out=t_out, t_exit=t_exit,
            inbound_observed=bool(in_obs), outbound_observed=bool(out_obs),
            gap_in_min=gap_in.total_seconds() / 60 if in_obs else np.nan,
            gap_out_min=gap_out.total_seconds() / 60 if out_obs else np.nan,
            ais_gap=ais_gap, n_pings=e - s + 1, n_inside=len(ins_rows),
            loader_dwell_h=(lead["dur"].total_seconds() / 3600) if lead else 0.0,
            loader_berth=lead["berth"] if lead else None,
            final_dwell_role=final["role"] if final else "none",
            final_dwell_berth=final["berth"] if final else None,
            final_dwell_end=final["end"] if final else pd.NaT,
            final_berth_multi_user=final["multi"] if final else False,
            eligible=eligible, type_class=vrow.type_class, size_class=vrow.size_class,
            length_m=vrow.length_m, beam_m=vrow.beam_m,
            laden_departure=laden, reasons=";".join(reasons),
            draught_in_m=p.draught_m.iloc[ins_rows[0]], draught_in_status=p.draught_status.iloc[ins_rows[0]],
            draught_out_m=p.draught_m.iloc[ins_rows[-1]], draught_out_status=p.draught_status.iloc[ins_rows[-1]],
        ))
    out = pd.DataFrame(rows)
    out["laden_departure"] = out.laden_departure.astype("boolean")
    return out
