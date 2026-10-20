"""Record what candidate boundary sources publish for Port Hedland. Reports attributes and extents only;
downloads no geometry and draws nothing.

Run from the repo root:  python scripts/s0/sources_check.py
Writes results/s0/sources_check.txt (overwrites; the file header carries the check time).
"""
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "results" / "s0" / "sources_check.txt"
SLIP_LAYER = ("https://public-services.slip.wa.gov.au/public/rest/services/"
              "SLIP_Public_Services/Boundaries/MapServer/12")
CKAN = "https://catalogue.data.wa.gov.au/api/3/action/"


def get(url, **params):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    return json.load(urllib.request.urlopen(url, timeout=60))


def main():
    out = [f"checked {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"]

    meta = get(SLIP_LAYER, f="json")
    out.append(f"\n[S1] SLIP layer: {meta['name']} | {meta['geometryType']} | wkid {meta['extent']['spatialReference']['wkid']}")
    out.append(f"  url {SLIP_LAYER}")
    q = get(f"{SLIP_LAYER}/query", where="name LIKE '%HEDLAND%'", outFields="*", returnGeometry="false", f="json")
    for feat in q["features"]:
        out.append(f"  feature: {feat['attributes']}")
    ext = get(f"{SLIP_LAYER}/query", where="name LIKE '%HEDLAND%'", returnExtentOnly="true", f="json")
    out.append(f"  extent (GDA2020 lon/lat): {ext['extent']}")

    pkg = get(CKAN + "package_show", id="port-authorities")["result"]
    out.append(f"\n[S2] data.wa.gov.au package 'port-authorities': {pkg['title']} | licence: {pkg.get('license_title')}")

    out.append("\n[S3] data.wa.gov.au keyword search (top 10 names per query)")
    for kw in ["berth", "wharf", "port hedland", "port limit"]:
        r = get(CKAN + "package_search", q=kw, rows=10)["result"]
        out.append(f"  '{kw}': {r['count']} hits; top: {[p['name'] for p in r['results']]}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
