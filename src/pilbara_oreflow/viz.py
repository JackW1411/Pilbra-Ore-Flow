"""Outputs for people: weekly table and chart, Folium map of call tracks. No computation of tonnes here.

Weeks are Monday-Sunday in the aggregation timezone, keyed by the final loader dwell end (same basis as
tonnage.monthly). Every table carries coverage; unknown tonnage stays NaN.
"""
from __future__ import annotations

from pathlib import Path

import folium
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

COLOURS = {"laden": "#c0392b", "ballast": "#2471a3", "not_laden": "#7f8c8d", "unknown": "#d4ac0d"}


def weekly(calls: pd.DataFrame, cargo_t: pd.Series, base_t: pd.Series, tz: str, span=None) -> pd.DataFrame:
    """Weekly laden departures, usable count, coverage, baseline and model tonnes. model_total = usable predictions
    + class-mean fill for flagged laden departures (same rule as tonnage.monthly), so it is comparable with baseline.
    `span` = (first, last) UTC timestamp of the loaded AIS data; weeks not fully inside it get `partial` True."""
    laden = calls.laden_departure.fillna(False).astype(bool)
    local = calls.final_dwell_end.dt.tz_convert(tz).dt.tz_localize(None)
    df = pd.DataFrame({"week": local.dt.to_period("W-SUN").dt.start_time, "usable": calls.usable,
                       "cargo_t": cargo_t, "baseline_t": base_t})[laden]
    df["fill_t"] = df.baseline_t.where(~df.usable)
    g = df.groupby("week")
    out = pd.DataFrame({"laden_departures": g.size(), "usable": g.usable.sum(),
                        "model_usable_t": g.cargo_t.sum(min_count=1), "fill_t": g.fill_t.sum(min_count=1), "baseline_t": g.baseline_t.sum(min_count=1)})
    out["model_total_t"] = out[["model_usable_t", "fill_t"]].sum(axis=1, min_count=1)
    out["coverage"] = out.usable / out.laden_departures
    out["partial"] = False
    if span is not None:
        lo, hi = (pd.Timestamp(s).tz_convert(tz).tz_localize(None) for s in span)
        out["partial"] = (out.index < lo) | (out.index + pd.Timedelta(days=7) > hi)
    return out


def weekly_chart(wk: pd.DataFrame, path: Path, title: str = "Port Hedland laden departures") -> Path:
    """Top: laden departures per week (usable vs flagged). Bottom, only if tonnes were estimated: model and baseline
    Mt on their own axis (two panels, never a dual y-axis). Partial weeks at the data edges are left out."""
    n_partial = int(wk.get("partial", pd.Series(False, index=wk.index)).sum())
    if n_partial:
        wk = wk[~wk.partial]
        title = f"{title}, full weeks only"
    tonnes = wk[["model_total_t", "baseline_t"]].notna().any(axis=None)
    fig, axes = plt.subplots(2 if tonnes else 1, 1, figsize=(10, 6.5 if tonnes else 4), sharex=True, squeeze=False)
    ax = axes[0, 0]
    x = np.arange(len(wk))
    ax.bar(x, wk.usable, color="#2a78d6", label="usable departure draught", edgecolor="white", lw=1)
    ax.bar(x, wk.laden_departures - wk.usable, bottom=wk.usable, color="#8a8984", label="flagged (no cargo estimate)",
           edgecolor="white", lw=1)
    ax.set_ylabel("laden departures")
    ax.set_ylim(0, max(wk.laden_departures.max(), 1) * 1.2)                    # headroom for the legend
    ax.legend(loc="upper left", fontsize=8, ncol=2, frameon=False)
    cov = wk.usable.sum() / wk.laden_departures.sum() if wk.laden_departures.sum() else float("nan")
    ax.set_title(f"{title} (coverage {cov:.0%}, {int(wk.laden_departures.sum())} laden departures)", loc="left")
    if tonnes:
        ax2 = axes[1, 0]
        ax2.plot(x, wk.model_total_t / 1e6, color="#2a78d6", marker="s", label="draught model + class-mean fill")
        ax2.plot(x, wk.baseline_t / 1e6, color="#eb6834", ls="--", marker="^", label="baseline")
        ax2.set_ylabel("Mt per week")
        ax2.legend(loc="upper left", fontsize=8, ncol=2, frameon=False)
    axes[-1, 0].set_xticks(x, [d.strftime("%d %b") for d in wk.index], rotation=45, ha="right")
    fig.tight_layout()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def _status(v) -> str:
    if pd.isna(v):
        return "unknown"
    return "laden" if v else "not_laden"


