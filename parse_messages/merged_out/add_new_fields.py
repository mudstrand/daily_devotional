#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
from typing import Any, List

NEW_FLAGS = [
    "ai_subject",
    "ai_verse",
    "ai_reading",
    "ai_prayer",
    "ai_reflection_corrected",
]


def find_json_files(paths: List[str]) -> List[str]:
    files: List[str] = []
    if not paths:
        paths = ["."]
    for p in paths:
        if os.path.isdir(p):
            for root, _, names in os.walk(p):
                for n in names:
                    if n.endswith(".json"):
                        files.append(os.path.join(root, n))
        else:
            if p.endswith(".json") and os.path.isfile(p):
                files.append(p)
    return sorted(files)


def add_flags_to_record(obj: dict) -> bool:
    changed = False
    for k in NEW_FLAGS:
        if k not in obj:
            obj[k] = False
            changed = True
        elif not isinstance(obj[k], bool):
            # Coerce to bool if already present but not boolean
            obj[k] = bool(obj[k])
            changed = True
    return changed


def add_flags_to_doc(doc: Any) -> bool:
    """
    Expects doc to be a list of message dicts (1–50 per file).
    Returns True if any change was made.
    """
    if not isinstance(doc, list):
        return False
    changed_any = False
    for i, item in enumerate(doc):
        if isinstance(item, dict):
            if add_flags_to_record(item):
                changed_any = True
        else:
            # Non-dict items are left untouched
            continue
    return changed_any


def backup_file(path: str) -> str:
    ts = time.strftime("%Y%m%d-%H%M%S")
    backup = f"{path}.bak.{ts}"
    with open(path, "rb") as src, open(backup, "wb") as dst:
        dst.write(src.read())
    return backup


def process_file(path: str, dry_run: bool = False, no_backup: bool = False) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except Exception as e:
        return f"[ERROR] Read failed {path}: {e}"

    if not isinstance(doc, list):
        return f"[SKIP] Top-level JSON is not an array: {path}"

    changed = add_flags_to_doc(doc)
    if not changed:
        return f"[SKIP] No changes: {path}"

    if dry_run:
        return f"[DRY] Would update: {path}"

    try:
        if not no_backup:
            backup_file(path)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
            f.write("\n")
        return f"[OK] Updated: {path}"
    except Exception as e:
        return f"[ERROR] Write failed {path}: {e}"


def main():
    ap = argparse.ArgumentParser(
        description="Add ai_* boolean flags (False) to every record in JSON files with top-level arrays."
    )
    ap.add_argument(
        "paths", nargs="*", help="Files or directories (default: current directory)"
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing"
    )
    ap.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create .bak timestamped backups",
    )
    args = ap.parse_args()

    files = find_json_files(args.paths)
    if not files:
        print("[INFO] No JSON files found.", file=sys.stderr)
        sys.exit(1)

    for fp in files:
        print(process_file(fp, dry_run=args.dry_run, no_backup=args.no_backup))


if __name__ == "__main__":
    main()
