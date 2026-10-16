# Sources

Retrieval dates are UTC dates of the fetch. Files marked "not committed" live under `data/raw/` (gitignored).

## PPA Port of Port Hedland Port Handbook
- URL: https://www.pilbaraports.com.au/about-pilbara-ports/publications/forms-and-publications/forms-and-publications/handbook/2025/september/port-of-port-hedland-port-handbook (the URL serves the PDF directly; the site blocks non-browser clients, so it was fetched in Chrome)
- Version stated on the cover: none. The cover shows only the title and document number **A941965**. The §1 amendment table lists version 1 (Harbour Master, August 2025). Inner page headers carry A222193 and "of 88" against 89 actual pages.
- PDF metadata: CreationDate/ModDate 2026-09-10 06:56:25Z, producer PDFTron office converter, PDF 1.4, 89 pages.
- Retrieved: 2026-10-12; re-read 2026-10-16 in Chrome for §6.13-6.24 berth roles (same size and sha256)
- Size: 4,576,408 bytes
- sha256: `b71bebcf7daf811a32203fee833b226d6f83ce795cf8270ae606ec8322759a37` (identical across two fetches 3 s apart)
- PDF not committed; not stored on disk.

## AMSA CTS vessel traffic, sub-areas (NW)
- Listing: https://www.operations.amsa.gov.au/Spatial/DataServices/DigitalData ("Vessel Traffic Data Sub-areas", contentItemId 6570 = Jul 2026, 6590 = Aug 2026)
- Licence: CC BY-NC 3.0 AU (https://www.operations.amsa.gov.au/spatial/DataServices/Copyright). Download requires accepting AMSA copyright and disclaimer (accepted by Jack, 2026-10-12).
- Retrieved: 2026-10-12. Not committed.

| File | Bytes | sha256 |
|---|---|---|
| `data/raw/amsa_subareas_2026_07.zip` | 74,640,457 | `3872e5b31088c64c254da4a3a9ea767480d34d8657b8613e2eca822383fa7a10` |
| `data/raw/amsa_subareas_2026_08.zip` | 79,029,621 | `ce989daf194fd554389fef56406851006234f10f347337f395571a6c94e213f6` |
| `DATA_ROOT/raw/amsa_subareas_2026_03.zip` | 54,665,750 | `68fb196713e8072e416d82355ef0b28e4d7a9f474c1a970effa9e2ff2956db5b` |
| `DATA_ROOT/raw/amsa_subareas_2026_04.zip` | 52,209,655 | `3003b376f1b6a6b04a25b82ffcebcbd7b5f9a13415c7fca33372581f810f8ddc` |
| `DATA_ROOT/raw/amsa_subareas_2026_05.zip` | 45,722,302 | `90beac105aeb4d25aa834292f312d841036fb20692b850fd19fb0b906d1fa3cd` |
| `DATA_ROOT/raw/amsa_subareas_2026_06.zip` | 72,767,428 | `75605e74bcc0a48e18b0b1847831aa61e6334403ea4fb66b803941ad3a73f274` |

Mar-Jun 2026 retrieved 2026-10-16 by `scripts/s2/fetch_amsa.py` (contentItemIds 6410, 6450, 6490, 6530; download form submitted with TermsAccepted=true, approved by Jack 2026-10-16). Metadata PDFs saved alongside in `sub_2026_MM/`. Mar-May NW files are named `cts_nw_*` and use an older schema (see docs/load_amsa_contract.md, legacy schema).

## SLIP LGATE-243 Port Authorities (working port limit)
- Service: https://public-services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/Boundaries/MapServer/12, objectid 12 "PORT HEDLAND PORT AUTHORITY", requested as GeoJSON with outSR 7844 (GDA2020).
- Catalogue: data.wa.gov.au package `port-authorities`. Licence "Custom (Other)", **terms not yet read**, so the geometry is not committed.
- Retrieved: 2026-10-12 06:55 UTC by `scripts/s0/fetch_port_limit.py`. Saved to `DATA_ROOT/raw/slip_lgate243/port_hedland_port_authority.geojson` (338,091 bytes, sha256 `3274c33b0473268fe1f029632bab47ab3a450c5298d4504e2b99565369365b4b`).

## PPA Port Hedland port statistics (read only, nothing downloaded)
- Page: https://www.pilbaraports.com.au/ports/port-of-port-hedland/about-port-of-hedland/port-statistics-reports (read in Chrome 2026-10-12)
- Monthly PDFs, January 2015 to August 2026: "cargo by destination" and "cargo, GRT and DWT statistics by commodity type". Files read: August 2026 (both) and January 2015 (commodity). No hashes recorded because nothing was stored. Licence/terms not read.

## OpenStreetMap (Overpass API)
- https://overpass-api.de/api/interpreter, queried from 2026-10-12 06:54 UTC by `scripts/s0/osm_check.py` and `osm_nearest_berth.py` (mirrors as fallback). Committed outputs hold tags, counts, names and distances only. From 2026-10-12 08:26 UTC every raw response (incl. berth geometry) and its query are saved to `DATA_ROOT/raw/osm/` (gitignored); each output records file, sha256 and the mirror's `osm_base` timestamp. Data (c) OpenStreetMap contributors, ODbL.

## Licences: Jack's reading
Recorded only from Jack's own statements. Nothing here is a summary or interpretation of a licence.

### AMSA vessel tracking data
- Documents: https://www.operations.amsa.gov.au/spatial/DataServices/Copyright and https://www.operations.amsa.gov.au/spatial/DataServices/Disclaimer
- Version or date: not recorded
- Status: **not yet read by me** (Jack)

### SLIP LGATE-243 Port Authorities
- Catalogue page: https://catalogue.data.wa.gov.au/dataset/port-authorities (licence field "Custom (Other)"; licence document URL not identified)
- Version or date: not recorded
- Status: **not yet read by me** (Jack)

### PPA port statistics
- Terms document: not identified
- Version or date: not recorded
- Status: **not yet read by me** (Jack)
