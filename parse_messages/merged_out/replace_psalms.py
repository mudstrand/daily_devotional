#!/usr/bin/env python3
import argparse
import glob
import os
import re
import sys


def replace_psalms(text: str) -> str:
    # Replace whole-word 'Psalms' with 'Psalm'
    # Word boundaries ensure we don't touch substrings like 'Psalmsomething'
    return re.sub(r"\bPsalms\b", "Psalm", text)


def process_file(path: str, create_backup: bool) -> bool:
    try:
        with open(path, "r", encoding="utf-8") as f:
            original = f.read()
    except Exception as e:
        print(f"Error reading {path}: {e}", file=sys.stderr)
        return False

    fixed = replace_psalms(original)
    if fixed == original:
        return True  # no change needed

    try:
        if create_backup:
            with open(path + ".bak", "w", encoding="utf-8", newline="") as bf:
                bf.write(original)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(fixed)
        return True
    except Exception as e:
        print(f"Error writing {path}: {e}", file=sys.stderr)
        return False


def main():
    ap = argparse.ArgumentParser(
        description='Replace the word "Psalms" with "Psalm" across JSON files.'
    )
    ap.add_argument(
        "paths",
        nargs="+",
        help='Files or glob patterns, e.g. "*.json" or "data/**/*.json"',
    )
    ap.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create .bak backup files.",
    )
    args = ap.parse_args()

    # Expand globs
    files = []
    for p in args.paths:
        matches = glob.glob(p, recursive=True)
        if matches:
            files.extend(matches)
        elif os.path.isfile(p):
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
