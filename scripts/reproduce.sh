#!/usr/bin/env bash
# Reproduce results/ from the raw data: pipeline run -> calibration -> held-out evaluation -> figures.
# Get the data first (data/README.md). Run from anywhere:  bash scripts/reproduce.sh
#
# Writes DATA_ROOT/out/$RUN/ and overwrites results/calibrate.txt, results/calibration.json, results/evaluate.txt
# and results/figures/*.png. Use `git diff results/` afterwards to compare with the committed outputs; header lines
# carry the run time and will differ.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH=src

MONTHS="2026-03 2026-04 2026-05 2026-06 2026-07 2026-08"
RUN="${RUN:-${MONTHS// /_}}"
DATA="$(python -c 'from pilbara_oreflow.config import data_root, load_config; print(data_root(load_config()).as_posix())')"

# MANUAL STEP 1 (browser): PPA calibration PDFs for Jun and Jul 2026 must already be in DATA_ROOT/raw/ppa/.
# MANUAL STEP 2 (browser): results/ppa_monthly_totals.txt holds the PPA monthly totals used by evaluate and
#                          figures. The committed copy is used unless you regenerate it (data/README.md).
missing=0
for f in raw/ppa/ppa_commodity_2026_06.pdf raw/ppa/ppa_commodity_2026_07.pdf \
         raw/slip_lgate243/port_hedland_port_authority.geojson raw/osm/osm_berths_20261012T082713Z.json; do
  [ -f "$DATA/$f" ] || { echo "missing: $DATA/$f (see data/README.md)"; missing=1; }
done
[ -f results/ppa_monthly_totals.txt ] || { echo "missing: results/ppa_monthly_totals.txt (manual step 2)"; missing=1; }
[ "$missing" -eq 0 ] || exit 1

echo "== 1/4 pipeline: $MONTHS -> $DATA/out/$RUN"
python -m pilbara_oreflow.run --months $MONTHS --out "$DATA/out/$RUN"
echo "== 2/4 calibration (Jun, Jul 2026) -> results/calibration.json"
python scripts/s2/calibrate.py --run "$RUN"
echo "== 3/4 held-out evaluation (Mar, Apr, May, Aug 2026) -> results/evaluate.txt"
python scripts/s3/evaluate.py --run "$RUN"
echo "== 4/4 figures -> results/figures/"
python scripts/s4/figures.py --run "$RUN"
