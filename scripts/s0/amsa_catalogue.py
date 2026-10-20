"""List AMSA "Vessel Traffic Data Sub-areas" entries (the package that holds the North West area) with the
compressed size stated on each entry's download dialog. Reads listing and dialog pages only; downloads no data.

Run from the repo root:  python scripts/s0/amsa_catalogue.py
Writes results/s0/amsa_catalogue.txt (overwrites).
The NW area is one of three sub-areas inside each zip; its own size is not stated. "Mentions North West" is
taken from each entry's description text.
"""
import re
import time
import urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

BASE = "https://www.operations.amsa.gov.au"
LISTING = BASE + "/Spatial/DataServices/DigitalData"
DIALOG = BASE + "/spatial/DataServices/Download?contentItemId={}"
OUT = Path(__file__).resolve().parents[2] / "results" / "s0" / "amsa_catalogue.txt"
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August",
                                      "September", "October", "November", "December"], 1)}
TYPOS = {"Agust": "August", "Februrary": "February"}   # as spelled on the listing page


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "pilbara-ore-flow-s0"}),
                                  timeout=60).read().decode("utf-8", "replace")


def main():
    html = get(LISTING)
    # Each entry: <strong>Vessel Traffic Data Sub-areas Month YYYY</strong> ... description ... openDownload(id)
    # Titles vary in case and spacing ("sub-areas", "Sub-areas", "July  2017"); two month typos occur.
    pat = re.compile(r"<strong>\s*Vessel Traffic Data sub-areas\s+([A-Za-z]+)\s*(\d{4})\s*</strong>(.*?)openDownload\((\d+)\)",
                     re.S | re.I)
    entries = []
    for m in pat.finditer(html):
        month, year, body, cid = TYPOS.get(m.group(1), m.group(1)), int(m.group(2)), m.group(3), int(m.group(4))
        desc = unescape(re.sub(r"<[^>]+>", " ", body))
        entries.append(dict(label=f"{month} {year}", ym=(year, MONTHS.get(month, 0)), cid=cid,
                            nw=bool(re.search(r"North\s*West", desc, re.I))))
    out = [f"checked {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}  listing {LISTING}",
           f"sub-area entries listed: {len(entries)}; month names not parsed: "
           f"{[e['label'] for e in entries if e['ym'][1] == 0]}"]
    for e in entries:
        d = get(DIALOG.format(e["cid"]))
        txt = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", d)))
        size = re.search(r"File size:\s*([\d.]+\s*[KMG]B)", txt)
        e["size"] = size.group(1) if size else "not stated"
        time.sleep(0.5)
    entries.sort(key=lambda e: e["ym"])
    nw = [e for e in entries if e["nw"]]
    out.append(f"entries whose description mentions North West: {len(nw)} of {len(entries)}")
    if nw:
        out.append(f"earliest NW-mentioning entry: {nw[0]['label']}; latest: {nw[-1]['label']}")
    out.append(f"earliest sub-area entry: {entries[0]['label']}; latest: {entries[-1]['label']}")
    yms = [e["ym"] for e in entries]
    (y0, m0), (y1, m1) = yms[0], yms[-1]
    span = [(y, m) for y in range(y0, y1 + 1) for m in range(1, 13) if (y0, m0) <= (y, m) <= (y1, m1)]
    out.append(f"months in span {len(span)}; distinct titled months {len(set(yms))}; "
               f"duplicate titles {sorted({x for x in yms if yms.count(x) > 1})}; missing {[x for x in span if x not in set(yms)]}")
    out.append(f"entries whose description does not mention North West: {[e['label'] for e in entries if not e['nw']]} "
               "(contents not visible without download)")
    out.append("months are from entry titles; some descriptions name a different month than the title")

    def to_mb(s):
        m = re.match(r"([\d.]+)\s*([KMG])B", s)
        return float(m.group(1)) * {"K": 1 / 1024, "M": 1, "G": 1024}[m.group(2)] if m else None
    sizes = [to_mb(e["size"]) for e in entries if to_mb(e["size"]) is not None]
    if sizes:
        out.append(f"compressed size MB: min {min(sizes):.1f}, median {sorted(sizes)[len(sizes) // 2]:.1f}, "
                   f"max {max(sizes):.1f}, total {sum(sizes):.0f}")
    out.append("\nlabel | contentItemId | description mentions North West | compressed size")
    for e in entries:
        out.append(f"  {e['label']:15s} | {e['cid']:5d} | {str(e['nw']):5s} | {e['size']}")
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
