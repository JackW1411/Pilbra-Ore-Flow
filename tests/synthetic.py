"""Synthetic AMSA-format AIS generator for S1 tests. No real data.

Everything here is invented: the port, berths, vessels and positions. The synthetic port sits at an arbitrary
offshore location (origin 116.5E, 19.5S) so it cannot be mistaken for Port Hedland or any real berth.

Output mirrors the real AMSA CTS sub-area schema measured in S0 (STATUS.md P1, P2):
  fields   craft_id, longitude, latitude, course, speed, type, length, beam, draught, timestamp (lowercase)
  dtypes   float64 for all except type and timestamp (str); type may be missing
  CRS      EPSG:4326 points
  time     'dd/mm/yyyy HH:MM:SS AM|PM' -- 24-hour clock WITH a redundant suffix (e.g. '19:17:06 PM')
  pings    ~15 min apart (S0 P11: median 15.0, p5 9.0, p95 21.0)

Each scenario returns its rows and a Truth record. Scenarios are built with wide margins around the
unfrozen definition parameters (ASSUMED_RANGES); a test using frozen parameters outside those ranges is invalid.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import Point, box

SEED = 20261012
ORIGIN_LONLAT = (116.5, -19.5)          # synthetic, open water; not a real port
CRS_METRIC = "EPSG:7850"                # Fixed decision: GDA2020 / MGA zone 50
CRS_AIS = "EPSG:4326"
KN = 0.514444                           # m/s per knot
REAL_FIELDS = ["craft_id", "longitude", "latitude", "course", "speed", "type", "length", "beam", "draught", "timestamp"]
FLOAT_FIELDS = ["craft_id", "longitude", "latitude", "course", "speed", "length", "beam", "draught"]

# Margins the scenarios are built around. Frozen S2 parameters must fall inside these for the truths to hold.
SHORT_DWELL_H = 1.0
LONG_DWELL_H = 30.0
REENTRY_AFTER_H = 2.0
GAP_AT_CROSSING_H = 3.0
CHATTER_CROSSINGS = 4                   # outside excursions before the vessel settles inside
CHATTER_OUTSIDE_DWELL_H = 0.3           # with moving and ping spacing: inside-to-inside gaps of ~0.6-0.9 h
LONG_STAY_DAYS = 4
LONG_STAY_SWING_H = 6.0                 # alternates 6 h just inside / 6 h just outside the limit
ASSUMED_RANGES = {
    "D_min_h": f"> {SHORT_DWELL_H} and < {LONG_DWELL_H}",
    "T_max_h": "> 1.5 (berth to port-limit exit takes ~1 h at 10 kn)",
    "X_h": f"> {REENTRY_AFTER_H} and <= 6 (tracks are observed ~6 h past the exit)",
    "SOG_kn": "> 0.3 (dwell SOG noise stays below 0.3 kn) and < 5 (transit speed >= 8 kn)",
    "crossing_gap_min": f"< {GAP_AT_CROSSING_H * 60:.0f}",
    "G_h": "> 1.0 (boundary_chatter inside-to-inside gaps are 0.6-0.9 h and must merge into one call)",
}

_to_metric = Transformer.from_crs(CRS_AIS, CRS_METRIC, always_xy=True)
_to_ais = Transformer.from_crs(CRS_METRIC, CRS_AIS, always_xy=True)
OX, OY = _to_metric.transform(*ORIGIN_LONLAT)


# ---------------------------------------------------------------- synthetic world (offsets in metres from origin)
PORT_LIMIT = box(-10_000, -10_000, 10_000, 10_000)
ANCHORAGE = (0.0, 7_000.0)
SEA = (0.0, 20_000.0)
OFFSHORE = (0.0, 120_000.0)             # departing tracks continue here: ~6 h of pings after the exit
BERTHS = {
    "SYN_LOADER_1": ("loader", box(-2_150, -8_030, -1_850, -7_970)),
    "SYN_LOADER_2": ("loader", box(1_850, -8_030, 2_150, -7_970)),
    "SYN_OTHER_1": ("other", box(-150, -9_030, 150, -8_970)),
}


def _abs(geom):
    from shapely import affinity
    return affinity.translate(geom, OX, OY)


def world() -> dict:
    """Synthetic geometries in EPSG:7850 (absolute coordinates)."""
    berths = gpd.GeoDataFrame(
        [{"name": n, "role": r, "geometry": _abs(g)} for n, (r, g) in BERTHS.items()], crs=CRS_METRIC)
    limit = gpd.GeoDataFrame([{"name": "SYN_PORT_LIMIT", "geometry": _abs(PORT_LIMIT)}], crs=CRS_METRIC)
    return {"port_limit": limit, "berths": berths, "origin_lonlat": ORIGIN_LONLAT}


def _centre(name):
    return tuple(np.array(BERTHS[name][1].centroid.coords[0]))


# ---------------------------------------------------------------- track builder
@dataclass
class Vessel:
    craft_id: float
    type: str | None
    length: float
    beam: float


class Track:
    """Emits pings at ~15 min intervals across consecutive legs. Positions are offsets in metres."""

    def __init__(self, vessel: Vessel, start: str, xy, draught: float, rng: np.random.Generator):
        self.v, self.rng = vessel, rng
        self.t = pd.Timestamp(start)
        self.next_ping = self.t
        self.xy = np.asarray(xy, float)
        self.draught = draught
        self.rows: list[dict] = []

    def _interval(self):
        return pd.Timedelta(minutes=float(np.clip(self.rng.normal(15.0, 3.0), 9.0, 21.0)))

    def _leg(self, hours, pos, sog, cog, draught_fn=None):
        t0, dur = self.t, pd.Timedelta(hours=hours)
        while self.next_ping < t0 + dur:
            f = (self.next_ping - t0) / dur
            d = draught_fn(self.next_ping - t0) if draught_fn else self.draught
            x, y = pos(f)
            self.rows.append(dict(t=self.next_ping, x=x, y=y, speed=sog(), course=cog() % 360, draught=d))
            self.next_ping += self._interval()
        self.t = t0 + dur

    def move(self, to, knots=10.0):
        to = np.asarray(to, float)
        a = self.xy.copy()
        dist = float(np.linalg.norm(to - a))
        cog = float(np.degrees(np.arctan2(to[0] - a[0], to[1] - a[1])))
        self._leg(dist / (knots * KN) / 3600, lambda f: a + f * (to - a),
                  lambda: round(max(0.0, knots + self.rng.normal(0, 0.2)), 1), lambda: round(cog, 1))
        self.xy = to
        return self

    def dwell(self, hours, draught_after=None, update_at_h=None, jitter_m=15.0):
        """Stationary. If draught_after is set, the reported draught switches at update_at_h into the dwell."""
        at = self.xy.copy()
        fn = None
        if draught_after is not None:
            before, cut = self.draught, pd.Timedelta(hours=update_at_h if update_at_h is not None else hours)
            fn = lambda dt: draught_after if dt >= cut else before
        self._leg(hours, lambda f: at + self.rng.normal(0, jitter_m, 2),
                  lambda: round(abs(self.rng.normal(0, 0.05)), 1), lambda: round(self.rng.uniform(0, 360), 1), fn)
        if draught_after is not None:
            self.draught = draught_after
        return self

    def depart(self, knots=10.0):
        """Leave the port limit and keep reporting for ~6 h offshore."""
        return self.move(SEA, knots).move(OFFSHORE, knots)

    def frame(self) -> pd.DataFrame:
        """Rows in the real AMSA raw schema and dtypes."""
        r = pd.DataFrame(self.rows)
        lon, lat = _to_ais.transform(r.x.to_numpy() + OX, r.y.to_numpy() + OY)
        out = pd.DataFrame({
            "craft_id": float(self.v.craft_id), "longitude": np.round(lon, 5), "latitude": np.round(lat, 5),
            "course": r.course.astype(float), "speed": r.speed.astype(float),
            "type": self.v.type, "length": float(self.v.length), "beam": float(self.v.beam),
            "draught": r.draught.astype(float).round(1), "timestamp": r.t.map(amsa_timestamp)})
        return out[REAL_FIELDS]


def amsa_timestamp(ts: pd.Timestamp) -> str:
    """AMSA format: 24-hour clock plus a redundant AM/PM suffix (S0 P2: suffix always agrees with the hour)."""
    return f"{ts:%d/%m/%Y %H:%M:%S} {'AM' if ts.hour < 12 else 'PM'}"


def inside_port_limit(df: pd.DataFrame) -> np.ndarray:
    x, y = _to_metric.transform(df.longitude.to_numpy(), df.latitude.to_numpy())
    return np.array([PORT_LIMIT.contains(Point(a - OX, b - OY)) for a, b in zip(x, y)])


def drop_window_around_exit(df: pd.DataFrame, hours: float, after: pd.Timestamp | None = None) -> pd.DataFrame:
    """Remove pings in a window of `hours` centred on the last inside->outside transition (after `after`)."""
    ts = pd.to_datetime(df.timestamp.str.slice(0, 19), format="%d/%m/%Y %H:%M:%S")
    ins = inside_port_limit(df)
    idx = [i for i in range(1, len(df)) if ins[i - 1] and not ins[i] and (after is None or ts.iloc[i] > after)]
    if not idx:
        raise ValueError("no outbound crossing found")
    i = idx[-1]
    if ts.iloc[-1] - ts.iloc[i] < pd.Timedelta(hours=hours):
        raise ValueError("track ends too soon after the crossing to place the gap")
    mid = ts.iloc[i - 1] + (ts.iloc[i] - ts.iloc[i - 1]) / 2
    half = pd.Timedelta(hours=hours / 2)
    return df[~((ts > mid - half) & (ts < mid + half))].reset_index(drop=True)


# ---------------------------------------------------------------- ground truth
@dataclass(frozen=True)
class Truth:
    name: str
    craft_id: float
    expected_laden_departures: int | None      # None = undetermined by design (assert flags instead)
    must_fail: bool                             # must NOT produce a laden departure
    expected_flags: frozenset = frozenset()     # call-level flags that must be raised
    expected_reason_codes: frozenset = frozenset()
    threshold_dependent: frozenset = frozenset()  # flags whose expectation needs an unfrozen threshold
    docs_case: int | None = None                # numbered must-fail case in docs/laden_departure.md
    notes: str = ""
    expected_calls: int | None = None           # set only where docs/laden_departure.md fixes the call count


CARGO = "Cargo ship - All"
_next_id = iter(range(1, 10_000))


def _cape(name_seed: int, length=292.0, beam=45.0, type_=CARGO) -> Vessel:
    # Synthetic IDs start at 9e10: above the largest real CRAFT_ID magnitude seen in S0 (~4.5e10).
    return Vessel(craft_id=9.0e10 + name_seed, type=type_, length=length, beam=beam)


def _laden_track(v, start, rng, arrival_d=8.6, departure_d=17.6, berth="SYN_LOADER_1", dwell_h=LONG_DWELL_H,
                 update_at_h=None):
    tr = Track(v, start, SEA, arrival_d, rng)
    tr.move(ANCHORAGE).dwell(20).move(_centre(berth), knots=8)
    tr.dwell(dwell_h, draught_after=departure_d, update_at_h=dwell_h - 2 if update_at_h is None else update_at_h)
    return tr


def scenarios(seed: int = SEED) -> dict[str, tuple[pd.DataFrame, Truth]]:
    rng = np.random.default_rng(seed)
    out = {}

    def add(df, truth):
        out[truth.name] = (df, truth)

    v = _cape(1)
    add(_laden_track(v, "2026-08-03 00:00", rng).depart().frame(),
        Truth("laden_call", v.craft_id, 1, False, notes="anchorage -> loader 30 h -> exit; draught 8.6 -> 17.6"))

    v = _cape(2)
    tr = Track(v, "2026-08-04 00:00", SEA, 8.5, rng)
    tr.move(ANCHORAGE).dwell(10).move(_centre("SYN_LOADER_1"), 8).dwell(SHORT_DWELL_H)
    tr.move(_centre("SYN_LOADER_2"), 6).dwell(SHORT_DWELL_H).depart()
    add(tr.frame(), Truth("ballast_shift_short_dwells", v.craft_id, 0, True, docs_case=1,
                          threshold_dependent=frozenset({"light_departure", "static_draught"}),
                          notes=f"anchorage -> loader 1 -> loader 2, each dwell {SHORT_DWELL_H} h < D_min"))

    v = _cape(3)
    tr = _laden_track(v, "2026-08-05 00:00", rng)
    tr.move(_centre("SYN_OTHER_1"), 6).dwell(6).depart()
    add(tr.frame(), Truth("last_dwell_non_loader", v.craft_id, 0, True, docs_case=2,
                          notes="loads at loader, last stationary dwell (6 h) at a non-loader berth"))

    v = _cape(4)
    tr = _laden_track(v, "2026-08-06 00:00", rng).move(SEA)
    tr.dwell(REENTRY_AFTER_H - 1.0).move(ANCHORAGE).dwell(5).depart()
    add(tr.frame(), Truth("reentry_after_departure", v.craft_id, 0, True, docs_case=3,
                          notes=f"exit, re-entry ~{REENTRY_AFTER_H} h later, anchorage dwell, exit; "
                                "0 laden departures whether or not the fragments merge (last dwell not at loader)"))

    v = _cape(5)
    df = _laden_track(v, "2026-08-07 00:00", rng).depart().frame()
    df = drop_window_around_exit(df, GAP_AT_CROSSING_H)
    add(df, Truth("ais_gap_at_crossing", v.craft_id, None, False, docs_case=4,
                  expected_flags=frozenset({"ais_gap"}),
                  notes=f"{GAP_AT_CROSSING_H} h of pings removed around the outbound crossing; call must be "
                        "retained and flagged ais_gap, not dropped"))

    v = Vessel(craft_id=9.0e10 + 6, type="Tug", length=32.0, beam=12.0)
    tr = Track(v, "2026-08-08 00:00", ANCHORAGE, 4.5, rng)
    tr.move(_centre("SYN_LOADER_1"), 8).dwell(LONG_DWELL_H).depart()
    add(tr.frame(), Truth("tug_at_loader", v.craft_id, 0, True, docs_case=5,
                          notes="tug-sized vessel dwells 30 h at a loader"))

    v = _cape(7)
    add(_laden_track(v, "2026-08-09 00:00", rng, departure_d=8.6).depart().frame(),
        Truth("static_draught", v.craft_id, 1, False, expected_flags=frozenset({"static_draught"}),
              notes="laden by geometry; reported draught identical in and out (8.6)"))

    v = _cape(8)
    add(_laden_track(v, "2026-08-10 00:00", rng, arrival_d=0.0, departure_d=0.0).depart().frame(),
        Truth("no_draught", v.craft_id, 1, False, expected_flags=frozenset({"no_draught"}),
              notes="draught 0 throughout = not reported; cargo must be NaN, never 0"))

    v = _cape(9, length=0.0, beam=0.0)
    add(_laden_track(v, "2026-08-11 00:00", rng).depart().frame(),
        Truth("missing_dimensions", v.craft_id, 0, True, expected_reason_codes=frozenset({"unclassified_size"}),
              notes="length and beam 0 (missing); not an eligible vessel; cargo NaN"))

    v = _cape(10)
    add(_laden_track(v, "2026-08-12 00:00", rng, departure_d=9.0).depart().frame(),
        Truth("light_departure_candidate", v.craft_id, 1, False,
              threshold_dependent=frozenset({"light_departure"}),
              notes="laden by geometry; draught rises only 8.6 -> 9.0"))

    v = _cape(11)
    add(_laden_track(v, "2026-07-30 12:00", rng).depart().frame(),
        Truth("month_boundary_call", v.craft_id, 1, False,
              notes="arrives 30 Jul UTC, loader dwell spans 31 Jul/1 Aug, exits 1 Aug; needs both month files"))

    # docs/laden_departure.md: "Fragments are merged across gaps < G h" -> one call.
    v = _cape(12)
    tr = Track(v, "2026-08-14 00:00", SEA, 8.6, rng)
    tr.move((0.0, 10_300.0))
    for _ in range(CHATTER_CROSSINGS):
        tr.move((0.0, 9_700.0), knots=2).dwell(0.5).move((0.0, 10_300.0), knots=2).dwell(CHATTER_OUTSIDE_DWELL_H)
    tr.move(ANCHORAGE).dwell(10).move(_centre("SYN_LOADER_1"), knots=8)
    tr.dwell(LONG_DWELL_H, draught_after=17.6, update_at_h=LONG_DWELL_H - 2)
    add(tr.depart().frame(),
        Truth("boundary_chatter", v.craft_id, 1, False, expected_calls=1,
              notes=f"crosses the port limit {2 * CHATTER_CROSSINGS + 1} times in ~5 h (inside-to-inside gaps <= ~0.9 h < G), "
                    "then anchorage -> loader 30 h -> exit; one call, one laden departure"))

    # docs/laden_departure.md rule (a): no loader dwell -> not a laden departure.
    v = _cape(13)
    tr = Track(v, "2026-08-16 00:00", SEA, 8.4, rng)
    tr.move((3_000.0, 9_600.0))
    for _ in range(int(LONG_STAY_DAYS * 24 / (2 * LONG_STAY_SWING_H))):
        tr.dwell(LONG_STAY_SWING_H, jitter_m=60).move((3_000.0, 10_400.0), knots=1)
        tr.dwell(LONG_STAY_SWING_H, jitter_m=60).move((3_000.0, 9_600.0), knots=1)
    add(tr.depart().frame(),
        Truth("long_stay_near_boundary", v.craft_id, 0, True,
              threshold_dependent=frozenset({"static_draught", "light_departure"}),
              notes=f"loiters {LONG_STAY_DAYS} days within 400 m of the port limit, 6 h in / 6 h out, never at a "
                    "berth; must not produce a laden departure (rule a). Call count depends on G: not asserted"))
    return out


def all_rows(seed: int = SEED, shuffle: bool = True) -> pd.DataFrame:
    """All scenario rows in one frame, optionally shuffled (real files are not sorted by vessel/time)."""
    df = pd.concat([d for d, _ in scenarios(seed).values()], ignore_index=True)
    return df.sample(frac=1.0, random_state=seed).reset_index(drop=True) if shuffle else df


def truth_table(seed: int = SEED) -> pd.DataFrame:
    return pd.DataFrame([t.__dict__ for _, t in scenarios(seed).values()])


# ---------------------------------------------------------------- row-level edge cases for load_amsa
def edge_rows() -> pd.DataFrame:
    """Hand-made rows covering parsing edge cases seen or implied in S0. Not a track."""
    base = dict(longitude=116.5, latitude=-19.5, course=0.0, speed=0.0, type=CARGO,
                length=292.0, beam=45.0, draught=9.2)
    rows = [
        dict(base, craft_id=9.1e10 + 1, timestamp="01/08/2026 00:00:05 AM"),   # first second of the month
        dict(base, craft_id=9.1e10 + 1, timestamp="15/08/2026 11:59:59 AM"),
        dict(base, craft_id=9.1e10 + 1, timestamp="15/08/2026 12:00:00 PM"),   # noon is PM
        dict(base, craft_id=9.1e10 + 1, timestamp="15/08/2026 19:17:06 PM"),   # 24-hour value with suffix
        dict(base, craft_id=9.1e10 + 1, timestamp="31/08/2026 23:59:50 PM"),   # last second of the month
        dict(base, craft_id=-2.1e9, timestamp="10/08/2026 08:16:59 AM"),       # negative CRAFT_ID exists in real data
        dict(base, craft_id=9.1e10 + 2, type=None, timestamp="10/08/2026 09:00:00 AM"),        # missing TYPE
        dict(base, craft_id=9.1e10 + 3, length=0.0, beam=0.0, timestamp="10/08/2026 09:15:00 AM"),  # zero L/B
        dict(base, craft_id=9.1e10 + 4, draught=0.0, timestamp="10/08/2026 09:30:00 AM"),      # zero draught
    ]
    rows.append(dict(rows[3]))                                                    # exact duplicate row
    df = pd.DataFrame(rows)[REAL_FIELDS]
    df[FLOAT_FIELDS] = df[FLOAT_FIELDS].astype(float)
    return df.iloc[::-1].reset_index(drop=True)                                   # reverse order: unsorted


def fractional_seconds_row() -> pd.DataFrame:
    """A timestamp with milliseconds, as found in 3 real Jul 2026 rows (e.g. '03/07/2026 15:15:00.555 PM')."""
    df = edge_rows().iloc[:1].copy()
    df["timestamp"] = "15/08/2026 15:15:00.555 PM"
    return df


def conflicting_suffix_row() -> pd.DataFrame:
    """A row whose suffix contradicts the hour. Never observed in Jul/Aug 2026 (S0 P2: 0 conflicts).
    What load_amsa should do with it is Jack's decision; the fixture only supplies the case."""
    df = edge_rows().iloc[:1].copy()
    df["timestamp"] = "15/08/2026 13:00:00 AM"
    return df


