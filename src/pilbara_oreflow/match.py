"""AIS laden departures <-> PPA calls by date key, group-level calibration and held-out evaluation.

Implements docs/preregistration.md (incl. amendments A1-A3). Calls are never paired one-to-one: within a key value the
AIS and PPA calls form a group, and only balanced groups (equal counts) are used. PPA tonnes enter only as fit targets
on calibration months and as monthly totals on held-out months; DWT, GRT and vessel names never reach this module.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .tonnage import displacement_term

LOADER_COMMODITIES = ["Iron Ore", "Manganese Ore", "Spodumene Concentrate"]          # amendment A1
VARIANTS = {                                                                          # id: (date fields, tz)
    "K1": (("arrival", "departure"), "Australia/Perth"),
    "K2": (("cargo_complete", "departure"), "Australia/Perth"),
    "K3": (("arrival", "cargo_complete", "departure"), "Australia/Perth"),
    "K4": (("arrival", "departure"), "UTC"),
    "K5": (("cargo_complete", "departure"), "UTC"),
    "K6": (("arrival", "cargo_complete", "departure"), "UTC"),
    # amendment A3: departure date only, AIS exit time shifted before taking the UTC date
    "K7": (("departure",), "UTC", 0),
    "K8": (("departure",), "UTC", 4),
    "K9": (("departure",), "UTC", 8),
}
AIS_TIME = {"arrival": "t_in", "cargo_complete": "final_dwell_end", "departure": "t_exit"}


def ppa_side(ppa_lines: pd.DataFrame) -> pd.DataFrame:
    """PPA calls exporting a loader-berth commodity, with loader-commodity and iron-ore export tonnes."""
    ld = ppa_lines[ppa_lines.commodity.isin(LOADER_COMMODITIES) & (ppa_lines.export_t > 0)]
    keep = ld[["file_month", "call_id"]].drop_duplicates()
    sub = ppa_lines.merge(keep, on=["file_month", "call_id"])
    g = sub.groupby(["file_month", "call_id"])
    out = g.agg(arrival=("arrival", "first"), departure=("departure", "first"),
                cargo_complete=("cargo_complete", "first")).reset_index()
    t = sub[sub.commodity.isin(LOADER_COMMODITIES)].groupby(["file_month", "call_id"]).export_t.sum()
    io = sub[sub.commodity == "Iron Ore"].groupby(["file_month", "call_id"]).export_t.sum()
    out = out.join(t.rename("loader_t"), on=["file_month", "call_id"]).join(io.rename("iron_ore_t"),
                                                                             on=["file_month", "call_id"])
    out["iron_ore_t"] = out.iron_ore_t.fillna(0.0)
    return out


def ais_side(calls: pd.DataFrame, tz: str = "Australia/Perth") -> pd.DataFrame:
    """Laden departures with their AWST month of final loader dwell end (the period basis)."""
    lad = calls[calls.laden_departure.astype("boolean").fillna(False)].copy()
    lad["month"] = lad.final_dwell_end.dt.tz_convert(tz).dt.strftime("%Y-%m")
    return lad


def _key(df: pd.DataFrame, variant: str, ais: bool) -> pd.Series:
    fields, tz, *shift = VARIANTS[variant]
    dt = pd.Timedelta(hours=shift[0] if shift else 0)
    parts = []
    for f in fields:
        if ais:
            parts.append((df[AIS_TIME[f]] + dt).dt.tz_convert(tz).dt.strftime("%Y-%m-%d"))
        else:
            parts.append(df[f].dt.strftime("%Y-%m-%d"))                # PPA: date only, zone unknown
    return pd.concat(parts, axis=1).agg("|".join, axis=1)


def groups(ais: pd.DataFrame, ppa: pd.DataFrame, variant: str) -> tuple[pd.Series, pd.Series, pd.DataFrame]:
    """(AIS group key, PPA group key, group table with counts and `balanced`)."""
    ka, kp = _key(ais, variant, True), _key(ppa, variant, False)
    t = pd.DataFrame({"n_ais": ka.value_counts(), "n_ppa": kp.value_counts()}).fillna(0).astype(int)
    t["balanced"] = (t.n_ais == t.n_ppa) & (t.n_ais > 0)
    return ka, kp, t


def choose_variant(ais_cal: pd.DataFrame, ppa_cal: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    """Variant with the largest share of AIS laden departures in balanced groups (ties: earlier id). Counts only."""
    rows = []
    for v in VARIANTS:
        _, _, t = groups(ais_cal, ppa_cal, v)
        rows.append({"variant": v, "ais_in_balanced": int(t.n_ais[t.balanced].sum()), "ais_total": len(ais_cal),
                     "balanced_groups": int(t.balanced.sum()), "groups": len(t)})
    r = pd.DataFrame(rows).set_index("variant")
    r["share"] = r.ais_in_balanced / r.ais_total
    best = r.share.idxmax()                                              # first max = earliest id on ties
    return best, r


def _lstsq(A: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.linalg.lstsq(A, y, rcond=None)[0]


def calibrate(ais_cal: pd.DataFrame, ppa_cal: pd.DataFrame, variant: str, cfg: dict, min_n: int = 5) -> dict:
    """Group-level fits on calibration months: draught model (a, b per class, pooled fallback), baseline class means,
    PH4 iron-ore share. Returns params plus fit diagnostics (no held-out data touched)."""
    classes = cfg["model"]["size_class_names"]
    ka, kp, t = groups(ais_cal, ppa_cal, variant)
    bal = t.index[t.balanced]
    a = ais_cal.assign(key=ka.values)
    a = a[a.key.isin(bal)].assign(X=lambda d: displacement_term(d, cfg))
    y_all = ppa_cal.assign(key=kp.values).groupby("key").loader_t.sum().reindex(bal)

    # baseline class means: y_g = sum_c m_c n_cg over all balanced groups (no draught)
    n = a.pivot_table(index="key", columns="size_class", values="X", aggfunc="size", fill_value=0)
    n = n.reindex(index=bal, columns=classes, fill_value=0)
    present = [c for c in classes if n[c].sum() > 0]
    m = _lstsq(n[present].to_numpy(float), y_all.to_numpy(float))
    means = dict(zip(present, map(float, m)))

    # draught model on groups whose calls are all usable
    ok_groups = a.groupby("key").usable.all()
    ok_groups = ok_groups.index[ok_groups]
    u = a[a.key.isin(ok_groups)]
    y = y_all.reindex(ok_groups)
    sx = u.pivot_table(index="key", columns="size_class", values="X", aggfunc="sum", fill_value=0.0)
    sx = sx.reindex(index=ok_groups, columns=classes, fill_value=0.0)
    nn = u.pivot_table(index="key", columns="size_class", values="X", aggfunc="size", fill_value=0)
    nn = nn.reindex(index=ok_groups, columns=classes, fill_value=0)
    pa, pb = _lstsq(np.column_stack([sx.sum(axis=1), -nn.sum(axis=1)]).astype(float), y.to_numpy(float))
    own = [c for c in classes if nn[c].sum() >= min_n]
    pooled = [c for c in classes if c not in own]
    offset = (pa * sx[pooled].sum(axis=1) - pb * nn[pooled].sum(axis=1)) if pooled else 0.0
    A = np.column_stack([col for c in own for col in (sx[c], -nn[c])]).astype(float)
    coef = _lstsq(A, (y - offset).to_numpy(float)) if own else []
    params = {"_pooled": {"a": float(pa), "b": float(pb), "n": int(nn.to_numpy().sum())}}
    for i, c in enumerate(own):
        params[c] = {"a": float(coef[2 * i]), "b": float(coef[2 * i + 1]), "n": int(nn[c].sum()), "pooled": False}
    for c in pooled:
        params[c] = {"a": float(pa), "b": float(pb), "n": int(nn[c].sum()), "pooled": True}

    # PH4 iron-ore share (amendment A2): non-iron loader cargo comes only from PH4, so no matching is needed
    n_ph4 = int((ais_cal.final_dwell_berth == "PH 4").sum())
    non_iron = float(((ppa_cal.loader_t - ppa_cal.iron_ore_t) / ppa_cal.loader_t).sum())
    share = float(np.clip(1 - non_iron / n_ph4, 0, 1)) if n_ph4 else None

    return {"variant": variant, "params": params, "means": means, "ph4_iron_share": share,
            "diagnostics": {"balanced_groups": int(len(bal)), "ais_calls_in_balanced": int(len(a)),
                            "groups_in_draught_fit": int(len(ok_groups)), "calls_in_draught_fit": int(len(u)),
                            "ph4_ais_departures": n_ph4, "non_iron_ppa_calls": round(non_iron, 2)}}


def monthly_totals(ais: pd.DataFrame, cargo_t: pd.Series, base_t: pd.Series, ph4_share: float | None) -> pd.DataFrame:
    """Per month: model total (usable predictions + class-mean fill) and baseline total, with PH4 departures scaled by
    the calibration iron-ore share (excluded if the share is undefined)."""
    is_ph4 = ais.final_dwell_berth == "PH 4"
    w = pd.Series(1.0, index=ais.index)
    w[is_ph4] = ph4_share if ph4_share is not None else 0.0
    model = cargo_t.where(ais.usable, base_t) * w
    base = base_t * w
    df = pd.DataFrame({"month": ais.month, "model": model, "base": base, "usable": ais.usable,
                       "unestimated": model.isna(), "ph4": is_ph4})
    g = df.groupby("month")
    return pd.DataFrame({"laden_departures": g.size(), "usable": g.usable.sum(), "ph4": g.ph4.sum(),
                         "unestimated": g.unestimated.sum(), "model_t": g.model.sum(min_count=1),
                         "baseline_t": g.base.sum(min_count=1)})


def evaluate(totals: pd.DataFrame, ppa_iron_by_month: pd.Series, months: list[str]) -> pd.DataFrame:
    """Absolute % error per month vs the PPA iron-ore total; mean over `months` in the last row."""
    e = totals.reindex(months).join(ppa_iron_by_month.rename("ppa_iron_ore_t"))
    e["model_err"] = (e.model_t - e.ppa_iron_ore_t).abs() / e.ppa_iron_ore_t
    e["baseline_err"] = (e.baseline_t - e.ppa_iron_ore_t).abs() / e.ppa_iron_ore_t
    e["coverage"] = e.usable / e.laden_departures
    e.loc["mean"] = e[["model_err", "baseline_err", "coverage"]].mean()
    return e
