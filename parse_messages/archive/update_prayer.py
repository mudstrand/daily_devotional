#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

SEPARATOR = '=' * 50

# Matches prayer text that ends with (AI) optionally with whitespace before/after
# Examples that should match:
#   "... Amen. (AI)"
#   "... (AI)   "
AI_TRAILING_RE = re.compile(r'\s*\(\s*AI\s*\)\s*$', re.IGNORECASE)


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


def strip_ai_suffix(text: str) -> Tuple[bool, str]:
    """
    If text ends with (AI) (case-insensitive, allowing extra spaces), strip it.
    Returns (changed, new_text).
    """
    if not isinstance(text, str):
        return False, text
    m = AI_TRAILING_RE.search(text)
    if not m:
        return False, text
    # Remove the matched suffix and trim trailing spaces
    new_text = AI_TRAILING_RE.sub('', text).rstrip()
    return True, new_text


def process_file(path: Path, preview: bool) -> int:
    """
    For each record:
      - If 'prayer' is a non-empty string and ends with (AI), remove the suffix and set ai_prayer = True.
      - Leave other records untouched.
    In --preview, print only changed records (before/after and ai_prayer).
    """
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
        records, container, key = load_records(raw, path)
    except Exception as e:
        print(f'[ERROR] {path}: cannot read/parse JSON: {e}')
        return 2

    updated_records: List[Dict[str, Any]] = []
    preview_items: List[Tuple[int, Dict[str, str]]] = []

    for idx, rec in enumerate(records, start=1):
        if not isinstance(rec, dict):
            updated_records.append(rec)
            continue

        prayer = rec.get('prayer')
        if not isinstance(prayer, str) or prayer.strip() == '':
            updated_records.append(rec)
            continue

        changed, new_prayer = strip_ai_suffix(prayer)
        if not changed:
            # no AI suffix at end; keep record as-is
            updated_records.append(rec)
            continue

        rec_copy = dict(rec)
        rec_copy['prayer'] = new_prayer
        # Set ai_prayer to True (even if already True it's idempotent)
        rec_copy['ai_prayer'] = True
        updated_records.append(rec_copy)

        if preview:
            preview_items.append(
                (
                    idx,
                    {
                        'before_prayer': prayer,
                        'after_prayer': new_prayer,
                        'ai_prayer': 'true',
                    },
                )
            )

    if preview:
        if preview_items:
            print(f'\n=== Preview: {path} ===')
            for idx, payload in preview_items:
                print(SEPARATOR)
                print(f'Record {idx}:')
                print(f'- prayer (before): {payload["before_prayer"]}')
                print(f'- prayer (after) : {payload["after_prayer"]}')
                print(f'- ai_prayer      : {payload["ai_prayer"]}')
            print(SEPARATOR)
        else:
            print(f'\n=== Preview: {path} ===')
            print('- No changes')
        return 0

    # Write mode
    try:
        out = updated_records if container is None else {**container, key: updated_records}
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'[OK] {path}: updated prayers ending with (AI)')
        return 0
    except Exception as e:
        print(f'[ERROR] {path}: failed to write updates: {e}')
        return 2


def main():
    parser = argparse.ArgumentParser(
        description='Update "prayer" fields that end with (AI): strip the suffix and set ai_prayer=true.'
    )
    parser.add_argument('files', nargs='+', help='One or more JSON files (e.g., *.json)')
    parser.add_argument('--preview', action='store_true', help='Show changes without writing files')
    args = parser.parse_args()

    exit_code = 0
    for file_arg in args.files:
        path = Path(file_arg)
        if not path.exists():
            print(f'[ERROR] {path}: not found')
            exit_code = max(exit_code, 2)
            continue
        rc = process_file(path, preview=args.preview)
        exit_code = max(exit_code, rc)

    sys.exit(exit_code)


if __name__ == '__main__':
    main()
