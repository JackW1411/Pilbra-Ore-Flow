"""S3 held-out evaluation (docs/preregistration.md §5; A3 primary, original K5 alongside).

Uses only: frozen calibration (scripts/s2/output/calibration.json), the per-call CSV of the Mar-Aug run, and PPA
monthly iron-ore totals (scripts/s3/output/ppa_monthly_totals.txt). Held-out months: Mar, Apr, May, Aug 2026.

    PYTHONPATH=src python scripts/s3/evaluate.py      -> scripts/s3/output/evaluate.txt
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from pilbara_oreflow import match, tonnage  # noqa: E402
from pilbara_oreflow.config import data_root, load_config  # noqa: E402

HELD_OUT = ["2026-03", "2026-04", "2026-05", "2026-08"]
RUN = "2026-03_2026-04_2026-05_2026-06_2026-07_2026-08"
OUT = ROOT / "scripts" / "s3" / "output" / "evaluate.txt"


def ppa_totals() -> pd.Series:
    rows = [l.split() for l in (ROOT / "scripts/s3/output/ppa_monthly_totals.txt").read_text().splitlines()
            if re.match(r"^\d{4}-\d{2}\s", l)]
    return pd.Series({r[0]: float(r[3]) for r in rows})


def main():
    cfg = load_config()
    cal = json.loads((ROOT / "scripts/s2/output/calibration.json").read_text())
    calls = pd.read_csv(data_root(cfg) / "out" / RUN / "calls.csv",
                        parse_dates=["t_in", "t_out", "t_exit", "final_dwell_end"])
    calls = tonnage.flag_calls(calls, cfg)               # recompute flags with the frozen thresholds
    ais = match.ais_side(calls, cfg["aggregation"]["timezone"])
    ppa = ppa_totals()
    out = [f"run {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}; held-out {HELD_OUT}; calls out/{RUN}/calls.csv; "
           f"calibration scripts/s2/output/calibration.json (primary {cal['primary']})"]

    no_light = ais.laden_departure & ~ais[["no_draught", "static_draught", "ais_gap", "implausible"]].any(axis=1)
    cov = ais.groupby("month").agg(laden=("usable", "size"), usable=("usable", "sum"))
    cov["coverage"] = cov.usable / cov.laden
    cov["coverage_excl_light"] = no_light.groupby(ais.month).sum() / cov.laden
    out.append("[E1] coverage on laden departures by month:\n" + cov.reindex(HELD_OUT).round(4).to_string())

    res = {}
    for label in ("a3", "original"):
        c = cal[label]
        pred = tonnage.predict(ais, c["params"], cfg)
        base = tonnage.baseline(ais, c["means"])
        tot = match.monthly_totals(ais, pred, base, c["ph4_iron_share"])
        e = match.evaluate(tot, ppa, HELD_OUT)
        res[label] = e
        out.append(f"[E2] {label} ({c['variant']}){' PRIMARY' if label == cal['primary'] else ''}:\n"
                   + e[["laden_departures", "usable", "ph4", "unestimated", "model_t", "baseline_t", "ppa_iron_ore_t",
                        "model_err", "baseline_err", "coverage"]].round(4).to_string())

    p = res[cal["primary"]].loc["mean"]
    cov_min = cov.reindex(HELD_OUT).coverage.min()
    kill = {"coverage_lt_60pct": bool(cov_min < 0.60), "monthly_error_gt_10pct": bool(p.model_err > 0.10),
            "fails_to_beat_baseline": bool(p.model_err >= p.baseline_err)}
    out.append(f"[E3] kill criteria on PRIMARY ({cal['primary']}): min held-out coverage {cov_min:.3f}; mean model err "
               f"{p.model_err:.4f}; mean baseline err {p.baseline_err:.4f}; " + json.dumps(kill))
    o = res["original"].loc["mean"]
    out.append(f"[E4] original (K5) for comparison: mean model err {o.model_err:.4f}, baseline {o.baseline_err:.4f}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
