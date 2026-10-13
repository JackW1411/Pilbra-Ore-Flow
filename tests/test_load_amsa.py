"""load_amsa against docs/load_amsa_contract.md. Synthetic data only."""
import geopandas as gpd
import pandas as pd
import pytest

import synthetic
from pilbara_oreflow.load_amsa import FIELDS, AmsaFormatError, find_files, load_amsa


def _write(df, path, crs="EPSG:4326"):
    path.parent.mkdir(parents=True, exist_ok=True)
    g = gpd.GeoDataFrame(df.copy(), geometry=gpd.points_from_xy(df.longitude, df.latitude), crs=crs)
    g.to_file(path, driver="ESRI Shapefile", engine="pyogrio")
    return path


# ---------------------------------------------------------------- returns (R1-R7)
def test_columns_dtypes_and_provenance(amsa_edge_shapefile):
    df = load_amsa(amsa_edge_shapefile)
    assert list(df.columns) == FIELDS + ["timestamp_utc", "source_file"]                     # R1, R7
    assert all(df[c].dtype == "float64" for c in ["craft_id", "longitude", "length", "draught"])  # R2, R4
    assert df["type"].dtype == "string" and df["type"].isna().sum() == 1                     # R2 missing TYPE kept
    assert str(df.timestamp_utc.dtype) == "datetime64[ns, UTC]" or str(df.timestamp_utc.dtype).endswith(", UTC]")  # R3
    assert (df.source_file == "ct_nw_08_2026_pt.shp").all()
    assert not isinstance(df, gpd.GeoDataFrame)                                               # R6


def test_timestamp_24h_with_suffix_parsed_exactly(amsa_edge_shapefile):
    df = load_amsa(amsa_edge_shapefile)
    got = dict(zip(df.timestamp, df.timestamp_utc.dt.strftime("%Y-%m-%d %H:%M:%S")))
    assert got["15/08/2026 19:17:06 PM"] == "2026-08-15 19:17:06"
    assert got["15/08/2026 12:00:00 PM"] == "2026-08-15 12:00:00"
    assert got["01/08/2026 00:00:05 AM"] == "2026-08-01 00:00:05"
    assert df.timestamp.notna().all()                                                         # raw string kept


def test_file_order_kept_and_not_cleaned(amsa_edge_shapefile, amsa_edge_rows):
    df = load_amsa(amsa_edge_shapefile)
    assert df.timestamp.tolist() == amsa_edge_rows.timestamp.tolist()                         # R7: no sorting
    assert (df.length == 0).any() and (df.draught == 0).any()                                 # section 3: zeros stay
    assert (df.craft_id < 0).any()


def test_exact_duplicates_kept_and_counted(amsa_edge_shapefile):
    df = load_amsa(amsa_edge_shapefile)
    assert df.duplicated(subset=FIELDS).sum() == 1                                            # X1: kept
    assert df.attrs["report"]["exact_duplicate_rows"] == 1


def test_extra_column_raises(tmp_path, amsa_edge_rows):
    p = _write(amsa_edge_rows.assign(heading=511.0), tmp_path / "ct_nw_08_2026_pt.shp")
    with pytest.raises(AmsaFormatError, match="unexpected columns.*heading"):                 # R5
        load_amsa(p)


# ---------------------------------------------------------------- raises (E0-E6)
def test_error_type_is_value_error():
    assert issubclass(AmsaFormatError, ValueError)                                            # E0


def test_unparsed_timestamp_raises(tmp_path, amsa_edge_rows):
    rows = amsa_edge_rows.copy()
    rows.loc[0, "timestamp"] = "2026-08-15T10:00:00Z"
    p = _write(rows, tmp_path / "ct_nw_08_2026_pt.shp")
    with pytest.raises(AmsaFormatError, match="1 unparsed timestamps.*2026-08-15T10:00:00Z"):  # E1
        load_amsa(p)


def test_twelve_hour_reading_would_be_wrong_but_is_not_used(amsa_edge_shapefile):
    # The metadata's 12-hour format would reject '19:17:06 PM'; load_amsa must accept it (S0 P2 trap).
    assert pd.isna(pd.to_datetime("15/08/2026 19:17:06 PM", format="%d/%m/%Y %I:%M:%S %p", errors="coerce"))
    assert len(load_amsa(amsa_edge_shapefile)) == 10


