#!/usr/bin/env bash
set -euo pipefail

DIR_A="orig_database_content"
DIR_B="loadable"
OUT_DIR="/path/to/merged_out"
mkdir -p "$OUT_DIR"

# Requires jq installed
# For each common filename, merge as arrays
comm -12 <(ls "$DIR_A" | sort) <(ls "$DIR_B" | sort) | while read -r fname; do
    A="$DIR_A/$fname"
    B="$DIR_B/$fname"
    OUT="$OUT_DIR/$fname"

    # Validate both are arrays; if not, skip with a warning
    if jq -e 'type=="array"' "$A" >/dev/null 2>&1 && jq -e 'type=="array"' "$B" >/dev/null 2>&1; then
        # Concatenate arrays, then unique by full element
        jq -s '.[0] + .[1] | unique' "$A" "$B" > "$OUT"
        echo "Merged array: $fname"
    else
        echo "Skip (not arrays): $fname" >&2
    fi
done
