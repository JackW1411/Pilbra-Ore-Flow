"""clean and calls against the synthetic scenarios (tests/synthetic.py Truth records)."""
import numpy as np
import pandas as pd
import pytest

import synthetic
from pilbara_oreflow.calls import build_calls
from pilbara_oreflow.clean import clean, type_class
from pilbara_oreflow.config import load_config
from pilbara_oreflow.load_amsa import load_amsa


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def pipeline(amsa_month_files, world, cfg):
    raw = load_amsa([amsa_month_files["2026-07"], amsa_month_files["2026-08"]])
    pings, vessels, report = clean(raw, cfg)
    port_limit = world["port_limit"].geometry.iloc[0]
    calls = build_calls(pings, vessels, port_limit, world["berths"], cfg)
    return pings, vessels, report, calls


def _calls_for(calls, name):
    return calls[calls.craft_id == synthetic.scenarios()[name][1].craft_id]


# ---------------------------------------------------------------- config inside the harness's assumed ranges
def test_call_parameters_inside_synthetic_assumed_ranges(cfg):
    c = cfg["calls"]
    assert synthetic.SHORT_DWELL_H < c["d_min_h"] < synthetic.LONG_DWELL_H
    assert c["t_max_h"] > 1.5
    assert synthetic.REENTRY_AFTER_H < c["reentry_x_h"] <= 6
    assert c["merge_gap_h"] > 1.0
    assert 0.3 < c["sog_stationary_kn"] < 5
    assert c["crossing_gap_min"] < synthetic.GAP_AT_CROSSING_H * 60


# ---------------------------------------------------------------- clean
def test_type_class_mapping():
    assert type_class("Cargo ship - All") == "cargo" and type_class("Tanker - All") == "tanker"
    assert type_class("Tug") == "other" and type_class(None) == "unknown" and type_class("unknown code 0") == "unknown"


def test_clean_draught_status_and_no_silent_zero(cfg, amsa_edge_rows):
    rows = amsa_edge_rows.assign(timestamp_utc=pd.to_datetime(amsa_edge_rows.timestamp.str.slice(0, 19),
                                                               format="%d/%m/%Y %H:%M:%S").dt.tz_localize("UTC"))
    rows.loc[1, "draught"] = 25.5
    p, v, rep = clean(rows, cfg)
    assert rep["exact_duplicates_dropped"] == 1
    zero = p[p.draught == 0]
    assert (zero.draught_status == "zero").all() and zero.draught_m.isna().all()       # never a measured 0
    code = p[p.draught == 25.5]
    assert (code.draught_status == "code_max").all() and code.draught_m.isna().all()   # C3
    assert (zero.draught == 0).all() and (code.draught == 25.5).all()                  # raw value kept beside
    assert p.groupby("craft_id").timestamp_utc.apply(lambda s: s.is_monotonic_increasing).all()


def test_clean_same_key_keeps_first(cfg, amsa_edge_rows):
    rows = amsa_edge_rows.assign(timestamp_utc=pd.to_datetime(amsa_edge_rows.timestamp.str.slice(0, 19),
                                                               format="%d/%m/%Y %H:%M:%S").dt.tz_localize("UTC"))
    twin = rows.iloc[[0]].assign(speed=9.9)                       # same craft_id + time, different value
    p, _, rep = clean(pd.concat([rows, twin], ignore_index=True), cfg)
    assert rep["same_key_rows_dropped"] == 1
    k = p[(p.craft_id == rows.craft_id.iloc[0]) & (p.timestamp == rows.timestamp.iloc[0])]
    assert len(k) == 1 and k.speed.iloc[0] == rows.speed.iloc[0]


def test_vessel_attributes(pipeline):
    _, v, _, _ = pipeline
    s = synthetic.scenarios()
    assert v.loc[s["missing_dimensions"][1].craft_id, "ineligible_reason"] == "unclassified_size"
    assert v.loc[s["tug_at_loader"][1].craft_id, "ineligible_reason"] == "not_cargo_type"
    assert v.loc[s["laden_call"][1].craft_id, "size_class"] == "cape" and v.loc[s["laden_call"][1].craft_id, "eligible"]


def test_implausible_dimensions_unclassified(cfg, amsa_edge_rows):
    rows = amsa_edge_rows.assign(timestamp_utc=pd.Timestamp("2026-08-10", tz="UTC") + pd.to_timedelta(range(10), "min"))
    rows["length"] = 708.0                                        # F3: seen in real data
    _, v, _ = clean(rows, cfg)
    assert v.unclassified_size.all() and v.length_m.isna().all()


# ---------------------------------------------------------------- calls vs truths
@pytest.mark.parametrize("name", [n for n, (_, t) in synthetic.scenarios().items()
                                  if t.expected_laden_departures is not None])
