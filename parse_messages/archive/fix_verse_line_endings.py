#!/usr/bin/env python3
import argparse
import os
import re
import sys
from typing import List, Tuple

# Matches verse lines whose end has ) "<spaces> , <spaces> EOL
# We want to normalize that ending to )",
END_BAD = re.compile(r'\)\s*"\s*,\s*$')
# A "good" ending (allowed)
END_GOOD = re.compile(r'\)",\s*$')


def find_json_files(paths: List[str]) -> List[str]:
    files: List[str] = []
    if not paths:
        paths = ['.']
    for p in paths:
        if os.path.isdir(p):
            for root, _, names in os.walk(p):
                for n in names:
                    if n.endswith('.json'):
                        files.append(os.path.join(root, n))
        else:
            if p.endswith('.json') and os.path.isfile(p):
                files.append(p)
    return sorted(files)


def normalize_line(line: str) -> Tuple[bool, str]:
    """
    If the line contains "verse" and the ending is not normalized, fix it.
    Returns (changed, updated_line).
    """
    if '"verse"' not in line:
        return False, line

    # If already good, no change
    if END_GOOD.search(line):
        return False, line

    # If it matches the "bad" end pattern, normalize
    if END_BAD.search(line):
        upd = END_BAD.sub(')",', line.rstrip('\n')) + '\n'
        if upd != line:
            return True, upd
        return False, line

    # If the line ends with a bare right paren or has whitespace before the closing quote/comma
    # but doesn't strictly match END_BAD, we can try a broader fix:
    # 1) Locate the last right paren and ensure the canonical ending is used.
    # Only do this if the line looks like it tries to put a reference at the end (has a closing paren and a quote somewhere near the end).
    # Keep this conservative to avoid false positives.
    tail = line.rstrip('\n')
    # Accept cases like ... ) " ,  ... or ... )  " , ... or ... ) ",<spaces><garbage>
    m = re.search(r'\)\s*"\s*,\s*$', tail)
    if m:
        # This would have been caught by END_BAD; fallback path retained for clarity
        upd = re.sub(r'\)\s*"\s*,\s*$', ')",', tail) + '\n'
        if upd != line:
            return True, upd

    # Handle edge cases like: ... )" (missing comma) or ... )  NIV", etc.
    # If line ends with )" followed by extra non-comma junk, do not alter here to avoid content loss.
    # The script is intentionally minimal and safe. Extend here if you want more aggressive fixes.

    return False, line


def process_file(path: str, preview: bool) -> int:
    """
    Process a single file. Returns number of changed lines.
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        print(f'[ERROR] Unable to read {path}: {e}', file=sys.stderr)
        return 0

    changed = 0
    updated: List[str] = []
    to_report: List[Tuple[str, str]] = []

    for line in lines:
        ch, upd = normalize_line(line)
        if ch:
            changed += 1
            to_report.append((line.rstrip('\n'), upd.rstrip('\n')))
            updated.append(upd)
        else:
            updated.append(upd)

    if changed == 0:
        return 0

    # Report
    for cur, upd in to_report:
        print(f'cur: {cur}')
        print(f'upd: {upd}')
        print('')

    # Write only if not preview
    if not preview:
        backup = f'{path}.bak'
        if not os.path.exists(backup):
            try:
                with open(backup, 'w', encoding='utf-8') as bf:
                    bf.writelines(lines)
            except Exception as e:
                print(f'[ERROR] Cannot write backup {backup}: {e}', file=sys.stderr)
                return 0
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.writelines(updated)
        except Exception as e:
            print(f'[ERROR] Cannot write {path}: {e}', file=sys.stderr)
            return 0

    return changed


def main():
    ap = argparse.ArgumentParser(
        description='Normalize verse lines to end with )", by removing whitespace between ) and ", and before the comma. Prints cur/upd for each change. In non-preview mode, files are updated and .bak backups are created once per file.'
    )
    ap.add_argument('--preview', action='store_true', help='Preview changes only (no file writes)')
    ap.add_argument(
        'paths',
        nargs='*',
        help='Files or directories to scan (default: current directory)',
    )
    args = ap.parse_args()

    files = find_json_files(args.paths)
    if not files:
        print('No JSON files found.', file=sys.stderr)
        sys.exit(1)

    total_changed = 0
    for fp in files:
        c = process_file(fp, preview=args.preview)
        if c > 0:
            print(f'-- {fp}: {c} line(s) {"would change" if args.preview else "changed"} --\n')
        total_changed += c

    if args.preview:
        print(f'Preview complete. {total_changed} line(s) would change.')
    else:
        print(f'Update complete. {total_changed} line(s) changed.')


if __name__ == '__main__':
    main()
