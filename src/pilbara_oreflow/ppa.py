"""PPA Port Hedland "cargo, GRT and DWT statistics by commodity type" monthly PDF -> per-line and per-call tables.

Evaluation data only (CLAUDE.md Fixed decisions). Vessel name, GRT and DWT are read only to group cargo lines into
calls in memory and are never returned: the output carries an anonymous `call_id`, the commodity, the three dates and
tonnes. Calls are (vessel, arrival date), as PPA counts "distinct visits" (STATUS.md PPA findings).
Row dates are M/D/YYYY with no time of day; the header range is D/M/YYYY (S0 PPA probe).
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

COMMODITIES = ["Containers", "Copper Concentrates", "General", "Hydrocarbon", "Iron Ore", "Manganese Ore", "Salt",
               "Spodumene Concentrate", "Chemical Compound", "Livestock", "Chromite", "Lithium"]
_D = r"\d{1,2}/\d{1,2}/\d{4}"
_N = r"[\d,]+\.\d\d"
ROW_RE = re.compile(rf"^(?P<name>.+?)\s+(?P<arr>{_D})\s+(?P<dep>{_D})\s+(?P<cc>{_D})\s+"
                    rf"(?P<imp>{_N})\s+(?P<exp>{_N})\s+{_N}\s+{_N}$")
GROUP_RE = re.compile(rf"^({'|'.join(map(re.escape, COMMODITIES))})\b(?!.*{_D})")
HEADER_RE = re.compile(r"Cargo Complete date:\s*(\d{2})/(\d{2})/(\d{4})\s+to\s+(\d{2})/(\d{2})/(\d{4})", re.I)


class PpaFormatError(ValueError):
    pass


def parse_lines(lines: list[tuple[str, str]]) -> tuple[pd.DataFrame, tuple[int, int]]:
    """(vessel-column text, full line text) per line of one commodity file -> (cargo lines without vessel identity,
    (year, month) from the header). The call key is (vessel column, arrival date); the destination/origin country
    column is excluded, since one call can ship to several countries on separate lines."""
    month, group, rows, ids = None, None, [], {}
    for vessel, line in lines:
        line = line.strip()
        if month is None and (h := HEADER_RE.search(line)):
            if (h.group(2), h.group(3)) != (h.group(5), h.group(6)):
                raise PpaFormatError(f"header spans more than one month: {line!r}")
            month = (int(h.group(3)), int(h.group(2)))
            continue
        if m := ROW_RE.match(line):
            if group is None:
                raise PpaFormatError(f"cargo line before any commodity heading: dates {m['arr']} {m['dep']}")
            key = (vessel.strip(), m["arr"])
            ids.setdefault(key, len(ids))
            rows.append({"call_id": ids[key], "commodity": group,
                         "arrival": pd.to_datetime(m["arr"], format="%m/%d/%Y"),
                         "departure": pd.to_datetime(m["dep"], format="%m/%d/%Y"),
                         "cargo_complete": pd.to_datetime(m["cc"], format="%m/%d/%Y"),
                         "import_t": float(m["imp"].replace(",", "")), "export_t": float(m["exp"].replace(",", ""))})
            continue
        if g := GROUP_RE.match(line):
            group = g.group(1)
    if month is None:
        raise PpaFormatError("no 'Cargo Complete date: dd/mm/yyyy to dd/mm/yyyy' header found")
    return pd.DataFrame(rows), month


def read_commodity_pdf(path: Path) -> pd.DataFrame:
    """Cargo lines of one monthly file, with `file_month` (YYYY-MM from the header). No vessel identity."""
    import pdfplumber

    lines = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
            col = [w["x0"] for w in words if w["text"].startswith("Destination/Origin")]
            if not col:
                raise PpaFormatError(f"{Path(path).name} p{page.page_number}: no 'Destination/Origin' column header")
            split = min(col) - 1.0
            rows: dict[int, list] = {}
            for w in words:                                     # cluster words into lines by top (4 pt, as S0 probe)
                k = next((r for r in rows if abs(r - w["top"]) <= 4), round(w["top"]))
                rows.setdefault(k, []).append(w)
            for k in sorted(rows):
                ws = sorted(rows[k], key=lambda w: w["x0"])
                lines.append((" ".join(w["text"] for w in ws if w["x0"] < split),
                              " ".join(w["text"] for w in ws)))
    df, (y, m) = parse_lines(lines)
    cc = df.cargo_complete
    if ((cc.dt.year != y) | (cc.dt.month != m)).any():
        raise PpaFormatError(f"{Path(path).name}: cargo-complete dates outside {y}-{m:02d}")
    return df.assign(file_month=f"{y}-{m:02d}")


def calls(lines: pd.DataFrame) -> pd.DataFrame:
    """One row per PPA call: dates, total export tonnes, iron-ore export tonnes, commodities."""
    g = lines.groupby(["file_month", "call_id"])
    out = g.agg(arrival=("arrival", "first"), departure=("departure", "first"), cargo_complete=("cargo_complete", "first"),
                n_lines=("export_t", "size"), export_t=("export_t", "sum"),
                commodities=("commodity", lambda s: ";".join(sorted(set(s)))))
    out["iron_ore_t"] = lines[lines.commodity == "Iron Ore"].groupby(["file_month", "call_id"]).export_t.sum()
    out["iron_ore_t"] = out.iron_ore_t.fillna(0.0)
    if (g[["arrival", "departure", "cargo_complete"]].nunique() > 1).any(axis=None):
        raise PpaFormatError("a (vessel, arrival) call has lines with different dates")
    return out.reset_index()
