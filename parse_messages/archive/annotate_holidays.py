#!/usr/bin/env python3
import argparse
import glob
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Import your holiday module
try:
    from holiday import holiday_name_or_none
except Exception as e:
    raise SystemExit(f'Failed to import holiday.py: {e}')

Record = Dict[str, Any]


# -----------------------------
# Validation helpers
# -----------------------------
def validate_msg_date(value: Any) -> Optional[str]:
    """
    Validate that value is a YYYY-MM-DD string. Return normalized YYYY-MM-DD or None if invalid.
    """
    if value is None:
        return None
    s = str(value).strip()
    if len(s) == 10 and s[4] == '-' and s[7] == '-':
        try:
            datetime.strptime(s, '%Y-%m-%d')
            return s
        except Exception:
            return None
    return None


# -----------------------------
# IO helpers
# -----------------------------
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


# -----------------------------
# Core processing
# -----------------------------
def holiday_value_for_date(ymd: str) -> Optional[str]:
    h = holiday_name_or_none(ymd)
    return h.value if h is not None else None


def annotate_record(rec: Record, path: Path, idx: Optional[int]) -> Optional[str]:
    """
    Update the 'holiday' field based on msg_date. Returns a change description for preview,
    or None if no change. Raises SystemExit if msg_date is missing/invalid.
    """
    raw = rec.get('msg_date')
    ymd = validate_msg_date(raw)
    if not ymd:
        loc = f'{path}' if idx is None else f'{path} [record[{idx}]]'
        print(f'ERROR: msg_date missing or invalid (expected YYYY-MM-DD) in {loc}. Found: {raw!r}')
        sys.exit(1)

    new_val = holiday_value_for_date(ymd)
    old_val = rec.get('holiday', None)
    if old_val != new_val:
        rec['holiday'] = new_val
        return f'holiday {old_val!r} -> {new_val!r} (msg_date {ymd})'
    return None


def process_file(path: Path, preview: bool) -> int:
    data = load_json(path)
    if data is None:
        return 0

    if isinstance(data, dict):
        records = [data]
        is_list = False
    elif isinstance(data, list):
        records = [r for r in data if isinstance(r, dict)]
        is_list = True
    else:
        print(f'[WARN] Unsupported JSON structure in {path}; expected object or list.')
        return 0

    changes: List[str] = []
    updated_count = 0

    for idx, rec in enumerate(records):
        change = annotate_record(rec, path, None if not is_list else idx)
        if change:
            updated_count += 1
            if preview:
                changes.append(f'  record[{idx if is_list else 0}]: {change}')

    if preview:
        if changes:
            print(f'[PREVIEW] {path}: {updated_count} update(s)')
            for c in changes:
                print(c)
    else:
        if updated_count > 0:
            out = records if is_list else records[0]
            write_json(path, out)

    return updated_count


# -----------------------------
# CLI
# -----------------------------
def main():
    ap = argparse.ArgumentParser(
        description="Annotate JSON records with 'holiday' using msg_date and holiday.py (requires msg_date)."
    )
    ap.add_argument('--preview', action='store_true', help='Show changes without writing files')
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
        total_updates += process_file(p, preview=args.preview)

    if args.preview:
        print(f'Preview complete. Files examined: {total_files}, records needing update: {total_updates}')
    else:
        print(f'Completed. Files processed: {total_files}, records updated: {total_updates}')


if __name__ == '__main__':
    main()
