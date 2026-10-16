"""match: date-key groups, variant choice, group-level calibration and evaluation. Synthetic frames only."""
import numpy as np
import pandas as pd
import pytest

from pilbara_oreflow.config import load_config
from pilbara_oreflow.match import ais_side, calibrate, choose_variant, evaluate, monthly_totals, ppa_side
from pilbara_oreflow.tonnage import displacement_term, predict

TRUE = {"small": (0.70, 3000.0), "cape": (0.80, 5000.0), "vloc": (0.82, 6000.0)}


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def _world(cfg, n_days=40, per_day=3, seed=1):
    """AIS laden departures and the PPA calls they produce; arrival 2 days before, exit 6 h after loading (AWST)."""
    rng = np.random.default_rng(seed)
    rows, ppa = [], []
    for d in range(n_days):
        for k in range(per_day):
            cls = rng.choice(["small", "cape", "vloc"], p=[0.15, 0.7, 0.15])
            L = {"small": 220, "cape": 292, "vloc": 340}[cls]
            done = pd.Timestamp("2026-06-01 10:00", tz="Australia/Perth") + pd.Timedelta(days=d, hours=int(rng.integers(0, 10)))
            r = dict(craft_id=float(len(rows)), size_class=cls, length_m=L, beam_m=L / 6.5,
                     draught_out_m=rng.uniform(14, 18), usable=True, laden_departure=True,
                     final_dwell_berth="PH 4" if len(rows) % 25 == 0 else "A",
                     t_in=(done - pd.Timedelta(days=2)).tz_convert("UTC"), final_dwell_end=done.tz_convert("UTC"),
                     t_exit=(done + pd.Timedelta(hours=6)).tz_convert("UTC"))
            rows.append(r)
    ais = pd.DataFrame(rows)
    x = displacement_term(ais, cfg)
    cargo = [TRUE[c][0] * xi - TRUE[c][1] for c, xi in zip(ais.size_class, x)]
    for i, r in ais.iterrows():
        loc = lambda t: t.tz_convert("Australia/Perth").tz_localize(None).normalize()
        com = "Manganese Ore" if r.final_dwell_berth == "PH 4" else "Iron Ore"
        ppa.append(dict(file_month=loc(r.final_dwell_end).strftime("%Y-%m"), call_id=i, commodity=com,
                        arrival=loc(r.t_in), departure=loc(r.t_exit), cargo_complete=loc(r.final_dwell_end),
                        import_t=0.0, export_t=cargo[i]))
    ppa.append(dict(file_month="2026-06", call_id=999, commodity="Salt", arrival=pd.Timestamp("2026-06-02"),
                    departure=pd.Timestamp("2026-06-04"), cargo_complete=pd.Timestamp("2026-06-03"),
                    import_t=0.0, export_t=50000.0))                       # not a loader commodity: dropped (A1)
    return ais, pd.DataFrame(ppa), pd.Series(cargo, index=ais.index)


def test_ppa_side_drops_non_loader_commodities(cfg):
    _, lines, _ = _world(cfg)
    p = ppa_side(lines)
    assert 999 not in set(p.call_id) and (p.loader_t > 0).all()


def test_variant_choice_uses_counts_and_prefers_awst(cfg):
    ais, lines, _ = _world(cfg)
    best, table = choose_variant(ais_side(ais), ppa_side(lines))
    assert best in ("K1", "K2", "K3") and table.loc[best, "share"] == 1.0


def test_calibrate_recovers_parameters_and_ph4_share(cfg):
    ais, lines, _ = _world(cfg)
    a, p = ais_side(ais), ppa_side(lines)
    cal = calibrate(a, p, "K3", cfg)
    for c, (ta, tb) in TRUE.items():
        assert cal["params"][c]["a"] == pytest.approx(ta, rel=1e-6) and cal["params"][c]["b"] == pytest.approx(tb, rel=1e-3)
    assert cal["ph4_iron_share"] == 0.0                                    # synthetic PH4 calls ship manganese


def test_unbalanced_group_left_out(cfg):
    ais, lines, _ = _world(cfg)
    a, p = ais_side(ais), ppa_side(lines)
    cal_full = calibrate(a, p, "K3", cfg)["diagnostics"]["balanced_groups"]
    cal_drop = calibrate(a.iloc[1:], p, "K3", cfg)["diagnostics"]["balanced_groups"]   # one AIS call missing
    assert cal_drop == cal_full - 1


def test_evaluate_zero_error_when_model_is_true(cfg):
    ais, lines, cargo = _world(cfg)
    a, p = ais_side(ais), ppa_side(lines)
    cal = calibrate(a, p, "K3", cfg)
    pred = predict(a, cal["params"], cfg)
    tot = monthly_totals(a, pred, pred, ph4_share=1.0)
    truth = pd.Series(cargo.groupby(a.month).sum())
    e = evaluate(tot, truth, ["2026-06"])
    assert e.loc["2026-06", "model_err"] == pytest.approx(0.0, abs=1e-9)
