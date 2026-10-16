"""ppa parser on hand-made lines (invented vessel names; no real PPA rows)."""
import pandas as pd
import pytest

from pilbara_oreflow.ppa import PpaFormatError, calls, parse_lines

HEAD = [("", "Cargo Complete date: 01/07/2026 to 31/07/2026")]


def _lines():
    return HEAD + [
        ("Iron Ore", "Iron Ore"),
        ("SYN ALPHA", "SYN ALPHA China 7/1/2026 7/3/2026 7/2/2026 0.00 180,000.00 90,000.00 180,000.00"),
        ("SYN ALPHA", "SYN ALPHA Japan 7/1/2026 7/3/2026 7/2/2026 0.00 20,000.00 90,000.00 180,000.00"),
        ("SYN BETA", "SYN BETA China 7/1/2026 7/3/2026 7/2/2026 0.00 150,000.00 80,000.00 160,000.00"),
        ("", "2 Vessels Total 350,000.00"),
        ("Manganese Ore", "Manganese Ore"),
        ("SYN GAMMA", "SYN GAMMA China 7/4/2026 7/6/2026 7/5/2026 0.00 40,000.00 30,000.00 50,000.00"),
    ]


def test_lines_drop_identity_and_keep_dates_tonnes():
    df, month = parse_lines(_lines())
    assert month == (2026, 7)
    assert list(df.columns) == ["call_id", "commodity", "arrival", "departure", "cargo_complete", "import_t", "export_t"]
    assert not df.astype(str).apply(lambda s: s.str.contains("SYN")).any(axis=None)        # no vessel names out
    assert df.arrival.iloc[0] == pd.Timestamp("2026-07-01") and df.cargo_complete.iloc[0] == pd.Timestamp("2026-07-02")


def test_two_countries_are_one_call():
    df, _ = parse_lines(_lines())
    c = calls(df.assign(file_month="2026-07"))
    assert len(c) == 3
    alpha = c[c.n_lines == 2].iloc[0]
    assert alpha.iron_ore_t == 200_000.0 and alpha.export_t == 200_000.0
    assert c[c.commodities == "Manganese Ore"].iron_ore_t.iloc[0] == 0.0


def test_header_missing_or_multi_month_raises():
    with pytest.raises(PpaFormatError, match="header"):
        parse_lines(_lines()[1:])
    with pytest.raises(PpaFormatError, match="more than one month"):
        parse_lines([("", "Cargo Complete date: 01/07/2026 to 31/08/2026")])


def test_cargo_line_before_commodity_heading_raises():
    with pytest.raises(PpaFormatError, match="heading"):
        parse_lines(HEAD + _lines()[2:3])
