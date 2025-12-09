#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
from typing import Tuple, Optional

# Regex to capture leading Roman numeral (I, II, III) at the start of a Bible book name
# Examples:
#   "I John 4:7"           -> ("I", " John 4:7")
#   "II Corinthians 5:17"  -> ("II", " Corinthians 5:17")
#   "III John 1:2"         -> ("III", " John 1:2")
#   "I Kings. 17:4"        -> ("I", " Kings. 17:4")
#   "I Thessalonians 4:16" -> ("I", " Thessalonians 4:16")
ROMAN_PREFIX_RE = re.compile(r'^\s*(I{1,3})\s*([A-Za-z][A-Za-z.\s-]*\S.*)$')

ROMAN_TO_ARABIC = {
    'I': '1',
    'II': '2',
    'III': '3',
}


def normalize_book_numeral(ref: str) -> str:
    """
    Normalize leading Roman numerals in Bible references:
    'I ', 'II ', 'III ' -> '1 ', '2 ', '3 ' (before the book name).
    Only affects the book prefix; leaves verse/partials untouched.
    """
    if not isinstance(ref, str):
        return ref
    m = ROMAN_PREFIX_RE.match(ref)
    if not m:
        return ref
    roman, rest = m.groups()
    arabic = ROMAN_TO_ARABIC.get(roman)
    if not arabic:
        return ref
    return f'{arabic} {rest.lstrip()}'


def process_record(rec: dict) -> Tuple[dict, Optional[dict]]:
    """
    Process a single JSON record with 'verse' and 'reading'.
    Returns (updated_record, change_info or None).
    """
    changed = False
    change_info = {}

    # Normalize 'verse'
    if 'verse' in rec:
        original_verse = rec['verse']
        normalized_verse = normalize_book_numeral(original_verse)
        if normalized_verse != original_verse:
            changed = True
            rec['verse'] = normalized_verse
            change_info['verse'] = {'from': original_verse, 'to': normalized_verse}

    # Optionally normalize references inside 'reading' at line/sentence starts
    if 'reading' in rec and isinstance(rec['reading'], str):
        original_reading = rec['reading']

        def repl_line_start(match):
            roman = match.group(1)
            rest = match.group(2)
            arabic = ROMAN_TO_ARABIC.get(roman, roman)
            return f'{arabic} {rest}'

        # At line starts (multiline)
        reading_updated = re.sub(r'(?m)^(I{1,3})\s+([A-Za-z].*)', repl_line_start, original_reading)

        # After sentence/start boundaries if followed by a verse-like pattern
        reading_updated = re.sub(
            r'(?<!\w)(I{1,3})\s+([A-Za-z][A-Za-z.\s-]*\d+:\d.*)',
            repl_line_start,
            reading_updated,
        )

        if reading_updated != original_reading:
            changed = True
            rec['reading'] = reading_updated
            change_info['reading'] = {'from': original_reading, 'to': reading_updated}

    return rec, (change_info if changed else None)


def load_records(content: str, path: str):
    """
    Load JSON content as list of records.
    Supports:
      - JSON array of objects
      - Single JSON object
      - JSON Lines (one object per line)
    Returns (records_list, is_json_array_format)
    """
    try:
        data = json.loads(content)
        if isinstance(data, list):
            return data, True
        if isinstance(data, dict):
            return [data], True
        raise ValueError('Root is neither list nor dict')
    except Exception:
        # Try JSON Lines
        records = []
        for i, line in enumerate(content.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                records.append(obj)
            except Exception as e:
                print(f'[WARN] {path}: line {i} not valid JSON: {e}', file=sys.stderr)
        return records, False


def save_records(path: str, original_content: str, records: list, is_json_array: bool):
    """
    Write back records to file. Creates a .bak backup if not present.
    """
    backup_path = f'{path}.bak'
    try:
        if not os.path.exists(backup_path):
            with open(backup_path, 'w', encoding='utf-8') as bf:
                bf.write(original_content)
    except Exception as e:
        print(f'[ERROR] Cannot write backup {backup_path}: {e}', file=sys.stderr)
        return False

    try:
        with open(path, 'w', encoding='utf-8') as wf:
            if is_json_array:
                json.dump(records, wf, ensure_ascii=False, indent=2)
                wf.write('\n')
            else:
                for obj in records:
                    wf.write(json.dumps(obj, ensure_ascii=False))
                    wf.write('\n')
        return True
    except Exception as e:
        print(f'[ERROR] Cannot write updated {path}: {e}', file=sys.stderr)
        return False


def process_file(path: str, preview: bool):
    """
    Process one file. Returns (total_records, changed_records, changes_list)
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f'[ERROR] Cannot read {path}: {e}', file=sys.stderr)
        return 0, 0, []

    records, is_json_array = load_records(content, path)

    total = len(records)
    changed = 0
    changes = []
    updated_records = []

    for idx, rec in enumerate(records, start=1):
        if not isinstance(rec, dict):
            updated_records.append(rec)
            continue
        new_rec, change_info = process_record(dict(rec))
        updated_records.append(new_rec)
        if change_info:
            changed += 1
            changes.append({'file': path, 'record_index': idx, **change_info})

    if not preview and changed > 0:
        save_records(path, content, updated_records, is_json_array)

    return total, changed, changes


def _oneline(s: str) -> str:
    """Render potentially multi-line text as a single line for preview."""
    if s is None:
        return ''
    return s.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\\n')


def main():
    parser = argparse.ArgumentParser(
        description='Normalize leading Roman numerals (I/II/III) in Bible references within verse and reading fields.'
    )
    parser.add_argument('files', nargs='+', help='Input JSON files (use shell globs like *.json)')
    parser.add_argument('--preview', action='store_true', help='Preview changes without modifying files')
    args = parser.parse_args()

    grand_total = 0
    grand_changed = 0
    grand_changes = []

    for path in args.files:
        total, changed, changes = process_file(path, preview=args.preview)
        grand_total += total
        grand_changed += changed
        grand_changes.extend(changes)

    if args.preview:
        print(f'Preview mode: {grand_changed} of {grand_total} records would change.\n')
        if grand_changes:
            for ch in grand_changes:
                print(f'- {ch["file"]} record #{ch["record_index"]}:')
                if 'verse' in ch:
                    cur = ch['verse']['from']
                    upd = ch['verse']['to']
                    print(f'cur: "{_oneline(cur)}"')
                    print(f'upd: "{(_oneline(upd))}"')
                if 'reading' in ch:
                    cur = ch['reading']['from']
                    upd = ch['reading']['to']
                    print(f'cur: "{_oneline(cur)}"')
                    print(f'upd: "{_oneline(upd)}"')
        else:
            print('No changes detected.')
    else:
        print(f'Completed. Updated {grand_changed} of {grand_total} records.')
        print('Backups created as .bak for files that changed.')


if __name__ == '__main__':
    main()
