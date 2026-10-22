# Pilbara Ore Flow

Estimates of monthly iron ore exports from Port Hedland, Western Australia, made from free AMSA ship-tracking (AIS)
data and each ship's departure draught, and checked against Pilbara Ports Authority (PPA) monthly statistics.

![Port Hedland monthly iron ore exports: AIS estimates vs PPA](results/figures/monthly_vs_ppa.png)

## Method

Thresholds and other parameters are in `config/project.toml`.

1. **Port calls.** AIS position reports are reprojected to GDA2020 / MGA zone 50 (EPSG:7850). A call runs from the
   first report inside the Port Hedland port limit (Landgate SLIP LGATE-243 polygon plus 500 m) to the first report
   outside it. Inside runs less than 2 h apart are merged into one call.
2. **Laden departures, without using draught.** A call counts as a laden departure if the ship is a cargo-type
   vessel of at least 150 m and spent at least 6 h stationary (below 0.5 kn) at an iron ore loading berth, its last
   stop was at a loading berth, it left within 6 h of that stop ending, and it did not re-enter within 4 h. Berth
   polygons come from OpenStreetMap, and berth roles from the PPA Port of Port Hedland handbook. Keeping draught out
   of this rule stops the coverage figure from being circular.
3. **Cargo per call.** `cargo = a * L * B * T_out * 1.025 - b`, where L and B are the ship's length and beam and
   T_out is the draught reported at the last position inside the port limit. `a` and `b` are fitted per size class
   to PPA tonnes. A call gets no draught estimate, and is flagged instead of set to zero, if its draught is missing,
   unchanged since arrival, below a per-class light threshold, or the AIS "25.5 m or more" code, or if there is an
   AIS gap at the port-limit crossing. In monthly totals, flagged calls are filled with their class-mean cargo.
4. **Calibration and evaluation on separate months.** AIS has no ship names or IMO numbers, so AIS calls cannot be
   paired one to one with PPA calls. Calls are instead grouped by departure date, and only dates where both sides
   have the same number of calls are used. The fit is on group totals. Calibration uses June and July 2026.
   Evaluation compares monthly totals with PPA on March, April, May and August 2026, which were not used in fitting.
   Every result is compared with a naive baseline that ignores draught: laden departures multiplied by the
   class-mean cargo from the calibration months.

## Results

Held-out months: March, April, May and August 2026. Calibration months: June and July 2026.

**Error metric.** For each held-out month, absolute percentage error = |estimate - PPA| / PPA. PPA is the total
iron ore export tonnes in PPA's monthly "cargo, GRT and DWT statistics by commodity type" file, whose month is the
cargo-complete date. On the AIS side, a call's month is the month (Australia/Perth time) in which its final loading
stop ended. The summary figure is the unweighted mean of the four monthly errors. Coverage is the share of laden
departures with a usable departure draught.

| Held-out month | Laden departures | Coverage | Draught model error | Baseline error |
|---|---|---|---|---|
| Mar 2026 | 245 | 97.55% | 4.11% | 4.90% |
| Apr 2026 | 251 | 92.43% | 0.88% | 2.59% |
| May 2026 | 272 | 93.75% | 2.30% | 4.08% |
| Aug 2026 | 255 | 96.86% | 1.47% | 1.03% |
| **Mean** | | **95.15%** | **2.19%** | **3.15%** |

Source: `results/evaluate.txt`, block E2 (primary matching rule A3). In every held-out month, both the model and
the baseline estimates are below the PPA figure (same file, `model_t` and `baseline_t` against `ppa_iron_ore_t`).

![Held-out errors](results/figures/heldout_errors.png)

The model beats the baseline in three of the four months. With the originally pre-registered matching rule (K5),
the mean errors are 4.19% (model) and 4.46% (baseline) (`results/evaluate.txt`, E4).

**Pre-registration and amendment A3.** The matching rule, the calibration/held-out split and the error metric were
written down in `docs/preregistration.md` and committed (`74508cc`) before any PPA tonnes were joined to AIS. The
original rule put only 14% of calibration-month departures into usable groups (73 of 520, `results/calibrate.txt`,
C2). Amendment A3 changed the date key to the PPA departure date with a fixed time shift (54%, 282 of 520). It was
made after the calibration fit and its in-sample residuals had been seen. In the commit history, A3 (`5522360`)
comes after the calibration commit (`aa4b8c6`) and before the held-out evaluation, which `results/evaluate.txt`
records as run at 2026-10-17 06:40 UTC and which was committed in `a7ca038`. Commit timestamps can be edited by
the author, so this is supporting evidence, not proof.

## Limitations

- Only four held-out months. The differences between the model and the baseline (2.19% vs 3.15% mean, with the
  baseline better in August) are within what four months can distinguish. This does not show that draught is
  better than counting laden departures.
