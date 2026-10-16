"""Clean pings from load_amsa: dedup, draught status, per-vessel attributes, metric coordinates.

Nothing is silently corrected: raw columns are kept; derived columns sit beside them and every change is counted
in the report. Decisions: docs/load_amsa_contract.md (C1-C3) and config [model].
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pyproj import Transformer

KEY = ["craft_id", "timestamp_utc"]
RAW = ["craft_id", "longitude", "latitude", "course", "speed", "type", "length", "beam", "draught", "timestamp"]


def type_class(t) -> str:
    """Map an AMSA TYPE string to cargo / tanker / other / unknown (S0 P8)."""
    if not isinstance(t, str):
        return "unknown"
    if t.startswith("Cargo ship"):
        return "cargo"
    if t.startswith("Tanker"):
        return "tanker"
    if t.startswith(("unknown code", "Reserved", "Local ")):
        return "unknown"
    return "other"


def _mode_positive(x: pd.Series) -> float:
    x = x[x > 0]
    return float(x.mode().min()) if len(x) else np.nan


def _mode_type(x: pd.Series):
    vc = x.dropna().value_counts()
    if vc.empty:
        return pd.NA
    return sorted(vc[vc == vc.max()].index)[0]          # deterministic tie-break


def vessel_attributes(pings: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """One row per craft_id: modal TYPE and dimensions, plausibility, size class, eligibility reason."""
    m = cfg["model"]
    g = pings.groupby("craft_id")
    v = pd.DataFrame({
        "type_modal": g["type"].agg(_mode_type),
        "length_mode_m": g["length"].agg(_mode_positive),
        "beam_mode_m": g["beam"].agg(_mode_positive),
        "n_types": g["type"].nunique(dropna=False),
    })
    v["type_class"] = v.type_modal.map(type_class)
    plausible = (v.length_mode_m <= m["max_plausible_length_m"]) & (v.beam_mode_m <= m["max_plausible_beam_m"])
    v["length_m"] = v.length_mode_m.where(plausible)
    v["beam_m"] = v.beam_mode_m.where(plausible)
    v["unclassified_size"] = v.length_m.isna() | v.beam_m.isna()
    edges, names = m["size_class_edges_m"], m["size_class_names"]
    v["size_class"] = pd.cut(v.length_m, edges, right=False, labels=names).astype("string")
    reason = pd.Series(pd.NA, index=v.index, dtype="string")
    reason[v.type_class != m["eligible_type_class"]] = "not_cargo_type"
    reason[reason.isna() & v.unclassified_size] = "unclassified_size"
    reason[reason.isna() & (v.length_m < m["min_length_m"])] = "below_min_length"
    reason[reason.isna() & v.size_class.isna()] = "outside_size_classes"
    v["eligible"] = reason.isna()
    v["ineligible_reason"] = reason
    return v


def clean(pings: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Returns (pings, vessels, report). Pings are sorted by craft_id then time and carry:
    draught_m (NaN unless a usable reported value), draught_status (ok / zero / code_max), x, y (EPSG:7850)."""
    m = cfg["model"]
    report = {"rows_in": len(pings)}
    exact = pings.duplicated(subset=RAW, keep="first")                       # C1
    p = pings[~exact]
    same_key = p.duplicated(subset=KEY, keep="first")
    p = p[~same_key].copy()
    report.update(exact_duplicates_dropped=int(exact.sum()), same_key_rows_dropped=int(same_key.sum()))

    d = p["draught"]
    status = pd.Series("ok", index=p.index, dtype="string")
    status[d == 0] = "zero"                                                  # not reported -> no_draught
    status[np.isclose(d, m["draught_code_max_m"])] = "code_max"              # C3 -> implausible
    status[d.isna()] = "missing"
    p["draught_status"] = status
    p["draught_m"] = d.where(status == "ok")
    report["draught_status_counts"] = status.value_counts().to_dict()

    tr = Transformer.from_crs(cfg["crs"]["ais_input"], cfg["crs"]["distance"], always_xy=True)
    p["x"], p["y"] = tr.transform(p.longitude.to_numpy(), p.latitude.to_numpy())

    p = p.sort_values(KEY, kind="stable").reset_index(drop=True)
    vessels = vessel_attributes(p, cfg)
    report.update(rows_out=len(p), vessels=len(vessels), eligible_vessels=int(vessels.eligible.sum()),
                  ineligible_reasons=vessels.ineligible_reason.value_counts().to_dict())
    return p, vessels, report
