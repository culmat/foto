#!/bin/bash

target="${1:-src/WIP}"

# Enable case-insensitive pattern matching
shopt -s nocaseglob

if [ -d "$target" ]; then
    # Case: target is a directory
    cd "$target" || exit 1
    files=(*.jpg *.jpeg)
elif [ -f "$target" ]; then
    # Case: target is a single file
    files=("$target")
else
    echo "Error: '$target' is not a valid file or directory."
    exit 1
fi

for img in "${files[@]}"; do
    [ -e "$img" ] || continue

    description=$(exiftool -s3 -ImageDescription "$img" 2>/dev/null)

    if [ "$description" = "OLYMPUS DIGITAL CAMERA" ]; then
        echo "Found 'OLYMPUS DIGITAL CAMERA' in $img. Removing ImageDescription..."
        exiftool -overwrite_original -ImageDescription= "$img" >/dev/null
        echo "Removed ImageDescription from $img"
    else
        echo "No match in $img"
    fi
done
