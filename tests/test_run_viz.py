"""run and viz end to end on the synthetic harness. Synthetic data only."""
import json

import pandas as pd
import pytest

from pilbara_oreflow.config import load_config
from pilbara_oreflow.run import run


@pytest.fixture(scope="module")
def outputs(amsa_month_files, world, tmp_path_factory):
    cfg = load_config()
    out = tmp_path_factory.mktemp("out")
    params = {c: {"a": 0.8, "b": 5000.0} for c in cfg["model"]["size_class_names"]}
    means = {"small": 60000.0, "cape": 170000.0, "vloc": 240000.0}
    rep = run([amsa_month_files["2026-07"], amsa_month_files["2026-08"]], world["port_limit"].geometry.iloc[0],
              world["berths"], cfg, out, params, means)
    return out, rep


def test_all_outputs_written(outputs):
    out, _ = outputs
    for f in ("calls.csv", "weekly.csv", "weekly.png", "monthly.csv", "map.html", "report.json"):
        assert (out / f).stat().st_size > 0, f


def test_calls_csv_has_flags_coverage_and_nan_not_zero(outputs):
    out, rep = outputs
    calls = pd.read_csv(out / "calls.csv")
    for col in ("no_draught", "static_draught", "light_departure", "ais_gap", "implausible", "usable", "run_coverage"):
        assert col in calls
    assert calls.loc[~calls.usable, "cargo_t"].isna().all() and not (calls.cargo_t == 0).any()
    assert calls.run_coverage.iloc[0] == pytest.approx(rep["coverage"]["coverage"])


def test_weekly_and_monthly_agree_on_laden_count(outputs):
    out, rep = outputs
    wk, mo = pd.read_csv(out / "weekly.csv"), pd.read_csv(out / "monthly.csv")
    n = rep["coverage"]["laden_departures"]
    assert wk.laden_departures.sum() == mo.laden_departures.sum() == n > 0
    assert (wk.coverage.between(0, 1)).all()


def test_report_records_tonnes_mode(outputs):
    out, _ = outputs
    assert json.loads((out / "report.json").read_text())["tonnes"] == "model+baseline"


def test_counts_only_without_params(amsa_month_files, world, tmp_path):
    rep = run(amsa_month_files["2026-08"], world["port_limit"].geometry.iloc[0], world["berths"], load_config(),
              tmp_path, make_map=False)
    assert rep["tonnes"] == "none" and pd.read_csv(tmp_path / "calls.csv").cargo_t.isna().all()



def test_weekly_marks_partial_edge_weeks():
    from pilbara_oreflow.viz import weekly
    end = pd.to_datetime(["2026-03-01 06:00", "2026-03-10 06:00", "2026-03-31 06:00"], utc=True)  # AWST Sun, Tue, Tue
    calls = pd.DataFrame({"laden_departure": True, "usable": True, "final_dwell_end": end})
    nan = pd.Series(float("nan"), index=calls.index)
    wk = weekly(calls, nan, nan, "Australia/Perth",
                span=(pd.Timestamp("2026-03-01", tz="UTC"), pd.Timestamp("2026-03-31 23:59", tz="UTC")))
    assert wk.partial.tolist() == [True, False, True]           # w/c 23 Feb and 30 Mar run past the data
