#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

SEPARATOR = '=' * 50


def load_records(data: Any, filename: Path) -> Tuple[List[Dict[str, Any]], Any, str]:
    """
    Accept:
      - top-level list of records
      - top-level dict with exactly one list value
    Return (records, container, key) to allow write-back.
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


def sort_record_keys(rec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a new dict with keys sorted alphabetically.
    """
    return {k: rec[k] for k in sorted(rec.keys())}


def process_file(path: Path, preview: bool, sort_all: bool) -> int:
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
        records, container, key = load_records(raw, path)
    except Exception as e:
        print(f'[ERROR] {path}: cannot read/parse JSON: {e}')
        return 2

    updated_records: List[Dict[str, Any]] = []
    preview_items: List[int] = []

    for idx, rec in enumerate(records, start=1):
        if not isinstance(rec, dict):
            updated_records.append(rec)
            continue

        rec_changed = False
        new_rec = dict(rec)

        # Remove the field if present
        if 'reading_text' in new_rec:
            del new_rec['reading_text']
            rec_changed = True

        # Enforce alphabetical order
        if rec_changed or sort_all:
            new_rec = sort_record_keys(new_rec)

        updated_records.append(new_rec)

        if preview and rec_changed:
            preview_items.append(idx)

    if preview:
        print(f'\n=== Preview: {path} ===')
        if preview_items:
            print(SEPARATOR)
            print(f"Will remove 'reading_text' from {len(preview_items)} record(s):")
            sample = preview_items[:25]
            print(f'Records: {", ".join(map(str, sample))}' + (' ...' if len(preview_items) > 25 else ''))
            print(SEPARATOR)
        else:
            print("- No records contain 'reading_text'")
        return 0

    try:
        out = updated_records if container is None else {**container, key: updated_records}
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
        if sort_all:
            print(f"[OK] {path}: removed 'reading_text' where present and sorted keys for all records")
        else:
            print(f"[OK] {path}: removed 'reading_text' where present and kept keys sorted for changed records")
        return 0
    except Exception as e:
        print(f'[ERROR] {path}: failed to write output: {e}')
        return 2


def main():
    parser = argparse.ArgumentParser(
        description="Remove 'reading_text' from all JSON records and keep keys sorted alphabetically."
    )
    parser.add_argument('files', nargs='+', help='One or more JSON files (e.g., *.json)')
    parser.add_argument(
        '--preview',
        action='store_true',
        help='Show what would change without writing files',
    )
    parser.add_argument(
        '--sort-all',
        action='store_true',
        help='Also sort keys alphabetically for records that did not change',
    )
    args = parser.parse_args()

    exit_code = 0
    for file_arg in args.files:
        path = Path(file_arg)
        if not path.exists():
            print(f'[ERROR] {path}: not found')
            exit_code = max(exit_code, 2)
            continue
        rc = process_file(path, preview=args.preview, sort_all=args.sort_all)
        exit_code = max(exit_code, rc)

    sys.exit(exit_code)


if __name__ == '__main__':
    main()
