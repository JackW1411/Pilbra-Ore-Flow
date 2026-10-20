"""S4 figures for docs/writeup.md (static PNG, light mode, aggregates only).

    PYTHONPATH=src python scripts/s4/figures.py [--run RUN]
Reads the frozen calibration, the Mar-Aug per-call CSV and the PPA monthly totals; writes docs/figures/*.png and
prints the numbers each figure shows.
Palette: reference categorical slots 1 (blue, model) and 2 (orange, baseline); PPA in primary ink.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from pilbara_oreflow import match, tonnage  # noqa: E402
from pilbara_oreflow.config import data_root, load_config  # noqa: E402

RUN = "2026-03_2026-04_2026-05_2026-06_2026-07_2026-08"   # default; override with --run (DATA_ROOT/out/<run>/)
MONTHS = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
CAL = {"2026-06", "2026-07"}
FIG = ROOT / "docs" / "figures"
INK, INK2, MUTED, GRID, SURF = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e1", "#fcfcfb"
MODEL, BASE = "#2a78d6", "#eb6834"

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
                     "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF})


def data(run: str = RUN):
    cfg = load_config()
    cal = json.loads((ROOT / "scripts/s2/output/calibration.json").read_text())["a3"]
    calls = pd.read_csv(data_root(cfg) / "out" / run / "calls.csv", parse_dates=["t_in", "t_out", "t_exit", "final_dwell_end"])
    calls = tonnage.flag_calls(calls, cfg)
    ais = match.ais_side(calls, cfg["aggregation"]["timezone"])
    pred, base = tonnage.predict(ais, cal["params"], cfg), tonnage.baseline(ais, cal["means"])
    tot = match.monthly_totals(ais, pred, base, cal["ph4_iron_share"]).reindex(MONTHS)
    rows = [l.split() for l in (ROOT / "scripts/s3/output/ppa_monthly_totals.txt").read_text().splitlines()
            if re.match(r"^\d{4}-\d{2}\s", l)]
    tot["ppa"] = pd.Series({r[0]: float(r[3]) for r in rows})
    return cfg, ais, pred, base, cal, tot


def fig_monthly(tot):
    x = np.arange(len(MONTHS))
    fig, ax = plt.subplots(figsize=(8, 4.2))
    for i, m in enumerate(MONTHS):
        if m in CAL:
            ax.axvspan(i - 0.5, i + 0.5, color="#f0efec", zorder=0)
    ax.text(3.5, 54.6, "calibration", ha="center", color=MUTED, fontsize=9)
    ax.text(1.0, 54.6, "held-out", ha="center", color=MUTED, fontsize=9)
    ax.text(5.0, 54.6, "held-out", ha="center", color=MUTED, fontsize=9)
    ax.plot(x, tot.ppa / 1e6, color=INK, lw=2, marker="o", ms=8, label="PPA reported", zorder=3)
    ax.plot(x, tot.model_t / 1e6, color=MODEL, lw=2, marker="s", ms=8, label="Draught model", zorder=4)
    ax.plot(x, tot.baseline_t / 1e6, color=BASE, lw=2, marker="^", ms=8, ls="--", label="Baseline (count x class mean)", zorder=4)
    ax.set_xticks(x, [pd.Timestamp(m).strftime("%b %Y") for m in MONTHS])
    ax.set_xlim(-0.5, len(MONTHS) - 0.5)
    ax.set_ylim(40, 56)
    ax.set_ylabel("Iron ore exports (Mt per month)")
    ax.yaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.legend(loc="lower left", frameon=False, fontsize=9, ncol=3)
    ax.set_title("Port Hedland monthly iron ore exports: AIS estimates vs PPA", loc="left", color=INK, fontsize=12)
    fig.text(0.01, 0.01, "Sources: AMSA CTS AIS (CC BY-NC 3.0 AU); Pilbara Ports Authority monthly commodity statistics. "
             "Months are AWST month of loading completion.", fontsize=7, color=MUTED)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(FIG / "monthly_vs_ppa.png", dpi=150)
    plt.close(fig)


def fig_errors(tot):
    held = [m for m in MONTHS if m not in CAL]
    e = tot.loc[held]
    em = (e.model_t - e.ppa) / e.ppa * 100
    eb = (e.baseline_t - e.ppa) / e.ppa * 100
    x = np.arange(len(held))
    w = 0.36
    fig, ax = plt.subplots(figsize=(7, 3.8))
    ax.bar(x - w / 2 - 0.01, em, w, color=MODEL, label="Draught model")
    ax.bar(x + w / 2 + 0.01, eb, w, color=BASE, label="Baseline", hatch="//", edgecolor=SURF, lw=0)
    for xi, v in zip(x - w / 2, em):
        ax.annotate(f"{v:+.1f}%", (xi, v), xytext=(0, -12), textcoords="offset points", ha="center", color=INK2, fontsize=8)
    for xi, v in zip(x + w / 2, eb):
        ax.annotate(f"{v:+.1f}%", (xi, v), xytext=(0, -12), textcoords="offset points", ha="center", color=INK2, fontsize=8)
    ax.axhline(0, color=INK2, lw=1)
    ax.set_xticks(x, [pd.Timestamp(m).strftime("%b %Y") for m in held])
    ax.set_ylim(-6.5, 1)
    ax.set_ylabel("Error vs PPA (%)")
    ax.yaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    ax.set_title(f"Held-out months: mean absolute error {em.abs().mean():.1f}% (model) vs {eb.abs().mean():.1f}% (baseline)",
                 loc="left", color=INK, fontsize=11)
    fig.tight_layout()
    fig.savefig(FIG / "heldout_errors.png", dpi=150)
    plt.close(fig)
    return em, eb


def fig_weekly(ais):
    local = ais.final_dwell_end.dt.tz_convert("Australia/Perth").dt.tz_localize(None)
    wk = local.dt.to_period("W-SUN").dt.start_time
    g = pd.DataFrame({"week": wk, "usable": ais.usable}).groupby("week").agg(n=("usable", "size"), usable=("usable", "sum"))
    g = g[(g.index >= "2026-03-02") & (g.index <= "2026-08-24")]          # full weeks only
    x = np.arange(len(g))
    fig, ax = plt.subplots(figsize=(9, 3.6))
    ax.bar(x, g.usable, 0.8, color=MODEL, label="usable departure draught", edgecolor=SURF, lw=1)
    ax.bar(x, g.n - g.usable, 0.8, bottom=g.usable, color=MUTED, label="flagged (no draught estimate)",
           edgecolor=SURF, lw=1)
    ticks = x[::4]
    ax.set_xticks(ticks, [g.index[i].strftime("%d %b") for i in ticks])
    ax.set_ylabel("Laden departures per week")
    ax.yaxis.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.set_ylim(0, 75)
    ax.legend(loc="upper left", bbox_to_anchor=(0, 1.02), frameon=False, fontsize=9, ncol=2)
    ax.set_title(f"Weekly laden departures from Port Hedland, Mar-Aug 2026 (coverage {g.usable.sum() / g.n.sum():.1%})",
                 loc="left", color=INK, fontsize=11, pad=22)
    fig.tight_layout()
    fig.savefig(FIG / "weekly_departures.png", dpi=150)
    plt.close(fig)
    return g


def main(run: str = RUN):
    FIG.mkdir(parents=True, exist_ok=True)
    cfg, ais, pred, base, cal, tot = data(run)
    fig_monthly(tot)
    em, eb = fig_errors(tot)
    g = fig_weekly(ais)
    print(tot[["laden_departures", "usable", "model_t", "baseline_t", "ppa"]].round(0).to_string())
    print("held-out signed error % model", em.round(2).to_dict(), "baseline", eb.round(2).to_dict())
    print("weeks", len(g), "laden", int(g.n.sum()), "usable", int(g.usable.sum()))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=RUN, help="run directory name under DATA_ROOT/out/")
    main(ap.parse_args().run)
