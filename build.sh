#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"   # the $(pwd) below has to be the repo root

# thumbsup slugifies the album *page* name but copies the album *directory* name
# into media URLs verbatim, so src/'s unicode normal form leaks into the
# published HTML -- while git commits media/ as NFC (core.precomposeunicode).
# Pin src/ to NFC first: when the two disagree the album 404s on GitHub Pages,
# which compares bytes, and looks perfect on macOS, which does not.
python3 ./nfcSrc.py

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

# Last, once the markup is final: every media/ reference must resolve
# byte-exactly. macOS matches paths case- and normalisation-insensitively and
# GitHub Pages does not, so this is the only local check that can fail the way
# production does.
python3 ./checkLinks.py
