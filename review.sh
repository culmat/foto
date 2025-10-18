#!/bin/bash
if [[ "$(uname -s)" == "Darwin" ]]; then
	DEFAULT_HOME="/Users/matthias"
else
	DEFAULT_HOME="/home/matthi"
fi

DIR="${1:-$DEFAULT_HOME/Pictures/foto/src/WIP/}"

if [[ "$(uname -s)" == "Darwin" ]]; then
	feh -.Fn -A "open %F &" "$DIR"
else
	feh -.Fn -A "shotwell -f %F &" "$DIR"
fi

