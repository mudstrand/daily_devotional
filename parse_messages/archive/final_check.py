#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Validate presence (non-empty strings) for:
REQUIRED_TEXT_FIELDS = ['subject', 'reflection', 'prayer', 'verse_text']
# Verse-like fields that must be present and valid normalized references:
REQUIRED_REFERENCE_FIELDS = ['verse', 'reading']

# Reference validation:
# Accept forms like:
#   "John 3:16"
#   "Romans 5:1-2"
#   "Proverbs 3:5,6"
#   "1 Corinthians 2:9"
#   "1 John 4:7-8,10"
# Normalization assumptions:
# - No translation tokens or trailing punctuation
# - Spaces normalized around colon/commas/hyphens
BOOK = r'(?:[1-3]\s+)?[A-Za-z][A-Za-z ]+'
CH = r'\d+'
VER = r'\d+(?:[abc])?'  # allow a/b/c suffix in input, we will check normalized form without them if needed
RANGE = rf'{VER}(?:-{VER})?'
LIST = rf'{RANGE}(?:,{RANGE})*'
REF_REGEX = re.compile(rf'^\s*({BOOK})\s+({CH}):({LIST})\s*$', re.IGNORECASE)


def load_records(data: Any, filename: Path) -> Tuple[List[Dict[str, Any]], Any, str]:
    """
    Accept:
      - top-level list of records
      - top-level dict with exactly one list value
    Return (records, container, key) for consistency and potential write-back (not used here).
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


def is_non_empty_string(v: Any) -> bool:
    return isinstance(v, str) and v.strip() != ''


def normalize_reference_spacing(ref: str) -> str:
    """
    Normalize spacing around colon/commas/hyphens; collapse multiple spaces.
    """
    s = ref.strip()
    s = re.sub(r'\s*:\s*', ':', s)
    s = re.sub(r'\s*,\s*', ',', s)
    s = re.sub(r'\s*-\s*', '-', s)
    s = re.sub(r'\s{2,}', ' ', s)
    return s


def strip_abc_suffixes(ref: str) -> str:
    """
    Remove a/b/c partial-verse suffixes for validation purposes.
    """
    return re.sub(r'(\d)[abc]\b', r'\1', ref, flags=re.IGNORECASE)


def count_verses_in_list(verses: str) -> int:
    """
    Count individual verses across a list like '1-3,5,7-8' -> 3 + 1 + 2 = 6
    """
    total = 0
    for seg in verses.split(','):
        seg = seg.strip()
        if '-' in seg:
            a, b = seg.split('-', 1)
            try:
                start = int(re.sub(r'[^\d]', '', a))
                end = int(re.sub(r'[^\d]', '', b))
                if end >= start:
                    total += end - start + 1
                else:
                    return 0
            except Exception:
                return 0
        else:
            try:
                int(re.sub(r'[^\d]', '', seg))
                total += 1
            except Exception:
                return 0
    return total


def is_valid_normalized_reference(val: Any) -> bool:
    """
    Validates a normalized Bible reference:
      - Non-empty string
      - Matches BOOK CH:VERS(,VERS)*
      - Each verse/range numeric; count > 0
    We allow a/b/c suffixes in input but treat them as normalized if spacing is correct and verse numbers are valid when suffix removed.
    """
    if not isinstance(val, str):
        return False
    s = normalize_reference_spacing(val)
    # remove a/b/c for numeric validation, but keep format otherwise
    s_for_num = strip_abc_suffixes(s)
    m = REF_REGEX.match(s_for_num)
    if not m:
        return False
    verses = m.group(3)
    # numeric/range count must be > 0
    return count_verses_in_list(verses) > 0


def validate_record(rec: Dict[str, Any]) -> List[str]:
    """
    Return a list of error strings for the record (empty if ok).
    """
    errors: List[str] = []

    # subject/reflection/prayer non-empty
    for f in REQUIRED_TEXT_FIELDS:
        if not is_non_empty_string(rec.get(f)):
            errors.append(f'{f}:empty')

    # verse/reading must be present, non-empty, valid normalized reference
    for f in REQUIRED_REFERENCE_FIELDS:
        v = rec.get(f)
        if not is_non_empty_string(v):
            errors.append(f'{f}:empty')
        else:
            if not is_valid_normalized_reference(v):
                errors.append(f'{f}:invalid_ref:{v}')

    return errors


def scan_file(path: Path, quiet_ok: bool) -> int:
    """
    Scan one file and print errors per failing record.
    Output, one line per error:
        filename:record_index<TAB>field:error_details
    If quiet_ok is False (default), files with 0 errors will print a summary OK line.
    Returns number of errors in this file.
    """
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
        records, _, _ = load_records(raw, path)
    except Exception as e:
        print(f'[ERROR] {path}: cannot read/parse JSON: {e}', file=sys.stderr)
        return 1

    errs = 0
    for idx, rec in enumerate(records, start=1):
        if not isinstance(rec, dict):
            print(f'{path}:{idx}\trecord:not_object', file=sys.stdout)
            errs += 1
            continue
        problems = validate_record(rec)
        if problems:
            errs += len(problems)
            for p in problems:
                print(f'{path}:{idx}\t{p}', file=sys.stdout)

    if errs == 0 and not quiet_ok:
        print(f'{path}\tOK', file=sys.stdout)
    return errs


def main():
    parser = argparse.ArgumentParser(
        description='Validate subject, verse, reading, reflection, and prayer fields. '
        'Ensure non-empty strings for subject/reflection/prayer and valid normalized references for verse/reading.'
    )
    parser.add_argument('files', nargs='+', help='One or more JSON files (e.g., *.json)')
    parser.add_argument(
        '--quiet-ok',
        action='store_true',
        help='Suppress OK lines for files without errors',
    )
    args = parser.parse_args()

    total_errors = 0
    for file_arg in args.files:
        path = Path(file_arg)
        if not path.exists():
            print(f'[ERROR] {path}: not found', file=sys.stderr)
            total_errors += 1
            continue
        total_errors += scan_file(path, quiet_ok=args.quiet_ok)

    # Exit non-zero if any errors
    sys.exit(1 if total_errors > 0 else 0)


if __name__ == '__main__':
    main()