def test_fractional_seconds_parsed_at_full_precision(tmp_path):
    p = _write(synthetic.fractional_seconds_row(), tmp_path / "ct_nw_08_2026_pt.shp")
    df = load_amsa(p)
    assert df.timestamp_utc.iloc[0] == pd.Timestamp("2026-08-15 15:15:00.555", tz="UTC")       # E1 amendment
    assert df.attrs["report"]["fractional_second_timestamps"] == 1


def test_contradictory_suffix_raises(tmp_path, amsa_conflicting_suffix_row):
    p = _write(amsa_conflicting_suffix_row, tmp_path / "ct_nw_08_2026_pt.shp")
    with pytest.raises(AmsaFormatError, match="contradicts.*13:00:00 AM"):                    # E2
        load_amsa(p)


def test_missing_column_raises(tmp_path, amsa_edge_rows):
    p = _write(amsa_edge_rows.drop(columns="draught"), tmp_path / "ct_nw_08_2026_pt.shp")
    with pytest.raises(AmsaFormatError, match=r"missing columns \['draught'\]"):              # E3
        load_amsa(p)


def test_header_drift_between_files_raises(tmp_path, amsa_edge_rows):
    a = _write(amsa_edge_rows, tmp_path / "a" / "ct_nw_08_2026_pt.shp")
    b_rows = amsa_edge_rows.copy()
    b_rows["timestamp"] = b_rows.timestamp.str.replace("/08/", "/10/")   # October has 31 days
    b_rows["type"] = 1.0                                                                      # dtype drift
    b = _write(b_rows, tmp_path / "b" / "ct_nw_10_2026_pt.shp")
    with pytest.raises(AmsaFormatError, match="header drift"):                                # E4
        load_amsa([a, b])


def test_wrong_crs_raises(tmp_path, amsa_edge_rows):
    p = _write(amsa_edge_rows, tmp_path / "ct_nw_08_2026_pt.shp", crs="EPSG:4283")
    with pytest.raises(AmsaFormatError, match="CRS"):                                         # E5
        load_amsa(p)


def test_non_numeric_in_numeric_field_raises(tmp_path, amsa_edge_rows):
    rows = amsa_edge_rows.copy().astype({"draught": "object"})
    rows.loc[0, "draught"] = "n/a"
    p = _write(rows, tmp_path / "ct_nw_08_2026_pt.shp")
    with pytest.raises(AmsaFormatError, match="non-numeric values in 'draught'"):             # E6
        load_amsa(p)


# ---------------------------------------------------------------- edge cases (X2-X6)
def test_row_outside_file_month_raises(tmp_path, amsa_edge_rows):
    p = _write(amsa_edge_rows, tmp_path / "ct_nw_07_2026_pt.shp")                              # August rows, July name
    with pytest.raises(AmsaFormatError, match="outside 2026-07"):                              # X2
        load_amsa(p)


def test_month_files_concatenate_and_keep_straddling_call(amsa_month_files, all_rows):
    df = load_amsa([amsa_month_files["2026-07"], amsa_month_files["2026-08"]])                 # X3
    assert len(df) == len(all_rows)
    cid = synthetic.scenarios()["month_boundary_call"][1].craft_id
    assert set(df.loc[df.craft_id == cid, "source_file"]) == {"ct_nw_07_2026_pt.shp", "ct_nw_08_2026_pt.shp"}


def test_zero_row_file_returns_typed_empty_frame(tmp_path, amsa_edge_rows):
    p = _write(amsa_edge_rows.iloc[:0], tmp_path / "ct_nw_08_2026_pt.shp")
    with pytest.warns(UserWarning, match="zero rows"):                                         # X4
        df = load_amsa(p)
    assert len(df) == 0 and list(df.columns) == FIELDS + ["timestamp_utc", "source_file"]
    assert df.craft_id.dtype == "float64"


def test_find_files_uses_real_prefix_and_month_order(amsa_month_files):
    root = amsa_month_files["2026-07"].parents[3]
    found = find_files(root)                                                                   # X6
    assert [p.name for p in found] == ["ct_nw_07_2026_pt.shp", "ct_nw_08_2026_pt.shp"]


def test_unrecognised_file_name_raises(tmp_path, amsa_edge_rows):
    p = _write(amsa_edge_rows, tmp_path / "cts_nw_08_2026_pt.shp")                             # metadata's wrong prefix
    with pytest.raises(AmsaFormatError, match="file name"):
        load_amsa(p)
