# OpenStreetMap berth extract

`osm_berths_20261012T082713Z.json` is the raw Overpass API response used by the pipeline
(`config/project.toml` `[berths] osm_file`). `osm_berths_20261012T082713Z.query.txt` is the query and endpoint.

- Content: 19 ways tagged `seamark:type=berth` in the Port Hedland area, with geometry (`out geom`).
- OSM database timestamp: `osm_base` 2026-10-12T08:25:30Z (in the file's `osm3s` block).
- sha256: `2026e173c0c189bd7d99414c1eecd380c84ddc30a4c2bb79b5bb7e740fd33fc4`
- Retrieved by `scripts/s0/osm_check.py` from https://overpass-api.de/api/interpreter on 2026-10-12.

© OpenStreetMap contributors. This data is available under the Open Database License (ODbL) 1.0:
https://opendatacommons.org/licenses/odbl/1-0/. See https://www.openstreetmap.org/copyright.
