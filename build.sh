# thumbsup --config thumbsUp_config.json --input ./src --output .
docker run -t  -v "$(pwd):/work" -u $(id -u):$(id -g)  ghcr.io/thumbsup/thumbsup thumbsup --input /work/src --output /work --config /work/thumbsUp_config.json
