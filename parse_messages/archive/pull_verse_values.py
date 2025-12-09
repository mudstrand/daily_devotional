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


def extract_verses_from_file(path: Path, include_index: bool, include_message_id: bool) -> int:
    """
    Print one line per record with its verse value.
    Output formats:
      Default:                               verse
      --include-index:                       filename:record_index<TAB>verse
      --include-index --include-message-id:  filename:record_index<TAB>message_id<TAB>verse
      --include-message-id (without index):  filename<TAB>message_id<TAB>verse
    Returns the number of records processed in this file.
    """
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
        records, _, _ = load_records(raw, path)
    except Exception as e:
        print(f'[ERROR] {path}: cannot read/parse JSON: {e}', file=sys.stderr)
        return 0

    count = 0
    for idx, rec in enumerate(records, start=1):
        if not isinstance(rec, dict):
            continue
        verse = rec.get('verse', '')
        verse_str = verse if isinstance(verse, str) else ''
        verse_str = ' '.join(verse_str.split()).strip()

        # Build line
        if include_index and include_message_id:
            mid = rec.get('message_id', '')
            mid_str = mid if isinstance(mid, str) else ''
            print(f'{path}:{idx}\t{mid_str}\t{verse_str}')
        elif include_index:
            print(f'{path}:{idx}\t{verse_str}')
        elif include_message_id:
            mid = rec.get('message_id', '')
            mid_str = mid if isinstance(mid, str) else ''
            print(f'{path}\t{mid_str}\t{verse_str}')
        else:
            print(verse_str)

        count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description="Extract the 'verse' value from all records in JSON files.")
    parser.add_argument('files', nargs='+', help='One or more JSON files (e.g., *.json)')
    parser.add_argument(
        '--include-index',
        action='store_true',
        help='Prefix each line with filename:record_index and a TAB',
    )
    parser.add_argument(
        '--include-message-id',
        action='store_true',
        help='Include the message_id between prefix and verse (tab-separated)',
    )
    args = parser.parse_args()

    total = 0
    for file_arg in args.files:
        path = Path(file_arg)
        if not path.exists():
            print(f'[ERROR] {path}: not found', file=sys.stderr)
            continue
        total += extract_verses_from_file(path, args.include_index, args.include_message_id)

    # Exit 0 regardless; this is a read-out tool
    sys.exit(0)


if __name__ == '__main__':
    main()
