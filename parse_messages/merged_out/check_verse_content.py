#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


def load_records(data: Any, filename: Path) -> Tuple[List[Dict[str, Any]], Any, str]:
    """
    Accept:
      - top-level list of records
      - top-level dict with exactly one list value
    Return (records, container, key) for consistency.
    """
    if isinstance(data, list):
        return data, None, ""
    if isinstance(data, dict):
        list_keys = [k for k, v in data.items() if isinstance(v, list)]
        if len(list_keys) == 1:
            key = list_keys[0]
            return data[key], data, key
        raise ValueError(
            f"{filename}: expected a list or a dict with a single list of records"
        )
    raise ValueError(f"{filename}: unsupported JSON structure")


def field_empty(val: Any, min_len: int = 1) -> bool:
    """
    True if val is missing/not a string, empty after strip, or shorter than min_len.
    """
    if not isinstance(val, str):
        return True
    s = val.strip()
    if s == "":
        return True
    return len(s) < min_len


def scan_file(path: Path, refl_min_len: int) -> int:
    """
    Scan one file and print only failing records in two categories:
      - reflection too short/empty (length < refl_min_len)
      - verse empty (length < 1 after strip)

    Output (one line per failure):
      filename:record_index<TAB>FIELD<TAB>content

    Where FIELD is either REFLECTION or VERSE.
    Returns number of failures in this file.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        records, _, _ = load_records(raw, path)
    except Exception as e:
        print(f"[ERROR] {path}: cannot read/parse JSON: {e}", file=sys.stderr)
        return 0

    failures = 0
    for idx, rec in enumerate(records, start=1):
        if not isinstance(rec, dict):
            continue

        # Check reflection
        refl = rec.get("reflection")
        if field_empty(refl, min_len=refl_min_len):
            failures += 1
            if isinstance(refl, str):
                content = " ".join(refl.split())
            else:
                content = f"(type={type(refl).__name__})"
            print(f"{path}:{idx}\tREFLECTION\t{content}")

        # Check verse (must be non-empty after strip; min_len fixed at 1)
        verse = rec.get("verse")
        if field_empty(verse, min_len=1):
            failures += 1
            if isinstance(verse, str):
                content_v = " ".join(verse.split())
            else:
                content_v = f"(type={type(verse).__name__})"
            print(f"{path}:{idx}\tVERSE\t{content_v}")

    return failures


def main():
    parser = argparse.ArgumentParser(
        description='List records where "reflection" is empty/short or "verse" is empty. '
        "Output: filename:record_number<TAB>FIELD<TAB>content"
    )
    parser.add_argument(
        "files", nargs="+", help="One or more JSON files (e.g., *.json)"
    )
    parser.add_argument(
        "--min-reflection",
        type=int,
        default=10,
        help="Minimum length for reflection (default: 10)",
    )
    args = parser.parse_args()

    total_failures = 0
    for file_arg in args.files:
        path = Path(file_arg)
        if not path.exists():
            print(f"[ERROR] {path}: not found", file=sys.stderr)
            continue
        total_failures += scan_file(path, refl_min_len=args.min_reflection)

    # Exit non-zero if any failures found
    sys.exit(1 if total_failures > 0 else 0)


if __name__ == "__main__":
    main()
