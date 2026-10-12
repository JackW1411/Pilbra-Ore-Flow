"""Shared S1 fixtures. Synthetic data only (tests/synthetic.py); no real AMSA, PPA or boundary data."""
import pytest

import synthetic


@pytest.fixture(scope="session")
def world():
    """Synthetic port limit and berth polygons (EPSG:7850). Invented geometry, not a real port."""
    return synthetic.world()


@pytest.fixture(scope="session")
def scenarios():
    """{name: (rows in raw AMSA schema, Truth)} for each designed scenario."""
    return synthetic.scenarios()


@pytest.fixture(scope="session")
def truth_table():
    return synthetic.truth_table()


@pytest.fixture(scope="session")
def must_fail_names(truth_table):
    return set(truth_table.loc[truth_table.must_fail, "name"])


@pytest.fixture(scope="session")
def all_rows():
    """All scenario rows in one shuffled frame (real files are not sorted)."""
    return synthetic.all_rows()


@pytest.fixture(scope="session")
def amsa_month_files(tmp_path_factory, all_rows):
    """All scenario rows written as monthly AMSA-style shapefiles in the data/raw layout.
    Returns {'2026-07': Path, '2026-08': Path}."""
    return synthetic.write_month_files(all_rows, tmp_path_factory.mktemp("raw"))


@pytest.fixture
def amsa_edge_rows():
    """Parsing edge cases: suffix/hour boundaries, negative CRAFT_ID, missing TYPE, zero L/B/draught,
    a duplicate row, reversed order."""
    return synthetic.edge_rows()


@pytest.fixture
def amsa_edge_shapefile(tmp_path, amsa_edge_rows):
    return synthetic.write_amsa_shapefile(amsa_edge_rows, tmp_path / "ct_nw_08_2026_pt.shp")


@pytest.fixture
def amsa_conflicting_suffix_row():
    """Suffix contradicts the hour ('13:00:00 AM'). Expected behaviour is undecided (Jack)."""
    return synthetic.conflicting_suffix_row()
