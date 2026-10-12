"""Distance from the harbour-gap patch to the nearest OSM seamark:type=berth features. Nothing is drawn or saved
except names, OSM ids and distances.

Run from the repo root:  python scripts/s0/osm_nearest_berth.py
Writes scripts/s0/output/osm_nearest_berth.txt. Geometry is fetched into memory only.
OSM data (c) OpenStreetMap contributors, ODbL. Mapping OSM names to handbook berths is [Unverified].
"""
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Polygon, box

from gate_proxy import load_config
from osm_check import BBOX, ENDPOINTS
from probe_s0 import Tee

OUT = Path(__file__).resolve().parent / "output" / "osm_nearest_berth.txt"


def fetch_osm_berths(cfg):
    """OSM seamark:type=berth polygons near Port Hedland, in memory, EPSG:7850. Returns (gdf, source_url, errors)."""
    q = f'[out:json][timeout:60];way["seamark:type"="berth"]({",".join(map(str, BBOX))});out geom;'
    errors = []
    for url in ENDPOINTS:
        try:
            req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": q}).encode(),
                                         headers={"User-Agent": "pilbara-ore-flow-s0-probe"})
            els = json.load(urllib.request.urlopen(req, timeout=120))["elements"]
            break
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    else:
        raise SystemExit("all Overpass endpoints failed: " + " | ".join(errors))
    feats = [{"osm": f"way/{e['id']}", "name": e["tags"].get("name"), "operator": e["tags"].get("operator"),
              "geometry": Polygon([(n["lon"], n["lat"]) for n in e["geometry"]])} for e in els]
    return gpd.GeoDataFrame(feats, crs="EPSG:4326").to_crs(cfg["crs"]["distance"]), url, errors


def main():
    cfg = load_config()
    sys.stdout = Tee(OUT)
    patch = cfg["s0_gate_proxy"]["harbour_gap_patch"]
    g, url, errors = fetch_osm_berths(cfg)
    print(f"checked {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} source {url}; failed before success: {errors or 'none'}")
    print(f"patch (lon/lat, from config harbour_gap_patch, gate_proxy V7): {patch}")
    pp = gpd.GeoSeries([box(*patch)], crs="EPSG:4326").to_crs(cfg["crs"]["distance"]).iloc[0]
    g["DIST_PATCH_M"] = g.distance(pp).round(0)
    g["DIST_CENTROID_M"] = g.distance(pp.centroid).round(0)
    g["INTERSECTS"] = g.intersects(pp)
    print(f"\n[N1] OSM berth features: {len(g)}; intersecting the patch: {int(g.INTERSECTS.sum())}")
    print("[N2] nearest 5 (distance from patch rectangle / from patch centroid, metres, EPSG:7850):")
    for r in g.sort_values("DIST_PATCH_M").head(5).itertuples():
        print(f"  {r.osm} name={r.name!r} operator={r.operator!r}: {r.DIST_PATCH_M:.0f} m / {r.DIST_CENTROID_M:.0f} m")


if __name__ == "__main__":
    main()
