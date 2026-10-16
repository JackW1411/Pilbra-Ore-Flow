"""Download AMSA "Vessel Traffic Data Sub-areas" monthly zips and their metadata PDFs into DATA_ROOT/raw/sub_YYYY_MM/.

Submitting the download form sets TermsAccepted=true, i.e. accepts AMSA's Copyright and Disclaimer
(CC BY-NC 3.0 AU; accepted by Jack 2026-10-12, re-approved for these downloads 2026-10-16).
Prints bytes and sha256 for docs/sources.md. Extracts the NW point shapefile zip next to it.

    python scripts/s2/fetch_amsa.py 6410:2026-03 6450:2026-04 ...      (contentItemId:YYYY-MM from amsa_catalogue.txt)
"""
import hashlib
import re
import sys
import urllib.parse
import urllib.request
import zipfile
from html import unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from pilbara_oreflow.config import data_root, load_config  # noqa: E402

BASE = "https://www.operations.amsa.gov.au"
UA = {"User-Agent": "pilbara-ore-flow-s2"}


def _get(url, data=None):
    return urllib.request.urlopen(urllib.request.Request(url, data=data, headers=UA), timeout=600)


def _save(resp, path: Path) -> tuple[int, str]:
    h, n = hashlib.sha256(), 0
    with open(path, "wb") as f:
        while chunk := resp.read(1 << 20):
            f.write(chunk)
            h.update(chunk)
            n += len(chunk)
    return n, h.hexdigest()


def fetch(cid: int, ym: str, raw: Path):
    y, m = ym.split("-")
    out = raw / f"sub_{y}_{m}"
    out.mkdir(parents=True, exist_ok=True)
    dialog = _get(f"{BASE}/spatial/DataServices/Download?contentItemId={cid}").read().decode("utf-8", "replace")
    title = unescape(re.search(r'id="Title" name="Title" type="hidden" value="([^"]*)"', dialog).group(1))
    month_name = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                  "November", "December"][int(m) - 1]
    if f"{month_name} {y}" not in title:
        raise SystemExit(f"contentItemId {cid} is '{title}', not {ym}")
    desc = unescape(re.search(r'id="Description" name="Description" type="hidden" value="([^"]*)"', dialog).group(1))
    meta = re.search(r'href="(/spatial/File/DownloadFile\?fileName=([^&"]+)&amp;[^"]+)"', dialog)
    if meta:
        n, h = _save(_get(BASE + unescape(meta.group(1))), out / meta.group(2))
        print(f"{ym} {meta.group(2)} {n} {h}")
    form = urllib.parse.urlencode({"ContentItemId": cid, "Title": title, "Description": desc,
                                   "TermsAccepted": "true"}).encode()
    zpath = raw / f"amsa_subareas_{y}_{m}.zip"
    n, h = _save(_get(f"{BASE}/spatial/DataServices/Download", data=form), zpath)
    print(f"{ym} {zpath.name} {n} {h}")
    with zipfile.ZipFile(zpath) as z:
        inner = [i for i in z.namelist() if re.search(r"_pt\.zip$", i)]
        z.extractall(out, members=inner)
    for i in inner:
        with zipfile.ZipFile(out / i) as z2:
            z2.extractall(out / "pt")
    print(f"{ym} extracted {inner} -> {out / 'pt'}")


if __name__ == "__main__":
    raw = data_root(load_config()) / "raw"
    for arg in sys.argv[1:]:
        cid, ym = arg.split(":")
        fetch(int(cid), ym, raw)
