"""Fetch the working port-limit polygon (SLIP LGATE-243, Port Hedland) to data/raw/ (gitignored).

Run from the repo root:  python scripts/s0/fetch_port_limit.py
Prints the retrieval time and sha256 of the saved file. The geometry itself is never committed.
"""
import hashlib
import tomllib
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    cfg = tomllib.loads((ROOT / "config" / "project.toml").read_text(encoding="utf-8"))["port_limit"]
    params = {"where": f"objectid={cfg['objectid']}", "outFields": "*", "returnGeometry": "true",
              "outSR": cfg["crs"].split(":")[1], "f": "geojson"}
    raw = urllib.request.urlopen(f"{cfg['url']}/query?{urllib.parse.urlencode(params)}", timeout=120).read()
    out = ROOT / cfg["path"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw)
    print(f"retrieved {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} -> {cfg['path']}")
    print(f"bytes {len(raw)}  sha256 {hashlib.sha256(raw).hexdigest()}")


if __name__ == "__main__":
    main()
