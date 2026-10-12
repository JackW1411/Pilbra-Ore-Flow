"""Fetch the working port-limit polygon (SLIP LGATE-243, Port Hedland) to DATA_ROOT/raw/ (gitignored).

Run from the repo root:  python scripts/s0/fetch_port_limit.py
Prints the retrieval time and sha256 of the saved file. The geometry itself is never committed.
"""
import hashlib
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from paths import DATA, load_config


def main():
    cfg = load_config()["port_limit"]
    params = {"where": f"objectid={cfg['objectid']}", "outFields": "*", "returnGeometry": "true",
              "outSR": cfg["crs"].split(":")[1], "f": "geojson"}
    raw = urllib.request.urlopen(f"{cfg['url']}/query?{urllib.parse.urlencode(params)}", timeout=120).read()
    out = DATA / cfg["path"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw)
    print(f"retrieved {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} -> DATA_ROOT/{cfg['path']}")
    print(f"bytes {len(raw)}  sha256 {hashlib.sha256(raw).hexdigest()}")


if __name__ == "__main__":
    main()
