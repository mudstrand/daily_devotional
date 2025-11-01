#!/usr/bin/env python3
import argparse
import glob
import os
import sys


def fix_text(s: str) -> str:
    # Replace ". . . " (and variants with trailing spaces) with ". "
    # Handles multiple repeats like ". . . . . " too.
    # Strategy: collapse any sequence of ". " repeated 2+ times to a single ". "
    out = []
    i = 0
    n = len(s)
    while i < n:
        if s[i] == ".":
            # Count repeats of ". "
            j = i
            reps = 0
            while True:
                if j + 2 <= n and s[j : j + 2] == ". ":
                    reps += 1
                    j += 2
                else:
                    break
            if reps >= 2:
                # Collapse to a single ". "
                out.append(". ")
                i = j
                continue
        out.append(s[i])
        i += 1
    return "".join(out)


def process_file(path: str, create_backup: bool) -> bool:
    try:
        with open(path, "r", encoding="utf-8") as f:
            original = f.read()
    except Exception as e:
        print(f"Error reading {path}: {e}", file=sys.stderr)
        return False

    fixed = fix_text(original)
    if fixed == original:
        return True

    try:
        if create_backup:
            bak = path + ".bak"
            with open(bak, "w", encoding="utf-8", newline="") as bf:
                bf.write(original)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(fixed)
        return True
    except Exception as e:
        print(f"Error writing {path}: {e}", file=sys.stderr)
        return False


def main():
    ap = argparse.ArgumentParser(
        description="Collapse spaced ellipses '. . . ' into a single '. ' across JSON files."
    )
    ap.add_argument(
        "paths",
        nargs="+",
        help="Files or glob patterns, e.g., '*.json' or 'data/**/*.json'",
    )
    ap.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not write .bak backup files.",
    )
    args = ap.parse_args()

    # Expand globs
    files = []
    for p in args.paths:
        matches = glob.glob(p, recursive=True)
        if matches:
            files.extend(matches)
        else:
            # If no glob match, treat as literal path
            if os.path.isfile(p):
                files.append(p)

    if not files:
        print("No files found.", file=sys.stderr)
        sys.exit(1)

    ok = True
    for path in sorted(set(files)):
        if not path.lower().endswith(".json"):
            continue
        if not process_file(path, create_backup=not args.no_backup):
            ok = False

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
