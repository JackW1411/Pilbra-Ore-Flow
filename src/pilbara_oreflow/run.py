"""Entry point: AMSA files -> per-call CSV, weekly table + chart, monthly table, Folium map, run report.

Tonnes are produced only when fitted parameters and class means are passed in (fitted on the calibration
period elsewhere); otherwise cargo columns are NaN and the outputs are counts and coverage only.
No PPA data is read here: PPA tonnes are evaluation-only and the AIS-PPA matching rule is not yet registered.

    python -m pilbara_oreflow.run --months 2026-07 2026-08 [--params params.json] [--out DIR]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd

from . import tonnage, viz
from .calls import build_calls, load_berths, load_port_limit
from .clean import clean
from .config import data_root, load_config
from .load_amsa import _file_month, find_files, load_amsa


def run(paths, port_limit, berths: gpd.GeoDataFrame, cfg: dict, out_dir: Path,
        params: dict | None = None, means: dict | None = None, make_map: bool = True) -> dict:
    """Run the pipeline on AMSA files. port_limit and berths in EPSG:7850. Returns the run report."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tz = cfg["aggregation"]["timezone"]

    raw = load_amsa(paths)
    pings, vessels, clean_report = clean(raw, cfg)
    calls = tonnage.flag_calls(build_calls(pings, vessels, port_limit, berths, cfg), cfg)
    if calls.empty:
        raise ValueError("no calls: no vessel was ever inside the port limit")

    cargo = tonnage.predict(calls, params, cfg) if params else pd.Series(float("nan"), index=calls.index)
    base = tonnage.baseline(calls, means) if means else pd.Series(float("nan"), index=calls.index)
    calls["cargo_t"], calls["baseline_t"] = cargo, base
    cov = tonnage.coverage(calls)
    calls["run_coverage"] = cov["coverage"]                       # every output table carries coverage

    calls.to_csv(out_dir / "calls.csv", index=False)
    wk = viz.weekly(calls, cargo, base, tz)
    wk.to_csv(out_dir / "weekly.csv")
    viz.weekly_chart(wk, out_dir / "weekly.png")
    mo = tonnage.monthly(calls, cargo, base, tz)
    mo.to_csv(out_dir / "monthly.csv")
    if make_map:
        pl = gpd.GeoSeries([port_limit], crs=cfg["crs"]["distance"]).to_crs("EPSG:4326")
        viz.call_map(pings, calls, pl, berths.to_crs("EPSG:4326")[["name", "role", "geometry"]]).save(
            out_dir / "map.html")

    report = {"files": [str(p) for p in ([paths] if isinstance(paths, (str, Path)) else paths)],
              "clean": clean_report, "calls": len(calls), "coverage": cov,
              "tonnes": "model+baseline" if params and means else ("model" if params else
                                                                    ("baseline" if means else "none"))}
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--months", nargs="+", required=True, help="YYYY-MM, in the order to load")
    ap.add_argument("--params", type=Path, help="JSON {'params': {...}, 'means': {...}} fitted on calibration months")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    cfg = load_config()
    root = data_root(cfg)
    files = find_files(root / "raw")
    want = {tuple(map(int, m.split("-"))) for m in a.months}
    paths = [f for f in files if _file_month(f) in want]
    if len(paths) != len(want):
        raise SystemExit(f"found {len(paths)} files for {len(want)} months under {root / 'raw'}")
    if "berths" not in cfg:
        raise SystemExit("config has no [berths] section (osm_file, loader_names): see STATUS.md Pending decisions")
    fitted = json.loads(a.params.read_text()) if a.params else {}
    out = a.out or root / "out" / "_".join(a.months)
    rep = run(paths, load_port_limit(cfg), load_berths(cfg), cfg, out, fitted.get("params"), fitted.get("means"))
    print(json.dumps(rep["coverage"], indent=2))
    print(f"outputs in {out}")


if __name__ == "__main__":
    main()
