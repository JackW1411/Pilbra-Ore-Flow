"""List OpenStreetMap berth/pier/wharf-type features near Port Hedland. Tags and counts only in the output.

Run from the repo root:  python scripts/s0/osm_check.py
Writes scripts/s0/output/osm_check.txt (overwrites). OSM data (c) OpenStreetMap contributors, ODbL.
Every raw Overpass response is saved, with its query text, to DATA_ROOT/raw/osm/ (gitignored); path and sha256 are
printed in the output so a run can be tied to the exact response.
"""
import hashlib
import json
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from paths import DATA

OUT = Path(__file__).resolve().parent / "output" / "osm_check.txt"
RAW_DIR = DATA / "raw" / "osm"
ENDPOINTS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
             "https://overpass.kumi.systems/api/interpreter"]
# Query bbox = SLIP LGATE-243 Port Hedland extent (S1 in sources_check.txt), rounded outward. Search area only.
BBOX = (-20.42, 118.35, -19.90, 118.76)  # south, west, north, east
FILTERS = [
    '["man_made"="pier"]', '["man_made"="quay"]', '["man_made"="breakwater"]',
    '["seamark:type"="berth"]', '["seamark:type"="mooring"]', '["seamark:type"="harbour"]',
    '["seamark:type"="anchorage"]', '["seamark:type"="anchor_berth"]',
    '["harbour"]', '["mooring"]', '["waterway"="dock"]', '["landuse"="port"]', '["industrial"="port"]',
]
KEYS = ["man_made", "seamark:type", "harbour", "mooring", "waterway", "landuse", "industrial", "name", "operator"]


def overpass(query: str, tag: str):
    """Run an Overpass query against ENDPOINTS in order. Saves the raw response and the query text to
    DATA_ROOT/raw/osm/<tag>_<UTC>.json / .query.txt. Returns (elements, url, errors, saved_path, 'sha256 (osm_base <timestamp>)')."""
    errors = []
    for url in ENDPOINTS:
        req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": query}).encode(),
                                     headers={"User-Agent": "pilbara-ore-flow-s0-probe"})
        try:
            raw = urllib.request.urlopen(req, timeout=120).read()
            els = json.loads(raw)["elements"]
            break
        except Exception as exc:  # report every failed endpoint; never fall back silently
            errors.append(f"{url}: {exc}")
    else:
        raise SystemExit("all Overpass endpoints failed: " + " | ".join(errors))
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{tag}_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    path = RAW_DIR / f"{stem}.json"
    path.write_bytes(raw)
    (RAW_DIR / f"{stem}.query.txt").write_text(f"endpoint: {url}\n{query}\n", encoding="utf-8", newline="\n")
    base = json.loads(raw).get("osm3s", {}).get("timestamp_osm_base", "not stated")
    # Mirrors serve different OSM snapshots; the base timestamp says which one this response reflects.
    return els, url, errors, path, f"{hashlib.sha256(raw).hexdigest()} (osm_base {base})"


def main():
    bb = ",".join(map(str, BBOX))
    body = "[out:json][timeout:90];(" + "".join(f"nwr{f}({bb});" for f in FILTERS) + ");out body;"  # body = tags + node refs (no coordinates)
    els, url, errors, saved, sha = overpass(body, "osm_check")

    out = [f"checked {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}  source {url}",
           f"bbox (S,W,N,E) {BBOX}; filters {FILTERS}",
           f"failed endpoints before success: {errors or 'none'}",
           f"raw response saved (gitignored): DATA_ROOT/{saved.relative_to(DATA).as_posix()} sha256 {sha}",
           f"\n[O1] elements returned: {len(els)} by type {dict(Counter(e['type'] for e in els))}"]
    for k in KEYS[:-2]:
        c = Counter(e["tags"][k] for e in els if k in e.get("tags", {}))
        if c:
            out.append(f"  {k}: {dict(c.most_common())}")
    out.append("\n[O2] elements (type/id, selected tags)")
    for e in sorted(els, key=lambda e: (e["tags"].get("man_made", ""), e["tags"].get("seamark:type", ""), e["id"])):
        t = {k: e["tags"][k] for k in KEYS if k in e["tags"]}
        if e["type"] == "way":
            nd = e.get("nodes", [])
            t["_shape"] = f"{'closed' if len(nd) > 2 and nd[0] == nd[-1] else 'open line'}, {len(nd)} nodes"
        out.append(f"  {e['type']}/{e['id']}: {t}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
