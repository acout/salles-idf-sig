#!/bin/bash
set -e
cd /home/antho/salles-idf-sig
python3 scripts/geocode_missing_coords.py --input public/import_queue.geojson --output public/import_queue.geojson "$@"