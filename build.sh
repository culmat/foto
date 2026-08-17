#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"   # the $(pwd) below has to be the repo root

# thumbsup --config thumbsUp_config.json --input ./src --output .
docker run -t  -v "$(pwd):/work" -u $(id -u):$(id -g)  ghcr.io/thumbsup/thumbsup thumbsup --input /work/src --output /work --config /work/thumbsUp_config.json

# thumbsup rewrites every root *.html; put the immersive viewer hooks back.
python3 ./patchHtml.py