# ---------------------------------------------------------------- writers (real file layout)
def write_amsa_shapefile(df: pd.DataFrame, path: Path) -> Path:
    """Write rows as a point shapefile like the AMSA ct_nw_* files (EPSG:4326, lowercase fields)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf = gpd.GeoDataFrame(df[REAL_FIELDS].copy(), geometry=gpd.points_from_xy(df.longitude, df.latitude), crs=CRS_AIS)
    gdf.to_file(path, driver="ESRI Shapefile", engine="pyogrio")
    return path


def write_month_files(df: pd.DataFrame, root: Path) -> dict[str, Path]:
    """Split by UTC month (as AMSA does) and write data/raw-like layout:
    root/sub_YYYY_MM/pt/cts_sub-areas_MM_YYYY_pt/ct_nw_MM_YYYY_pt.shp"""
    ts = pd.to_datetime(df.timestamp.str.slice(0, 19), format="%d/%m/%Y %H:%M:%S")
    paths = {}
    for (y, m), part in df.groupby([ts.dt.year, ts.dt.month]):
        p = root / f"sub_{y}_{m:02d}" / "pt" / f"cts_sub-areas_{m:02d}_{y}_pt" / f"ct_nw_{m:02d}_{y}_pt.shp"
        paths[f"{y}-{m:02d}"] = write_amsa_shapefile(part, p)
    return paths
