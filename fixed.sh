#!/usr/bin/env bash
set -euo pipefail

# Config (override via env if you want)
UNIDENTIFIED_LIST="${UNIDENTIFIED_LIST:-unidentified_messages.txt}"
FIXED_LIST="${FIXED_LIST:-fixed_messages.txt}"
UNIDENTIFIED_DIR="${UNIDENTIFIED_DIR:-unidentified}"
FIXED_DIR="${FIXED_DIR:-fixed}"

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <message_id>"
    exit 1
fi
MID="$1"

# Ensure lists exist
touch "$UNIDENTIFIED_LIST"
touch "$FIXED_LIST"

# Append to fixed_messages.txt if not already present
if ! grep -Fxq "$MID" "$FIXED_LIST"; then
    echo "$MID" >> "$FIXED_LIST"
    echo "Added $MID to $FIXED_LIST"
else
    echo "$MID already present in $FIXED_LIST"
fi

# Paths
SRC_FILE="${UNIDENTIFIED_DIR}/${MID}.txt"
DST_FILE="${FIXED_DIR}/${MID}.txt"

# Ensure directories
mkdir -p "$UNIDENTIFIED_DIR" "$FIXED_DIR"

# Copy to fixed, then remove original
if [[ -f "$SRC_FILE" ]]; then
    cp -f "$SRC_FILE" "$DST_FILE"
    rm -f "$SRC_FILE"
    echo "Moved ${SRC_FILE} -> ${DST_FILE}"
else
    echo "Warning: source file not found: ${SRC_FILE}"
fi

echo "Done."
