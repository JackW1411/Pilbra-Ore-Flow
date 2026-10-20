"""Record which AMSA monthly sub-area datasets are listed right now, for release-lag tracking.

Run from the repo root:  python scripts/s0/amsa_listing.py
Appends one dated block to results/s0/amsa_listing.txt. Re-run on different days to bound
the listing date of each month (lag = first run that sees month M minus end of month M).
"""
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

URL = "https://www.operations.amsa.gov.au/Spatial/DataServices/DigitalData"
OUT = Path(__file__).resolve().parents[2] / "results" / "s0" / "amsa_listing.txt"
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]


def main():
    html = urllib.request.urlopen(URL, timeout=60).read().decode("utf-8", "replace")
    found = set(re.findall(r"<strong>Vessel Traffic Data Sub-areas (\w+) (\d{4})</strong>", html))
    listed = sorted(((int(y), MONTHS.index(m) + 1) for m, y in found if m in MONTHS), reverse=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"checked {now}  source {URL}",
             f"  latest sub-area month listed: {listed[0][0]}-{listed[0][1]:02d}",
             f"  most recent 3 listed: {[f'{y}-{m:02d}' for y, m in listed[:3]]}"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "a", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
