"""Self-checks for the synthetic harness only (tests/synthetic.py). No pipeline code is tested here.
They pin the generator to the real AMSA schema measured in S0 so load_amsa is tested against realistic input."""
import re

import numpy as np
import pandas as pd
import pyogrio

import synthetic

TS_RE = re.compile(r"^\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2} (AM|PM)$")


def _ts(df):
    return pd.to_datetime(df.timestamp.str.slice(0, 19), format="%d/%m/%Y %H:%M:%S")


def test_schema_matches_real_amsa():
    df = synthetic.all_rows()
    assert list(df.columns) == synthetic.REAL_FIELDS
    assert all(df[c].dtype == np.float64 for c in synthetic.FLOAT_FIELDS)


def test_timestamp_format_and_suffix_agrees_with_hour():
    df = synthetic.all_rows()
    assert df.timestamp.str.match(TS_RE).all()
    hour = df.timestamp.str.slice(11, 13).astype(int)
    assert ((hour >= 12) == (df.timestamp.str[-2:] == "PM")).all()


def test_ping_interval_close_to_real():
    df = synthetic.all_rows(shuffle=False)
    dt = df.assign(t=_ts(df)).groupby("craft_id").t.diff().dt.total_seconds().dropna() / 60
    dt = dt[dt < 60]                     # exclude the deliberate gap
    assert 14.0 <= dt.median() <= 16.0
    assert dt.min() >= 9.0 and dt.max() <= 21.0


def test_deterministic():
    a, b = synthetic.all_rows(), synthetic.all_rows()
    pd.testing.assert_frame_equal(a, b)


def test_docs_must_fail_cases_all_present():
    t = synthetic.truth_table()
    assert set(t.docs_case.dropna().astype(int)) == {1, 2, 3, 4, 5}
    assert not t.loc[t.must_fail, "expected_laden_departures"].fillna(0).astype(int).any()


def test_ais_gap_scenario_has_gap_at_crossing():
    df, _ = synthetic.scenarios()["ais_gap_at_crossing"]
    gaps = _ts(df).diff().dt.total_seconds() / 3600
    assert gaps.max() >= synthetic.GAP_AT_CROSSING_H - 0.5


def test_laden_call_dwells_inside_loader(world):
    df, _ = synthetic.scenarios()["laden_call"]
    pts = synthetic._to_metric.transform(df.longitude.to_numpy(), df.latitude.to_numpy())
    loader = world["berths"].set_index("name").geometry["SYN_LOADER_1"].buffer(50)
    import shapely
    inside = shapely.contains_xy(loader, *pts)
    hours = inside.sum() * 15 / 60
    assert hours > synthetic.LONG_DWELL_H * 0.8


def test_month_files_roundtrip(tmp_path):
    df = synthetic.all_rows()
    paths = synthetic.write_month_files(df, tmp_path)
    assert set(paths) == {"2026-07", "2026-08"}
    back = pd.concat([pyogrio.read_dataframe(p, read_geometry=False) for p in paths.values()], ignore_index=True)
    assert list(back.columns) == synthetic.REAL_FIELDS
    assert len(back) == len(df)
    cid = synthetic.scenarios()["month_boundary_call"][1].craft_id
    for p in paths.values():
        assert (pyogrio.read_dataframe(p, read_geometry=False).craft_id == cid).any()


def _outside_spells(df):
    """For each outside run between two inside pings: the inside-to-inside gap in hours (the quantity a
    fragment-merge rule with gap G compares against) and the number of outside pings in the run."""
    df = df.assign(t=_ts(df), ins=synthetic.inside_port_limit(df)).sort_values("t").reset_index(drop=True)
    first_in, last_in = df.index[df.ins].min(), df.index[df.ins].max()
    mid = df.loc[first_in:last_in]
    run = (mid.ins != mid.ins.shift()).cumsum()
    spans, counts = [], []
    for _, g in mid[~mid.ins].groupby(run[~mid.ins]):
        spans.append((df.t[g.index[-1] + 1] - df.t[g.index[0] - 1]).total_seconds() / 3600)
        counts.append(len(g))
    return spans, counts


def test_boundary_chatter_crosses_repeatedly_with_short_outside_spells():
    df, truth = synthetic.scenarios()["boundary_chatter"]
    spans, counts = _outside_spells(df)
    assert len(spans) >= synthetic.CHATTER_CROSSINGS            # several in/out alternations
    assert max(spans) < 1.0 and min(counts) >= 1                 # gaps below the assumed G, each observed
    assert truth.expected_calls == 1 and truth.expected_laden_departures == 1


def test_long_stay_never_at_a_berth_and_lasts_days(world):
    df, truth = synthetic.scenarios()["long_stay_near_boundary"]
    import shapely
    x, y = synthetic._to_metric.transform(df.longitude.to_numpy(), df.latitude.to_numpy())
    near_berth = shapely.contains_xy(world["berths"].geometry.buffer(500).union_all(), x, y)
    assert not near_berth.any()
    spans, _ = _outside_spells(df)
    t, ins = _ts(df), synthetic.inside_port_limit(df)
    assert (t[ins].max() - t[ins].min()).total_seconds() / 3600 >= synthetic.LONG_STAY_DAYS * 24 - 12
    assert len(spans) >= 2 and truth.must_fail and truth.expected_laden_departures == 0


def test_edge_rows_cover_cases():
    e = synthetic.edge_rows()
    assert e.type.isna().any() and (e.length == 0).any() and (e.draught == 0).any()
    assert (e.craft_id < 0).any() and e.duplicated().any()
    assert not _ts(e).is_monotonic_increasing