- Both methods under-estimated in all four held-out months. Signed errors (estimate minus PPA, as a share of PPA;
  magnitudes from the `model_err` and `baseline_err` columns of `results/evaluate.txt`, signs from `model_t` and
  `baseline_t` against `ppa_iron_ore_t` in the same file):

  | Month | Draught model | Baseline |
  |---|---|---|
  | Mar 2026 | -4.11% | -4.90% |
  | Apr 2026 | -0.88% | -2.59% |
  | May 2026 | -2.30% | -4.08% |
  | Aug 2026 | -1.47% | -1.03% |

  The shortfall is between 0.88% and 4.90% of PPA's figure, so the headline absolute errors reflect a consistent
  downward bias, not random scatter. The cause has not been investigated. The bias was not corrected after the
  held-out errors were seen, because the rule and the calibration/held-out split were pre-registered.
- One port (Port Hedland) and a single commodity (iron ore). The method has not been tested at other ports.
- No live feed was built. The pipeline uses AMSA's monthly AIS extracts, which are published after the month ends,
  so it cannot produce estimates in real time.
- Per-call cargo estimates are not reliable, even though monthly totals are close. Six parameters are fitted to 21
  group totals (`results/calibrate.txt`, C3), and the fitted VLOC slope of 1.55 (C5) is not physically plausible.
  Errors cancel across roughly 250 departures a month.
- Matching rule A3 was chosen after the in-sample calibration residuals had been seen (see above).
- PPA dates carry no time of day and no stated time zone, so the month boundary on the PPA side is inferred.
- The berth polygons are OpenStreetMap boxes whose accuracy has not been checked. The port limit is the SLIP
  polygon plus 500 m, and its equivalence to the handbook port limit has not been checked.
- Utah Point (berth PH 4) also loads manganese and spodumene. Its departures are scaled by an iron ore share fitted
  on the calibration months (0.55, `results/calibrate.txt`, C6).

## Reproduction

Requires Python 3.12. Pinned versions are in `requirements-lock.txt` and `pyproject.toml`.

```
python -m pip install -r requirements-lock.txt
python -m pytest tests                 # synthetic data only; no downloads needed
```

To reproduce `results/` from the raw data, first get the data as described in `data/README.md`. Two steps are
manual, because the PPA website blocks scripted clients: downloading the June and July 2026 PPA PDFs, and producing
the PPA monthly totals in a browser (a committed copy is in `results/ppa_monthly_totals.txt`). Then:

```
bash scripts/reproduce.sh              # pipeline -> calibration -> evaluation -> figures
git diff results/                      # compare with the committed outputs
```

The data location defaults to `data/`. Set `ORE_FLOW_DATA_ROOT` to use another directory.

## Repository layout

```
src/pilbara_oreflow/   pipeline: load_amsa, clean, calls, tonnage, ppa, match, viz; run (entry point)
tests/                 pytest suite on a synthetic AIS harness
scripts/s0/            feasibility probes and data fetchers (port limit, OSM, AMSA catalogue)
scripts/s2/            AMSA download, calibration
scripts/s3/            held-out evaluation; browser script for PPA monthly totals
scripts/s4/            figures
scripts/reproduce.sh   end-to-end reproduction
results/               committed outputs every number above comes from; results/s0/ holds the probe outputs
config/project.toml    all parameters, CRS, berth roles, data location
data/                  local data (not committed) except the OSM berth extract; see data/README.md
docs/                  write-up, pre-registration, data sources, load_amsa contract
```

## Data sources and licences

| Source | Used for | Licence |
|---|---|---|
| AMSA Craft Tracking System, monthly "Vessel Traffic Data Sub-areas", North West, Mar-Aug 2026 | All AIS inputs | CC BY-NC 3.0 AU |
| Landgate SLIP LGATE-243 Port Authorities boundaries | Port limit | As listed in the data.wa.gov.au catalogue ("Custom (Other)") |
| OpenStreetMap `seamark:type=berth` (extract of 2026-10-12, in `data/raw/osm/`) | Berth polygons | ODbL 1.0 |
| PPA Port of Port Hedland port handbook (A941965) | Berth roles | Terms as published by PPA |
| PPA monthly port statistics, commodity-type files | Calibration and evaluation only | Terms as published by PPA |

Links, retrieval dates and file hashes are in `docs/sources.md` and `data/README.md`.

## Attribution

- Vessel tracking data: Australian Maritime Safety Authority, Craft Tracking System, licensed under CC BY-NC 3.0 AU.
  Results derived from AMSA data in this repository are for non-commercial use only.
- Berth polygons: © OpenStreetMap contributors, available under the Open Database License (ODbL).
- Port statistics and port handbook: Pilbara Ports Authority.
- Port limit: Landgate, SLIP LGATE-243 Port Authorities.

Built with Claude Code.
