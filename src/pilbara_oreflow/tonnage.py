"""Cargo per laden departure from DEPARTURE draught (Fixed decision), flags, fit, baseline, coverage.

cargo = a * L * B * T_out * rho - b, with a, b per size class fitted to PPA tonnes (calibration period only).
Flagged calls get cargo NaN, never 0. Monthly totals fill flagged laden departures with the calibration
class-mean cargo and report how much was filled (decision 2026-10-13, Claude delegated).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FLAGS = ["no_draught", "static_draught", "light_departure", "ais_gap", "implausible"]


def flag_calls(calls: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Add the five Fixed flags and `usable` to laden departures. Non-laden calls get all False."""
    m, t = cfg["model"], cfg["tonnage"]
    out = calls.copy()
    laden = out.laden_departure.fillna(False).astype(bool)
    d_in, d_out = out.draught_in_m, out.draught_out_m
    thr = dict(zip(m["size_class_names"], t["light_departure_m"]))
    light_thr = out.size_class.map(thr).astype("float64")
    out["no_draught"] = laden & out.draught_out_status.isin(["zero", "missing"])
    out["implausible"] = laden & (out.draught_out_status == "code_max")
    out["static_draught"] = laden & d_in.notna() & d_out.notna() & ((d_out - d_in).abs() <= m["draught_resolution_m"] + 1e-9)
    out["light_departure"] = laden & d_out.notna() & (d_out < light_thr)
    out["ais_gap"] = laden & out["ais_gap"].astype(bool)
    out["usable"] = laden & ~out[FLAGS].any(axis=1)
    return out


def displacement_term(calls: pd.DataFrame, cfg: dict) -> pd.Series:
    """L * B * T_out * rho (tonnes of displaced water per unit block coefficient)."""
    return calls.length_m * calls.beam_m * calls.draught_out_m * cfg["model"]["seawater_density"]


def fit(calls: pd.DataFrame, observed_t: pd.Series, cfg: dict, min_n: int = 5) -> dict:
    """Least squares cargo = a*X - b per size class on usable calls with an observed tonnage.
    Classes with fewer than min_n calls use the pooled fit (marked)."""
    x = displacement_term(calls, cfg)
    ok = calls.usable & observed_t.notna() & x.notna()

    def _ls(mask):
        A = np.column_stack([x[mask], -np.ones(int(mask.sum()))])
        (a, b), *_ = np.linalg.lstsq(A, observed_t[mask].to_numpy(dtype=float), rcond=None)
        return float(a), float(b)

    if ok.sum() < 2:
        raise ValueError(f"fit needs at least 2 usable calls with observed tonnage, got {int(ok.sum())}")
    pa, pb = _ls(ok)
    params = {"_pooled": {"a": pa, "b": pb, "n": int(ok.sum())}}
    for cls in cfg["model"]["size_class_names"]:
        mask = ok & (calls.size_class == cls)
        n = int(mask.sum())
        if n >= min_n:
            a, b = _ls(mask)
            params[cls] = {"a": a, "b": b, "n": n, "pooled": False}
        else:
            params[cls] = {"a": pa, "b": pb, "n": n, "pooled": True}
    return params


def predict(calls: pd.DataFrame, params: dict, cfg: dict) -> pd.Series:
    """Cargo tonnes for usable laden departures; NaN for everything else (never 0)."""
    x = displacement_term(calls, cfg)
    a = calls.size_class.map({k: v["a"] for k, v in params.items() if not k.startswith("_")}).astype("float64")
    b = calls.size_class.map({k: v["b"] for k, v in params.items() if not k.startswith("_")}).astype("float64")
    return (a * x - b).where(calls.usable)


def class_means(calls: pd.DataFrame, observed_t: pd.Series) -> dict:
    """Mean observed cargo per size class over laden departures with an observation (baseline input)."""
    laden = calls.laden_departure.fillna(False).astype(bool)
    obs = observed_t.where(laden)
    return {k: float(v) for k, v in obs.groupby(calls.size_class).mean().dropna().items()}


def baseline(calls: pd.DataFrame, means: dict) -> pd.Series:
    """Baseline: every eligible laden departure gets its class-mean cargo. Uses no draught."""
    laden = calls.laden_departure.fillna(False).astype(bool)
    return calls.size_class.map(means).astype("float64").where(laden)


def coverage(calls: pd.DataFrame) -> dict:
    laden = calls.laden_departure.fillna(False).astype(bool)
    n = int(laden.sum())
    return {"laden_departures": n, "usable": int(calls.usable.sum()),
            "coverage": (calls.usable.sum() / n) if n else float("nan"),
            "flag_counts": {f: int(calls[f].sum()) for f in FLAGS},
            "exit_unobserved": int(calls.laden_departure.isna().sum())}


def monthly(calls: pd.DataFrame, cargo_t: pd.Series, base_t: pd.Series, tz: str) -> pd.DataFrame:
    """Monthly totals by month of the final loader dwell end in `tz` (proxy for PPA's cargo-complete date).
    model_total = usable predictions + class-mean fill for flagged laden departures; the fill is reported.
    Laden departures with no prediction and no class mean are counted in `unestimated`, never summed as 0."""
    laden = calls.laden_departure.fillna(False).astype(bool)
    month = calls.final_dwell_end.dt.tz_convert(tz).dt.strftime("%Y-%m")
    df = pd.DataFrame({"month": month, "laden": laden, "usable": calls.usable,
                       "cargo_t": cargo_t, "baseline_t": base_t})
    df["fill_t"] = df.baseline_t.where(df.laden & ~df.usable)
    df["unestimated"] = df.laden & df.cargo_t.isna() & df.fill_t.isna()
    df["baseline_missing"] = df.laden & df.baseline_t.isna()
    g = df[df.laden].groupby("month")
    out = pd.DataFrame({
        "laden_departures": g.size(), "usable": g.usable.sum(),
        "unestimated": g.unestimated.sum(), "baseline_missing": g.baseline_missing.sum(),
        "model_usable_t": g.cargo_t.sum(min_count=1), "fill_t": g.fill_t.sum(min_count=1).fillna(0.0),
        "baseline_t": g.baseline_t.sum(min_count=1)})
    out["model_total_t"] = out.model_usable_t.fillna(0.0) + out.fill_t
    out["coverage"] = out.usable / out.laden_departures
    return out
