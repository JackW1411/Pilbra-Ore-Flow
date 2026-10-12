# Pilbara Ore Flow

Estimate iron ore export tonnes from Pilbara ports using free AMSA AIS data and departure draught, validated against Pilbara Ports Authority (PPA) monthly statistics.
Purpose: learning and portfolio credibility. Not a product.

## Session start (every session)
1. Read `STATUS.md`. State the current stage and gate status in one line.
2. Do only work that belongs to the current stage. If asked for later-stage work, say which gate is unpassed and stop.
3. If a request conflicts with a Fixed Decision below, push back with evidence before doing anything.

## How to work with me (Jack)
- I'm a GIS dev with strong Python. Skip basics.
- TEACH, don't solve. When I'm stuck: explain the cause, let me write the fix.
- Do NOT write or edit files in `src/` or `tests/` unless I explicitly ask in that message. Review them instead.
- Test failures: explain why they fail. Do not rewrite the code.
- Review = correctness, edge cases, flag handling, CRS misuse, silent corrections, circular validation. Not style nitpicks.
- No filler, no praise. Push back on weak ideas, including mine.
- Label confidence on factual claims: [High] [Med] [Low] [Unverified].
- Cite real sources (AMSA, IMOS, PPA, company reports) for facts about ports, data or vessels. If unsourced, say so. Never guess a number.
- Never invent field names, URLs, licence terms or release dates. Check the real data or docs, or say "unverified".

## Fixed decisions (challenge only with evidence)
- CRS: EPSG:7850 (GDA2020 / MGA zone 50) for all distance work. Reproject explicitly; never compute distances in EPSG:4326.
- Cargo from DEPARTURE draught only. Never delta-draught (ballast is discharged during loading, so delta underestimates).
- Model: `cargo = a*L*B*T_out*1.025 - b`, with a, b fitted per size class to PPA. Not textbook constants.
- Flags (never silently correct): `no_draught`, `static_draught`, `light_departure`, `ais_gap`, `implausible`. Flagged calls are NaN, never 0. Always report coverage.
- Every model is compared with the baseline: laden departures x class-mean cargo.
- Calibrate and validate on separate time periods. No circular validation.

## Scope
In: Port Hedland first. Dampier only after Hedland passes S3.
Outputs: per-call CSV, weekly tonnage chart, Folium map (laden/ballast tracks, call markers). Stretch: per-terminal attribution via berth polygons.
Out (document as limitations, do not build): live AIS, paid feeds, Cape Lambert, Ashburton (offshore transhipment breaks harbour-polygon logic).
Scope creep rule: if you think something out-of-scope is worth doing, say so in one line and wait. Do not start it.

## Stage gates (in order; each can stop the project)
- S0 Feasibility probe, one Hedland month: usable-draught coverage on laden departures, CRAFT_ID stability across two months, median in-port ping interval, actual field list (incl. length and beam), AMSA release lag, licence terms. GATE: coverage < 60% -> stop or rescope.
- S1 Synthetic harness + modules passing tests. No real data before this.
- S2 Real Hedland data: baseline first, then draught model.
- S3 PPA validation on held-out months. GATE: kill criteria.
- S4 Write-up / LinkedIn. Dampier only if S3 passes.

## Kill criteria (my judgement, not an industry standard)
Stop the draught method if, on held-out data: usable-draught coverage < 60%, OR monthly Hedland error vs PPA > 10% after calibration, OR it fails to beat the baseline.
Fails only the last test -> ship the call-count version and say so. Timebox: 4 weeks.

## Open items (verify, do not assume)
- AMSA release lag (partial, see STATUS.md); PPA statistics licence/terms (AMSA licence resolved; PPA granularity resolved, see STATUS.md log).
- [Unverified] PPA month basis and timezone: commodity files filter on cargo-complete date (2026) vs departure date (2015); dates carry no timezone.
- [Unverified] Berth polygon source. PPA handbook gives no coordinates (§6.13-6.24). Candidates: OSM `seamark:type=berth` (19 named polygons, ODbL, naming/accuracy unverified), AHO AUS 53 / ENC PT613, or digitised from imagery with the method documented. Do not invent polygons. Blocks the S0 gate. See STATUS.md "Boundary sources".
- [Unverified] Port limit: working limit is SLIP LGATE-243 (adopted 2026-10-12); equivalence to handbook §4.3 and the LGATE-243 licence terms are unverified. It excludes a harbour patch where ships dwell (STATUS.md); treatment undecided.
- [Unverified] Whether PPA monthly statistics use local (AWST) or UTC months.
- [Unverified] Which Hedland berths are multi-user (handbook §6.16 PH4 indicates yes; keyword scan only), and the PPA published cargo/berth list.
- Cape Lambert jurisdiction and whether PPA publishes its throughput (the "no PPA validation" claim is unverified).
- Definition of "laden departure" for the S0 coverage denominator that does not depend on draught itself. Hypothesis in `docs/laden_departure.md`; not adopted. Must be fixed before S0 coverage is run.
- Definition of "monthly error": per-month absolute % error, and how many held-out months are required.

## Repo layout
`src/pilbara_oreflow/`: `config`, `load_amsa`, `clean`, `calls`, `tonnage`, `viz`; `run` at entry.
`tests/` mirrors modules, synthetic data only until S1 passes. `STATUS.md` holds stage, gate results, decisions log.
Workflow per module: I write it -> I test on synthetic data -> you review.

## Conventions
- Python, pandas/geopandas, pytest. Raw data in `data/raw/` (gitignored, never edited). Derived in `data/interim/`, `data/out/`.
- Every output table carries flag columns and a coverage figure. NaN means unknown; 0 means measured zero.
- When a gate result or decision is made, update `STATUS.md` and log date + evidence.

## Doc maintenance (agent's job, not mine)

Living docs: STATUS.md, the Open items list in this file, and any brief in docs/. Each must be kept current by the agent, not left for me to remember.

End of every session (or after any gate result, decision or resolved open item): update the affected living docs and add a dated line to the STATUS.md decisions log. Do this without being asked.
Update with evidence: put the source (file, query, URL, date) next to any measured value. No value without a source. Unmeasured = blank or "pending", never a guess.
Protected sections: do NOT edit Fixed Decisions, Scope, Stage gates or Kill criteria in this file unless I explicitly tell you to in that message. If evidence suggests one should change, say so and wait. (Moving a threshold after seeing results is the failure this guards against.)
Resolved open items: move to the STATUS.md decisions log with the answer and source, then remove from the Open items list here.
Temp docs (scratch notes, intermediate summaries, probe output, one-off briefs): create only in scratch/ (gitignored). Delete each one as soon as it has been used. Before ending a session, list scratch/ and remove everything created that session. Anything worth keeping gets folded into STATUS.md first.
Deletion limits: only delete files you created in scratch/. Never delete anything in data/raw/, src/, tests/, or any file I created. If unsure whether a file is temp, ask.
Before ending a session, report in two lines: which living docs you updated, and which temp docs you deleted.