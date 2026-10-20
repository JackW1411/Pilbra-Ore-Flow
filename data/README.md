# Data

Raw and derived data are not in the repository, except the OpenStreetMap berth extract in `raw/osm/`. Scripts find
data through `DATA_ROOT`: `data/` by default (`config/project.toml`), or the path in the environment variable
`ORE_FLOW_DATA_ROOT` if set. The layout below is relative to `DATA_ROOT`.

```
raw/
  amsa_subareas_2026_MM.zip        AMSA monthly downloads (fetch_amsa.py)
  sub_2026_MM/                     extracted North West point shapefiles + metadata PDF (fetch_amsa.py)
  slip_lgate243/port_hedland_port_authority.geojson   port limit (fetch_port_limit.py)
  osm/osm_berths_20261012T082713Z.json                berth polygons (committed)
  ppa/ppa_commodity_2026_06.pdf, ppa_commodity_2026_07.pdf   PPA calibration months (manual download)
out/<run>/                         pipeline outputs: calls.csv, weekly.csv/png, monthly.csv, map.html, report.json
```

File sizes and sha256 hashes of every file used are in `docs/sources.md`.

## AMSA vessel tracking (AIS)

- Source: Australian Maritime Safety Authority, Craft Tracking System, "Vessel Traffic Data Sub-areas" (monthly),
  listed at https://www.operations.amsa.gov.au/Spatial/DataServices/DigitalData
- Licence: CC BY-NC 3.0 AU (https://www.operations.amsa.gov.au/spatial/DataServices/Copyright). Downloading means
  accepting AMSA's copyright and disclaimer terms. Non-commercial use only.
- Months used: March to August 2026. Fetch with the listing's content item ids (from `results/s0/amsa_catalogue.txt`):

  ```
  python scripts/s2/fetch_amsa.py 6410:2026-03 6450:2026-04 6490:2026-05 6530:2026-06 6570:2026-07 6590:2026-08
  ```

  The script submits AMSA's download form with the terms accepted, so read the terms before running it.
  Total download is about 380 MB.

## SLIP LGATE-243 port limit

- Source: Landgate SLIP, Port Authorities boundaries (LGATE-243), map service
  https://public-services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/Boundaries/MapServer/12
  (object id 12, "PORT HEDLAND PORT AUTHORITY"). Catalogue entry: https://catalogue.data.wa.gov.au/dataset/port-authorities
- Licence: listed in the catalogue as "Custom (Other)". Read the terms there before use.
- Fetch:

  ```
  python scripts/s0/fetch_port_limit.py
  ```

  The live service may change. The file used for the results has sha256
  `3274c33b0473268fe1f029632bab47ab3a450c5298d4504e2b99565369365b4b`.

## OpenStreetMap berth polygons (committed)

- `raw/osm/osm_berths_20261012T082713Z.json`: 19 `seamark:type=berth` ways, OSM database timestamp
  2026-10-12T08:25:30Z. See `raw/osm/NOTICE.md`.
- Licence: © OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright).
- It is committed because a fresh Overpass query returns current OSM data, which may differ from the data the results
  were produced with. `scripts/s0/osm_check.py` re-queries if you want current data.
- If `ORE_FLOW_DATA_ROOT` points elsewhere, copy `raw/osm/` there.

## Pilbara Ports Authority statistics (manual)

- Source: PPA, Port of Port Hedland port statistics reports,
  https://www.pilbaraports.com.au/ports/port-of-port-hedland/about-port-of-hedland/port-statistics-reports
  Monthly PDF "cargo, GRT and DWT statistics by commodity type". Terms: as published by PPA on its website.
- The site blocks non-browser clients, so both PPA steps are manual:
  1. **Calibration PDFs.** In a browser, download the commodity-type PDFs for June and July 2026 and save them as
     `raw/ppa/ppa_commodity_2026_06.pdf` and `raw/ppa/ppa_commodity_2026_07.pdf`. Identify each file by the
     "Cargo Complete date" in its header, not by the link label (the page files some 2026 reports under "2027").
     Expected sha256: June `53286f7b65f7bb775398195f3081aade3413f8d34d044b56b481f0de4ef77165`, July
     `b82be4f348feba4aac64b3799e0a817d0599e973901f4d780db614e298cd9810`.
  2. **Monthly totals for evaluation.** Open the statistics page in Chrome, paste `scripts/s3/ppa_monthly_totals.js`
     into the developer console, and copy its output into `results/ppa_monthly_totals.txt`. The committed copy was
     produced this way on 2026-10-17 and holds aggregates only (monthly iron ore tonnes and line counts).
- PPA tonnes are used only for calibration and evaluation, never as a model input.
