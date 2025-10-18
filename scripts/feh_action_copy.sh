#!/bin/bash
# Copy images to clipboard. Accepts one or more file paths (as feh passes with %F).
# On macOS use pngpaste/pbcopy via AppleScript fallback. On Linux use xclip.

set -euo pipefail

if [[ "$#" -lt 1 ]]; then
    echo "Usage: $0 <image-file> [more-files...]" >&2
    exit 2
fi

copy_to_clipboard() {
    # Use the first file only. feh may pass multiple filenames in %F, but
    # a clipboard typically holds a single image. If you want different
    # behavior, adjust this function.
    local f="$1"

    # Detect available tools in preferred order
    if command -v wl-copy >/dev/null 2>&1; then
        # Wayland
        wl-copy --type "$(file --brief --mime-type "$f")" < "$f"
        return $?
    fi

    if command -v xclip >/dev/null 2>&1; then
        mime=$(file --brief --mime-type "$f")
        xclip -selection clipboard -t "image/$mime" -i "$f"
        return $?
    fi

    if command -v xsel >/dev/null 2>&1; then
        # xsel doesn't accept MIME type; try to pass raw data (may not work for images in all setups)
        cat "$f" | xsel --clipboard --input
        return $?
    fi

    if command -v pngpaste >/dev/null 2>&1; then
        # pngpaste reads clipboard to file; to set clipboard from file use AppleScript fallback below
        # but if pngpaste exists we still prefer osascript for writing images
        :
    fi

    if command -v osascript >/dev/null 2>&1; then
        # Use AppleScript to read the file as picture and set the clipboard
        osascript -e "set theFile to POSIX file \"$f\"" \
                  -e 'set theImage to (read theFile as JPEG picture)' \
                  -e 'set the clipboard to theImage'
        return $?
    fi

    echo "No supported clipboard tool found. Install wl-copy, xclip, xsel or ensure osascript is available." >&2
    return 2
}

if [[ "$#" -lt 1 ]]; then
    echo "Usage: $0 <image-file> [more-files...]" >&2
    exit 2
fi

copy_to_clipboard "$1"

