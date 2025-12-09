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
        return data, None, ''
    if isinstance(data, dict):
        list_keys = [k for k, v in data.items() if isinstance(v, list)]
        if len(list_keys) == 1:
            key = list_keys[0]
            return data[key], data, key
        raise ValueError(f'{filename}: expected a list or a dict with a single list of records')
    raise ValueError(f'{filename}: unsupported JSON structure')


def normalize_single_line(s: str) -> str:
    # Collapse whitespace to a single line for compact output
    return ' '.join(s.split()).strip()


def prayer_empty(val: Any) -> Tuple[bool, str]:
    """
    True if prayer is missing/not a string or empty after strip.
    Returns (is_empty, normalized_preview_or_type).
    """
    if not isinstance(val, str):
        return True, f'(type={type(val).__name__})'
    s = normalize_single_line(val)
    return (s == '', s)


def prayer_too_short(val: Any, min_chars: int) -> Tuple[bool, str]:
    """
    True if prayer exists but is shorter than min_chars after trimming.
    Returns (is_short, normalized_preview_or_type).
    """
    if not isinstance(val, str):
        return True, f'(type={type(val).__name__})'
    s = normalize_single_line(val)
    if s == '':
        return False, s  # handled by prayer_empty
    return (len(s) < min_chars, s)


def scan_file_prayer(path: Path, min_chars: int, check_size_only: bool) -> int:
    """
    Scan one file and print failing records.

    Output (one line per failure):
        filename:record_index<TAB>PRAYER_EMPTY<TAB>content
        filename:record_index<TAB>PRAYER_SHORT<TAB>content

    Behavior:
      - If --check-size is False (default):
          Report both empty prayers and prayers with content shorter than min_chars.
      - If --check-size is True:
          Only check size for existing, non-empty string prayers (skip empties and non-strings).
    Returns number of failures in this file.
    """
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
        records, _, _ = load_records(raw, path)
    except Exception as e:
        print(f'[ERROR] {path}: cannot read/parse JSON: {e}', file=sys.stderr)
        return 0

    failures = 0
    for idx, rec in enumerate(records, start=1):
        if not isinstance(rec, dict):
            continue

        prayer_val = rec.get('prayer')

        if check_size_only:
            # Only evaluate minimum length for existing string prayers; skip empties and non-strings
            if isinstance(prayer_val, str) and prayer_val.strip() != '':
                is_short, preview = prayer_too_short(prayer_val, min_chars=min_chars)
                if is_short:
                    failures += 1
                    print(f'{path}:{idx}\tPRAYER_SHORT\t{preview}')
            # else: skip (either empty or not a string)
            continue

        # Default mode: report empties and short prayers
        is_empty, preview_empty = prayer_empty(prayer_val)
        if is_empty:
            failures += 1
            print(f'{path}:{idx}\tPRAYER_EMPTY\t{preview_empty}')
            continue  # don't also report as short

        is_short, preview_short = prayer_too_short(prayer_val, min_chars=min_chars)
        if is_short:
            failures += 1
            print(f'{path}:{idx}\tPRAYER_SHORT\t{preview_short}')

    return failures


def main():
    parser = argparse.ArgumentParser(
        description='Report prayer issues. By default, lists empty prayers and prayers shorter than a minimum length. '
        'With --check-size, only check size for existing non-empty prayers.'
    )
    parser.add_argument('files', nargs='+', help='One or more JSON files (e.g., *.json)')
    parser.add_argument(
        '--min-chars',
        type=int,
        default=20,
        help='Minimum characters for prayer (default: 20)',
    )
    parser.add_argument(
        '--check-size',
        action='store_true',
        help='Only check size for existing non-empty prayers; do not report empty or non-string prayers',
    )
    args = parser.parse_args()

    total_failures = 0
    for file_arg in args.files:
        path = Path(file_arg)
        if not path.exists():
            print(f'[ERROR] {path}: not found', file=sys.stderr)
            continue
        total_failures += scan_file_prayer(path, min_chars=args.min_chars, check_size_only=args.check_size)

    # Exit non-zero if any failures found
    sys.exit(1 if total_failures > 0 else 0)


if __name__ == '__main__':
    main()
