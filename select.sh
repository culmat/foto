#!/bin/bash
if [[ "$(uname -s)" == "Darwin" ]]; then
	DEFAULT_HOME="/Users/matthias"
else
	DEFAULT_HOME="/home/matthi"
fi

DEST_DIR="${1:-$DEFAULT_HOME/Pictures/foto/src/WIP/}"
SRC_DIR="${2:-$DEFAULT_HOME/Pictures/s10/Camera/}"
WALLPAPER_DIR="${3:-$DEFAULT_HOME/Pictures/Wallpapers}"
# press 0 to copy to DEST_DIR
# press 1 to copy to clipboard
# press 2 to copy to WALLPAPER_DIR
# see https://man.finalrewind.org/1/feh/
## feh actions:
## 0 -> copy to DEST_DIR
## 1 -> copy to clipboard (Linux: xclip, macOS: use helper script)
## 2 -> copy to WALLPAPER_DIR

FEH_ACTION_COPY="${FEH_ACTION_COPY:-$DEFAULT_HOME/Pictures/foto/scripts/feh_action_copy.sh}"

ACTION1="\"$FEH_ACTION_COPY\" %F"

feh --edit -.Fn -A ";mkdir -p \"$DEST_DIR\" && cp %F \"$DEST_DIR/%n\"" --action1 "$ACTION1" --action2 ";mkdir -p \"$WALLPAPER_DIR\" && cp %F \"$WALLPAPER_DIR/%n\"" "$SRC_DIR"