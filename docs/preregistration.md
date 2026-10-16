# Pre-registration: AIS-PPA matching, calibration split, error metric

Committed 2026-10-16, before any PPA tonnes were matched to AIS calls and before any model or baseline error was
computed (CLAUDE.md Fixed decisions). Decided by Claude under Jack's delegation (2026-10-13). Changing anything
here after errors are seen must be logged in STATUS.md as a deviation, with the reason, and the original result
must still be reported.

What was seen before this was written: PPA monthly iron-ore totals and call counts for Jul and Aug 2026
(ppa_browser_probe.txt), and AIS laden-departure counts and coverage for Jul and Aug 2026 (STATUS.md 2026-10-16).
No PPA per-call tonnes have been joined to anything.

## 1. Periods
- **Calibration:** June and July 2026 (AWST months of the final loader dwell end).
- **Held-out:** March, April, May and August 2026. Used only for the S3 evaluation. Nothing is fitted, tuned,
  thresholded or chosen on them, including `[calls]` parameters, `light_departure` thresholds and the matching
  variant (§3).
- AMSA files loaded per run: the target months plus the adjacent months on disk. Calls whose loading started before
  the first loaded file are `<NA>` (`loader_dwell_truncated`) and are reported, not filled.

## 2. Frozen parameters
- `[calls]` keeps its current values (S1 defaults). They were not tuned on any data and are now frozen. Reason:
  tuning them against PPA call counts would use PPA as a model input.
- `light_departure_m` per size class = the midpoint of the median first-inside draught and the median
  departure draught of laden departures in the **calibration** months, rounded to 0.1 m. It uses no PPA data.
- Size classes and the berth roles stay as configured on 2026-10-16.

## 3. Matching rule (AIS laden departure <-> PPA call)
PPA side: the commodity-type file rows summed per (vessel, arrival date) = one PPA call (STATUS.md, PPA findings).
All commodities are kept for matching. **Vessel name, GRT and DWT are dropped when PPA data is read and never
stored.** Tonnes are read only after a match is fixed.

AIS side: laden departures (`laden_departure == True`), with dates from `t_in` (port-limit entry), `final_dwell_end`
(proxy for cargo complete) and `t_exit` (port-limit exit).

Key variants (fixed list):
| id | key | timezone |
|---|---|---|
| K1 | (arrival date, departure date) | AWST |
| K2 | (cargo-complete date, departure date) | AWST |
| K3 | (arrival, cargo-complete, departure dates) | AWST |
| K4-K6 | K1-K3 | UTC |

Grouping: within a key value, the AIS calls and PPA calls form a group. A group is **balanced** if both sides have
the same count, else unmatched. Calls are never paired one-to-one inside a group; groups are compared on sums.

Variant choice: on the calibration months only, pick the variant with the largest share of AIS laden departures in
balanced groups. Ties go to the earlier id. Only counts are used; no tonnes. The chosen variant and its match rate
are logged before any fit.

## 4. Calibration fits (calibration months, balanced groups only)
- **Draught model:** per group g, PPA_t(g) = sum over classes c of (a_c * sum_X(c,g) - b_c * n(c,g)), with
  X = L * B * T_out * 1.025. Groups with any non-usable call are left out of this fit. Ordinary least squares. A
  class with fewer than 5 calls in the fit uses the pooled (a, b), as in `tonnage.fit`.
- **Baseline class means:** PPA_t(g) = sum over c of m_c * n(c,g), least squares, all balanced groups (no draught).
- **PH4 iron-ore share:** s = PPA iron-ore tonnes / all PPA tonnes over balanced groups that contain a PH4 call.
  Applied to the PH4 part of monthly totals for both the model and the baseline. If no balanced group holds a PH4
  call, s is left undefined and PH4 departures are excluded from the totals, which biases them low.

## 5. Monthly totals and error (held-out months)
- Model total per month = usable predictions + calibration class-mean fill for flagged laden departures
  (`tonnage.monthly`), with PH4 departures scaled by s. The baseline total is laden departures x class mean,
  also with PH4 scaled by s.
- Target: PPA monthly **iron-ore** export total (commodity-type file total for the month).
- Error per held-out month: |total - PPA| / PPA.
- **Monthly error** (kill criterion): the mean of the per-month errors over the 4 held-out months. Each month's
  error is reported as well.
- **Beats baseline:** the model's mean held-out error is lower than the baseline's.
- **Coverage:** usable / laden departures per month, both with and without `light_departure`.
- Kill criteria as in CLAUDE.md: coverage < 60%, monthly error > 10%, or not beating the baseline.

## 6. Secondary (reported, not used for the kill decision)
- Per-group error on balanced groups in held-out months (PPA per-call data from those months is read only after
  the S3 monthly result is logged).
- Laden-departure count vs PPA iron-ore call count per month.
