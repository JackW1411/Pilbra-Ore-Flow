"""S2 calibration on the pre-registered calibration months (docs/preregistration.md, amendments A1-A3).

Reads the per-call CSV from `pilbara_oreflow.run` and the PPA commodity PDFs for the calibration months only.
Chooses the key variant by counts, then fits baseline class means, the draught model and the PH4 iron share.
Reports in-sample (calibration) group residuals as diagnostics only; no held-out month is read.

    PYTHONPATH=src python scripts/s2/calibrate.py [--run RUN]
Writes scripts/s2/output/calibrate.txt (aggregates only) and DATA_ROOT/interim/calibration.json.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from pilbara_oreflow import match, tonnage  # noqa: E402
from pilbara_oreflow.config import data_root, load_config  # noqa: E402
from pilbara_oreflow.ppa import read_commodity_pdf  # noqa: E402

CAL = ["2026-06", "2026-07"]
RUN = "2026-03_2026-04_2026-05_2026-06_2026-07_2026-08"   # default; override with --run (DATA_ROOT/out/<run>/)
OUT = ROOT / "scripts" / "s2" / "output" / "calibrate.txt"


def main(run: str = RUN):
    cfg = load_config()
    root = data_root(cfg)
    lines = []
    out = [f"run {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}; calibration months {CAL}; calls from out/{run}/calls.csv"]

    calls = pd.read_csv(root / "out" / run / "calls.csv",
                        parse_dates=["t_in", "t_out", "t_exit", "final_dwell_end"])
    ais = match.ais_side(calls, cfg["aggregation"]["timezone"])
    ais_cal = ais[ais.month.isin(CAL)].copy()

    for ym in CAL:
        lines.append(read_commodity_pdf(root / "raw" / "ppa" / f"ppa_commodity_{ym.replace('-', '_')}.pdf"))
    ppa_lines = pd.concat(lines, ignore_index=True)
    ppa_cal = match.ppa_side(ppa_lines)
    out.append(f"[C1] AIS laden departures {len(ais_cal)} (usable {int(ais_cal.usable.sum())}); "
               f"PPA loader-commodity calls {len(ppa_cal)} "
               f"(iron-ore {int((ppa_cal.iron_ore_t > 0).sum())}, non-iron share-weighted "
               f"{((ppa_cal.loader_t - ppa_cal.iron_ore_t) / ppa_cal.loader_t).sum():.2f})")

    _, table = match.choose_variant(ais_cal, ppa_cal)
    out.append("[C2] key variants on calibration months (counts only):\n" + table.to_string())
    chosen = {"original": table.loc[["K1", "K2", "K3", "K4", "K5", "K6"]].share.idxmax(),   # pre-registered list
              "a3": table.share.idxmax()}                                                  # amendment A3 (primary)
    out.append(f"     chosen: original {chosen['original']}, A3 {chosen['a3']}")
    result = {}
    for label, v in chosen.items():
        cal = match.calibrate(ais_cal, ppa_cal, v, cfg)
        result[label] = {k: cal[k] for k in ("variant", "params", "means", "ph4_iron_share", "diagnostics")}
        out.append(f"--- {label} ({v})")
        out.append("[C3] fit diagnostics: " + json.dumps(cal["diagnostics"]))
        out.append("[C4] baseline class means (t): " + json.dumps({k: round(x) for k, x in cal["means"].items()}))
        out.append("[C5] draught model params: " + json.dumps(
            {k: {kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in d.items()}
             for k, d in cal["params"].items()}))
        out.append(f"[C6] PH4 iron-ore share s = {cal['ph4_iron_share']}")
        # In-sample diagnostics: balanced all-usable groups, sum of predictions vs PPA loader tonnes. Not S3.
        ka, kp, t = match.groups(ais_cal, ppa_cal, v)
        a = ais_cal.assign(key=ka.values, pred=tonnage.predict(ais_cal, cal["params"], cfg),
                           base=tonnage.baseline(ais_cal, cal["means"]))
        bal = t.index[t.balanced]
        y = ppa_cal.assign(key=kp.values).groupby("key").loader_t.sum().reindex(bal)
        ok = a[a.key.isin(bal)].groupby("key").usable.all()
        ok = ok.index[ok]
        g = a[a.key.isin(ok)].groupby("key")[["pred", "base"]].sum().join(y)
        rel_m = (g.pred - g.loader_t) / g.loader_t
        rel_b = (g.base - g.loader_t) / g.loader_t
        out.append(f"[C7] IN-SAMPLE group residuals over {len(g)} all-usable balanced groups (diagnostic, not S3): "
                   f"model median |err| {rel_m.abs().median():.3%}, p90 {rel_m.abs().quantile(.9):.3%}, sum err "
                   f"{(g.pred.sum() - g.loader_t.sum()) / g.loader_t.sum():+.3%}; baseline median |err| "
                   f"{rel_b.abs().median():.3%}, p90 {rel_b.abs().quantile(.9):.3%}, sum err "
                   f"{(g.base.sum() - g.loader_t.sum()) / g.loader_t.sum():+.3%}")
        out.append(f"     group sizes: {a[a.key.isin(ok)].groupby('key').size().value_counts().sort_index().to_dict()}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    dest = root / "interim" / "calibration.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({"primary": "a3", **result}, indent=2), encoding="utf-8")
    print("\n".join(out))
    print(f"wrote {OUT} and {dest}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=RUN, help="run directory name under DATA_ROOT/out/")
    np.set_printoptions(suppress=True)
    main(ap.parse_args().run)