def test_laden_departures_match_truth(pipeline, name):
    calls = _calls_for(pipeline[3], name)
    truth = synthetic.scenarios()[name][1]
    assert len(calls) >= 1, "scenario produced no call"
    got = int(calls.laden_departure.fillna(False).sum())
    assert got == truth.expected_laden_departures, calls[["reasons", "laden_departure"]].to_string()


def test_must_fail_scenarios_never_laden(pipeline):
    for name, (_, t) in synthetic.scenarios().items():
        if t.must_fail:
            assert not _calls_for(pipeline[3], name).laden_departure.fillna(False).any(), name


def test_ais_gap_call_flagged_not_dropped(pipeline):
    calls = _calls_for(pipeline[3], "ais_gap_at_crossing")
    assert len(calls) == 1 and calls.ais_gap.iloc[0]
    assert calls.gap_out_min.iloc[0] > 60


def test_boundary_chatter_is_one_call(pipeline):
    assert len(_calls_for(pipeline[3], "boundary_chatter")) == synthetic.scenarios()["boundary_chatter"][1].expected_calls


def test_reasons_explain_failures(pipeline):
    calls = pipeline[3]
    assert "no_loader_dwell_ge_dmin" in _calls_for(calls, "ballast_shift_short_dwells").reasons.iloc[0]
    assert "final_dwell_not_loader" in _calls_for(calls, "last_dwell_non_loader").reasons.iloc[0]
    assert "reentry_within_x" in _calls_for(calls, "reentry_after_departure").reasons.iloc[0]
    assert "not_cargo_type" in _calls_for(calls, "tug_at_loader").reasons.iloc[0]


def test_month_file_alone_marks_truncated_call(amsa_month_files, world, cfg):
    raw = load_amsa(amsa_month_files["2026-08"])
    p, v, _ = clean(raw, cfg)
    calls = build_calls(p, v, world["port_limit"].geometry.iloc[0], world["berths"], cfg)
    c = calls[calls.craft_id == synthetic.scenarios()["month_boundary_call"][1].craft_id]
    assert len(c) == 1 and not c.inbound_observed.iloc[0] and "no_inbound_observed" in c.reasons.iloc[0]


def test_departure_draught_from_last_inside_ping(pipeline):
    c = _calls_for(pipeline[3], "laden_call").iloc[0]
    assert c.draught_in_m == pytest.approx(8.6) and c.draught_out_m == pytest.approx(17.6)
    nd = _calls_for(pipeline[3], "no_draught").iloc[0]
    assert np.isnan(nd.draught_out_m) and nd.draught_out_status == "zero"


# ---------------------------------------------------------------- review fixes 2026-10-16
def _aug_only(amsa_month_files, cfg):
    p, v, _ = clean(load_amsa(amsa_month_files["2026-08"]), cfg)
    return p, v


def test_truncated_loader_dwell_is_unknown_not_false(amsa_month_files, world, cfg):
    """Data starts 3 h before a loader dwell ends: dwell < D_min is a lower bound, so laden is <NA>."""
    p, v = _aug_only(amsa_month_files, cfg)
    pl, berths = world["port_limit"].geometry.iloc[0], world["berths"]
    cid = synthetic.scenarios()["month_boundary_call"][1].craft_id
    end = build_calls(p, v, pl, berths, cfg).set_index("craft_id").loc[cid, "final_dwell_end"]
    p2 = p[(p.craft_id != cid) | (p.timestamp_utc >= end - pd.Timedelta(hours=3))].reset_index(drop=True)
    c = build_calls(p2, v, pl, berths, cfg)
    c = c[c.craft_id == cid].iloc[0]
    assert pd.isna(c.laden_departure) and "loader_dwell_truncated" in c.reasons


def test_dwell_excludes_long_ping_gaps(pipeline, world, cfg):
    """Removing the middle of a laden berth dwell must shorten the dwell, not be bridged as dwell time."""
    pings, vessels, _, calls = pipeline
    cid = synthetic.scenarios()["laden_call"][1].craft_id
    c = calls[calls.craft_id == cid].iloc[0]
    end = c.final_dwell_end
    hole = (pings.craft_id == cid) & pings.timestamp_utc.between(end - pd.Timedelta(hours=c.loader_dwell_h - 1),
                                                               end - pd.Timedelta(hours=1))
    c2 = build_calls(pings[~hole].reset_index(drop=True), vessels, world["port_limit"].geometry.iloc[0],
                     world["berths"], cfg)
    c2 = c2[c2.craft_id == cid].iloc[0]
    assert c2.loader_dwell_h < cfg["calls"]["d_min_h"] and not c2.laden_departure


def test_ineligible_vessel_is_false_even_if_exit_unobserved(pipeline):
    calls = pipeline[3]
    inel = calls[~calls.eligible]
    assert len(inel) and (inel.laden_departure == False).all()     # noqa: E712  (False, never <NA>)
