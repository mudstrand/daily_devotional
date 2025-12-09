#!/usr/bin/env python3
import argparse
import glob
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

Record = Dict[str, Any]


def expand_globs(patterns: List[str]) -> List[Path]:
    files: List[str] = []
    for pat in patterns:
        files.extend(glob.glob(pat, recursive=True))
    paths: List[Path] = []
    seen = set()
    for f in files:
        p = Path(f)
        if p.is_file() and p.suffix.lower() == '.json':
            rp = p.resolve()
            if rp not in seen:
                seen.add(rp)
                paths.append(p)
    return paths


def load_json(path: Path) -> Optional[Union[Record, List[Record]]]:
    try:
        with path.open('r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f'[WARN] Skipping invalid JSON: {path} ({e})')
        return None


def write_json(path: Path, data: Union[Record, List[Record]]) -> None:
    tmp = path.with_suffix(path.suffix + '.tmp')
    bak = path.with_suffix(path.suffix + '.bak')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    if not bak.exists():
        path.replace(bak)
    else:
        path.unlink(missing_ok=True)
    tmp.replace(path)


def normalize_psalms(value: Any, nocase: bool) -> Any:
    """
    Replace leading 'Psalm ' with 'Psalms '.
    Only if the field is a string and starts with that token.
    If nocase=True, perform a case-insensitive check on the leading token.
    """
    if not isinstance(value, str):
        return value
    s = value
    if nocase:
        # Case-insensitive: check the leading token
        if s[:6].lower() == 'psalm ':
            return 'Psalms ' + s[6:]
        return s
    else:
        # Case-sensitive, exact 'Psalm '
        if s.startswith('Psalm '):
            return 'Psalms ' + s[len('Psalm ') :]
        return s


def process_record(rec: Record, nocase: bool) -> Optional[str]:
    """
    Update rec['verse'] and rec['reading'] if they begin with Psalm -> Psalms.
    Returns a summary string if changes were made; otherwise None.
    """
    changed = []
    for key in ('verse', 'reading'):
        if key in rec and isinstance(rec[key], str):
            before = rec[key]
            after = normalize_psalms(before, nocase=nocase)
            if after != before:
                rec[key] = after
                changed.append(f'{key}: {before!r} -> {after!r}')
    if changed:
        return '; '.join(changed)
    return None


def process_file(path: Path, preview: bool, nocase: bool) -> int:
    data = load_json(path)
    if data is None:
        return 0

    is_list = isinstance(data, list)
    if not is_list and not isinstance(data, dict):
        print(f'[WARN] Unsupported JSON structure in {path}; expected object or list.')
        return 0

    records = data if is_list else [data]
    changes: List[str] = []
    updated_count = 0

    for idx, rec in enumerate(records):
        if not isinstance(rec, dict):
            continue
        summary = process_record(rec, nocase=nocase)
        if summary:
            updated_count += 1
            if preview:
                changes.append(f'  record[{idx if is_list else 0}]: {summary}')

    if preview:
        if changes:
            print(f'[PREVIEW] {path}: {updated_count} record(s) updated')
            for c in changes:
                print(c)
    else:
        if updated_count > 0:
            out = records if is_list else records[0]
            write_json(path, out)

    return updated_count


def main():
    ap = argparse.ArgumentParser(
        description="Normalize 'Psalm' -> 'Psalms' in verse and reading fields across JSON files."
    )
    ap.add_argument('--preview', action='store_true', help='Show changes without writing files')
    ap.add_argument(
        '--nocase',
        action='store_true',
        help="Case-insensitive matching for leading 'Psalm '",
    )
    ap.add_argument(
        'globs',
        nargs='+',
        help="Glob patterns for JSON files, e.g., './data/*.json' './more/**/*.json'",
    )
    args = ap.parse_args()

    paths = expand_globs(args.globs)
    if not paths:
        print('No JSON files matched the given patterns.')
        return

    total_files = 0
    total_updates = 0
    for p in paths:
        total_files += 1
        total_updates += process_file(p, preview=args.preview, nocase=args.nocase)

    if args.preview:
        print(f'Preview complete. Files examined: {total_files}, records needing update: {total_updates}')
    else:
        print(f'Completed. Files processed: {total_files}, records updated: {total_updates}')


if __name__ == '__main__':
    main()
