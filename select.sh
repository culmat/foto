#!/bin/bash
SRC_DIR="${1:-/home/matthi/Pictures/s10/Camera/}"
DEST_DIR="${2:-/home/matthi/Pictures/sigal/src/WIP/}"

feh --edit -.Fn -A ";mkdir -p \"$DEST_DIR\" && cp %F \"$DEST_DIR/%n\"" "$SRC_DIR"
