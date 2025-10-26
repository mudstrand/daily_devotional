#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: $0 <directory> <n>" >&2
    exit 1
}

# Validate args
if [[ $# -ne 2 ]]; then
    usage
fi

DIR="$1"
N="$2"

# Validate directory
if [[ ! -d "$DIR" ]]; then
    echo "Error: '$DIR' is not a directory" >&2
    exit 2
fi

# Validate N as positive integer
if ! [[ "$N" =~ ^[1-9][0-9]*$ ]]; then
    echo "Error: n must be a positive integer" >&2
    exit 3
fi

# Ensure pbcopy exists (macOS)
if ! command -v pbcopy >/dev/null 2>&1; then
    echo "Error: pbcopy not found. This script requires macOS." >&2
    exit 4
fi

# Gather regular files only (non-recursive)
# Use -print0 to handle spaces/newlines in filenames
mapfile -d '' FILES < <(find "$DIR" -maxdepth 1 -type f -print0)

TOTAL=${#FILES[@]}
if (( TOTAL == 0 )); then
    echo "Error: No files found in '$DIR'" >&2
    exit 5
fi

if (( N > TOTAL )); then
    echo "Warning: Requested $N files, but only $TOTAL available. Using $TOTAL." >&2
    N=$TOTAL
fi

# Shuffle and pick N files
# We print one file per line with null guard removed, then shuffle with shuf.
# On macOS, install shuf via: brew install coreutils (gshuf), or use the fallback below.
shuffle_cmd="shuf"
if ! command -v shuf >/dev/null 2>&1; then
    if command -v gshuf >/dev/null 2>&1; then
        shuffle_cmd="gshuf"
    else
        # Fallback shuffle using awk+sort+rand if shuf/gshuf not available
        # shellcheck disable=SC2016
        SHUFFLED=($(printf '%s\n' "${FILES[@]}" | awk 'BEGIN{srand()} {print rand() "\t" $0}' | sort -k1,1n | cut -f2-))
        PICKED=("${SHUFFLED[@]:0:N}")
        # Concatenate to pbcopy safely
        # Note: printf handles filenames with spaces
        : > /dev/stdout # no-op
        {
            for f in "${PICKED[@]}"; do
                cat -- "$f"
                printf '\n'
            done
        } | pbcopy
        echo "Copied contents of ${#PICKED[@]} files to clipboard."
        exit 0
    fi
fi

# Use shuf/gshuf path
PICKED=($(printf '%s\n' "${FILES[@]}" | "$shuffle_cmd" -n "$N"))

# Concatenate selected files and copy to clipboard
{
    for f in "${PICKED[@]}"; do
        cat -- "$f"
        printf '\n'
    done
} | pbcopy

echo "Copied contents of ${#PICKED[@]} files to clipboard."
