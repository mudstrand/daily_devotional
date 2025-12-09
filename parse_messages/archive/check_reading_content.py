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


def field_empty(val: Any) -> bool:
    """
    True if val is missing/not a string or empty after strip.
    """
    if not isinstance(val, str):
        return True
    return val.strip() == ''


def scan_file_reading_only(path: Path) -> int:
    """
    Scan one file and print only records where 'reading' is empty after trimming.
    Output format (one line per failure):
        filename:record_index<TAB>READING<TAB>content
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
        reading = rec.get('reading')
        if field_empty(reading):
            failures += 1
            content = ' '.join(reading.split()) if isinstance(reading, str) else f'(type={type(reading).__name__})'
            print(f'{path}:{idx}\tREADING\t{content}')
    return failures


def main():
    parser = argparse.ArgumentParser(
        description='Report records where "reading" is empty after trimming. '
        'Output: filename:record_number<TAB>READING<TAB>content'
    )
    parser.add_argument('files', nargs='+', help='One or more JSON files (e.g., *.json)')
    args = parser.parse_args()

    total_failures = 0
    for file_arg in args.files:
        path = Path(file_arg)
        if not path.exists():
            print(f'[ERROR] {path}: not found', file=sys.stderr)
            continue
        total_failures += scan_file_reading_only(path)

    # Exit non-zero if any failures found
    sys.exit(1 if total_failures > 0 else 0)


if __name__ == '__main__':
    main()
