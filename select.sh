#!/bin/bash
DEST_DIR="${1:-/home/matthi/Pictures/sigal/src/WIP/}"
SRC_DIR="${2:-/home/matthi/Pictures/s10/Camera/}"
# press 0 to copy to DEST_DIR
# press 1 to copy to clipboard
# see https://man.finalrewind.org/1/feh/
feh --edit -.Fn -A ";mkdir -p \"$DEST_DIR\" && cp %F \"$DEST_DIR/%n\"" --action1 'xclip -selection clipboard -t image/%t -i %F' "$SRC_DIR"
