"""tonnage: flags, NaN-not-0, fit recovery, baseline, monthly fill. Synthetic data only."""
import numpy as np
import pandas as pd
import pytest

import synthetic
from pilbara_oreflow.calls import build_calls
from pilbara_oreflow.clean import clean
from pilbara_oreflow.config import load_config
from pilbara_oreflow.load_amsa import load_amsa
from pilbara_oreflow.tonnage import (FLAGS, baseline, class_means, coverage, displacement_term, fit, flag_calls,
                                     monthly, predict)


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def flagged(amsa_month_files, world, cfg):
    raw = load_amsa([amsa_month_files["2026-07"], amsa_month_files["2026-08"]])
    p, v, _ = clean(raw, cfg)
    calls = build_calls(p, v, world["port_limit"].geometry.iloc[0], world["berths"], cfg)
    return flag_calls(calls, cfg)


def _row(calls, name):
    return calls[calls.craft_id == synthetic.scenarios()[name][1].craft_id]


def test_scenario_flags(flagged):
    assert _row(flagged, "static_draught").static_draught.all()
    assert _row(flagged, "no_draught").no_draught.all()
    assert _row(flagged, "light_departure_candidate").light_departure.all()     # 9.0 m < cape threshold
    assert _row(flagged, "ais_gap_at_crossing").ais_gap.all() or not _row(flagged, "ais_gap_at_crossing").laden_departure.fillna(False).any()
    lc = _row(flagged, "laden_call")
    assert lc.usable.all() and not lc[FLAGS].any(axis=None)


def test_flags_only_on_laden_departures(flagged):
    not_laden = ~flagged.laden_departure.fillna(False).astype(bool)
    assert not flagged.loc[not_laden, FLAGS + ["usable"]].any(axis=None)


def test_flagged_cargo_is_nan_never_zero(flagged, cfg):
    params = {c: {"a": 0.8, "b": 1000.0} for c in cfg["model"]["size_class_names"]}
    cargo = predict(flagged, params, cfg)
    assert cargo[~flagged.usable].isna().all()
    assert (cargo[flagged.usable] > 0).all()
    assert not (cargo == 0).any()


def test_fit_recovers_known_parameters(cfg):
    rng = np.random.default_rng(0)
    n = 60
    calls = pd.DataFrame({
        "size_class": rng.choice(["small", "cape", "vloc"], n),
        "length_m": rng.uniform(180, 330, n), "beam_m": rng.uniform(30, 57, n),
        "draught_out_m": rng.uniform(12, 18.5, n), "usable": True})
    truth = {"small": (0.70, 3000.0), "cape": (0.80, 5000.0), "vloc": (0.82, 6000.0)}
    x = displacement_term(calls, cfg)
    obs = pd.Series([truth[c][0] * xi - truth[c][1] for c, xi in zip(calls.size_class, x)])
    params = fit(calls, obs, cfg, min_n=5)
    for c, (a, b) in truth.items():
        assert params[c]["a"] == pytest.approx(a, rel=1e-6) and params[c]["b"] == pytest.approx(b, rel=1e-4)


def test_fit_pools_sparse_classes(cfg):
    calls = pd.DataFrame({"size_class": ["cape"] * 6 + ["vloc"] * 2, "length_m": 290.0, "beam_m": 45.0,
                          "draught_out_m": np.linspace(12, 18, 8), "usable": True})
    obs = displacement_term(calls, cfg) * 0.8 - 5000
    params = fit(calls, obs, cfg, min_n=5)
    assert params["vloc"]["pooled"] and not params["cape"]["pooled"]
    assert params["small"]["n"] == 0 and params["small"]["pooled"]


def test_baseline_ignores_draught_and_monthly_fill(flagged, cfg):
    means = {"small": 60000.0, "cape": 170000.0, "vloc": 240000.0}
    base = baseline(flagged, means)
    laden = flagged.laden_departure.fillna(False).astype(bool)
    assert base[laden].notna().all() and base[~laden].isna().all()
    params = {c: {"a": 0.8, "b": 0.0} for c in means}
    m = monthly(flagged, predict(flagged, params, cfg), base, "Australia/Perth")
    flagged_laden = int((laden & ~flagged.usable).sum())
    assert m.laden_departures.sum() == laden.sum()
    assert m.fill_t.sum() == pytest.approx(base[laden & ~flagged.usable].sum())
    assert flagged_laden > 0 and (m.coverage <= 1).all()


def test_class_means_and_coverage(flagged):
    obs = pd.Series(150000.0, index=flagged.index)
    assert class_means(flagged, obs) == {"cape": 150000.0}
    cov = coverage(flagged)
    assert cov["laden_departures"] >= cov["usable"] >= 1 and set(cov["flag_counts"]) == set(FLAGS)


def test_monthly_counts_unestimated_instead_of_summing_zero(flagged, cfg):
    """A laden class with no class mean and no usable prediction is counted, not silently dropped."""
    laden = flagged.laden_departure.fillna(False).astype(bool)
    means = {"small": 60000.0, "vloc": 240000.0}                   # no 'cape' mean
    base = baseline(flagged, means)
    m = monthly(flagged, predict(flagged, {c: {"a": 0.8, "b": 0.0} for c in means}, cfg), base, "Australia/Perth")
    cape = laden & (flagged.size_class == "cape")
    assert m.baseline_missing.sum() == cape.sum() > 0
    assert m.unestimated.sum() == cape.sum()


def test_monthly_uses_final_dwell_end_month(flagged, cfg):
    base = baseline(flagged, {"small": 1.0, "cape": 1.0, "vloc": 1.0})
    m = monthly(flagged, base * 0, base, "Australia/Perth")
    laden = flagged.laden_departure.fillna(False).astype(bool)
    want = flagged.final_dwell_end[laden].dt.tz_convert("Australia/Perth").dt.strftime("%Y-%m").value_counts()
    assert m.laden_departures.sort_index().to_dict() == want.sort_index().to_dict()
