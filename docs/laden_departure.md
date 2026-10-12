# Laden departure: working hypothesis (not adopted)

Status: hypothesis to test in S0. Proposed by Jack on 2026-10-12. No draught is used anywhere in the definition.

## Probe facts this depends on (see STATUS.md for sources)
- There is no SUBTYPE and no IMO field, and TYPE has no bulk-carrier value. **Berth geometry is the only type filter.**
- L/B is near-complete and stable per CRAFT_ID. Use the per-vessel modal value. L/B sets size class and rejects small craft. It cannot tell bulkers from tankers or containerships.
- TYPE is classified per CRAFT_ID by modal value (`TYPE_CLASS`: cargo / tanker / other / unknown); the row-level TYPE is kept. Of 326 vessels with modal L >= 150 m in the Hedland box (Aug), 4 are unknown/other (Tug, Passenger, unknown code 0), so a strict cargo filter has a small known leak (STATUS.md P8). The filter is not widened.

## Definition
- **Eligible vessel:** modal `TYPE_CLASS == cargo`; modal LENGTH and BEAM present and inside a size band. Band edges come from the L/B scatter. Textbook class values are only starting guesses. Missing or implausible dimensions -> call-level reason code `unclassified_size` (cargo NaN, never 0). Adopted by Jack 2026-10-12; it is a reason code, not an addition to the fixed flag list.
- **Call:** a port-limit visit, from inbound to outbound crossing of the port-limit polygon. Fragments are merged across gaps < G h. Anchorage time and berth shifts stay in one call. A departure is a port-limit exit, never a berth exit.
- **Laden departure:** requires all of:
  - (a) a dwell of at least D_min h at SOG < S, wholly inside an iron-ore loading-berth polygon (small buffer);
  - (b) the final stationary dwell before exit is at a loading berth;
  - (c) the outbound crossing comes within T_max h of that dwell ending, with no re-entry within X h.
- D_min, T_max, X, G, S and the band edges are all empirical. Derive them from the probe-month distributions and freeze them on the calibration period before S3.

## Known leaks (document, do not hide)
- Ballast vessels that dwell at a loader and leave without loading, and aborted loadings. These are caught later by `light_departure`, as a flag.
- Multi-user berths: a dwell does not prove iron ore. Include/exclude is an explicit decision, quantified against PPA.

## Circularity rule
Draught may be used to diagnose definition precision on the calibration period only, and must be reported as such. It never tunes parameters on held-out months.

## S1 synthetic cases that must FAIL the definition
1. Ballast arrival shifting anchorage -> loader -> second loader, leaving after a dwell < D_min.
2. Loaded vessel whose last stationary dwell is at a non-loader berth.
3. Departure followed by re-entry within X h.
4. AIS gap straddling the port-limit crossing: flagged `ais_gap`, not dropped.
5. Tug-sized vessel dwelling at a loader.