def call_map(pings: pd.DataFrame, calls: pd.DataFrame, port_limit_4326=None, berths_4326=None,
             max_calls: int = 400) -> folium.Map:
    """Tracks per call: arrival leg (before the final dwell end) in blue, departure leg coloured by laden status.
    One marker per call at the last inside ping. `pings` from clean() (longitude/latitude in EPSG:4326)."""
    c = calls[calls.eligible].sort_values("t_out").tail(max_calls)
    centre = [pings.latitude.median(), pings.longitude.median()] if len(pings) else [-20.3, 118.6]
    # OSM's volunteer tile servers refuse file:// pages (no referer; 403 "Access blocked", seen 2026-10-17) and
    # folium 0.20 warns CartoDB now needs an API key. Esri World Imagery needs no key; its terms are [Unverified].
    m = folium.Map(location=centre, zoom_start=11, tiles=None)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Imagery: Esri, Maxar, Earthstar Geographics, and the GIS User Community", name="Esri World Imagery",
    ).add_to(m)
    if port_limit_4326 is not None:
        folium.GeoJson(port_limit_4326, name="port limit",
                       style_function=lambda _: {"fill": False, "color": "black", "weight": 1}).add_to(m)
    if berths_4326 is not None:
        folium.GeoJson(berths_4326, name="berths", tooltip=folium.GeoJsonTooltip(["name", "role"]),
                       style_function=lambda f: {"color": "#8e44ad" if f["properties"]["role"] == "loader" else "#95a5a6",
                                                 "weight": 1, "fillOpacity": 0.3}).add_to(m)
    layers = {k: folium.FeatureGroup(name=k).add_to(m) for k in ("ballast", "laden", "not_laden", "unknown")}
    by_vessel = dict(tuple(pings.groupby("craft_id")))
    for r in c.itertuples():
        p = by_vessel[r.craft_id]
        end = r.t_exit if pd.notna(r.t_exit) else r.t_out
        p = p[(p.timestamp_utc >= r.t_in) & (p.timestamp_utc <= end)]
        split = r.final_dwell_end if pd.notna(r.final_dwell_end) else r.t_out
        arr, dep = p[p.timestamp_utc <= split], p[p.timestamp_utc >= split]
        st = _status(r.laden_departure)
        if len(arr) > 1:
            folium.PolyLine(arr[["latitude", "longitude"]].to_numpy().tolist(), color=COLOURS["ballast"],
                            weight=1.5, opacity=0.6).add_to(layers["ballast"])
        if len(dep) > 1:
            folium.PolyLine(dep[["latitude", "longitude"]].to_numpy().tolist(), color=COLOURS[st],
                            weight=2, opacity=0.8).add_to(layers[st])
        last = p[p.timestamp_utc <= r.t_out].tail(1)
        if len(last):
            flags = [f for f in ("no_draught", "static_draught", "light_departure", "ais_gap", "implausible")
                     if getattr(r, f, False)]
            popup = (f"craft_id {r.craft_id:.0f}<br>{r.t_out:%Y-%m-%d %H:%M} UTC<br>{st}<br>"
                     f"class {r.size_class}, T_out {r.draught_out_m} m<br>flags: {', '.join(flags) or 'none'}<br>"
                     f"reasons: {r.reasons or '-'}")
            folium.CircleMarker(last[["latitude", "longitude"]].iloc[0].tolist(), radius=4, color=COLOURS[st],
                                fill=True, popup=folium.Popup(popup, max_width=320)).add_to(layers[st])
    folium.LayerControl().add_to(m)
    return m
