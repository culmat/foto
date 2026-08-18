#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"   # the $(pwd) below has to be the repo root

# thumbsup --config thumbsUp_config.json --input ./src --output .
docker run -t  -v "$(pwd):/work" -u $(id -u):$(id -g)  ghcr.io/thumbsup/thumbsup thumbsup --input /work/src --output /work --config /work/thumbsUp_config.json

# thumbsup strips EXIF while resizing, so coordinates survive only in src/.
# Pull them into the committed geo/ sidecars that map.html reads. Runs after
# thumbsup because it reads the album pages it just wrote (to resolve each
# album's page name and per-photo slide index), and before patchHtml.py because
# that links only the albums which ended up with data.
python3 ./exif2geojson.py

# thumbsup rewrites every root *.html; put the immersive and map hooks back.
python3 ./patchHtml.py
