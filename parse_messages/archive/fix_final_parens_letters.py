#!/usr/bin/env python3
import argparse
import os
import re
import sys
from typing import List, Optional, Tuple

# Detect verse lines quickly
VERSE_KEY = '"verse"'

# Find the FINAL (...) on the line, capturing inner text, with optional trailing tag and JSON )
# We capture up to the closing ), then allow optional spaces, optional letters (a tag), then a closing quote and comma to EOL.
# We'll match from near the end for robustness.
FINAL_PARENS = re.compile(r'\(([^()]*)\)\s*(?:(?:[A-Za-z][A-Za-z ]*)\s*)?("\s*,\s*$)')

# "Letters-only" (case-insensitive), allowing internal spaces only. No digits or punctuation.
LETTERS_ONLY = re.compile(r'^[A-Za-z ]+$')

# Normalize end-of-line ) ", to )", at EOL
END_BAD = re.compile(r'\)\s*"\s*,\s*$')
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


def extract_final_parens(line: str) -> Optional[Tuple[str, str, int, int]]:
    """
    Return (inner_text, suffix, start_index, end_index) for the FINAL (...) group:
    - inner_text: content inside final parens
    - suffix: the trailing '",...' part matched by FINAL_PARENS group 2
    - start_index/end_index: indices of the '(' and ')' positions in the original line
    """
    # Search from the right using regex; FINAL_PARENS expects the trailing '",'
    m = FINAL_PARENS.search(line)
    if not m:
        return None
    inner = m.group(1)
    suffix = m.group(2)
    # To compute indices of the parens, find the literal paren match by walking backwards
    # We'll locate the last ')' before the suffix start, then find the matching '(' from that slice
    suffix_pos = m.start(2)  # start of '",'
    right_slice = line[:suffix_pos]
    # find last ')' in right_slice
    rparen_idx = right_slice.rfind(')')
    if rparen_idx == -1:
        return None
    # now find matching '(' by scanning backwards in substring
    # since it's simple, just find the last '(' before rparen_idx in the overall line
    lparen_idx = line.rfind('(', 0, rparen_idx + 1)
    if lparen_idx == -1:
        return None
    return inner, suffix, lparen_idx, rparen_idx


def normalize_ending(line: str) -> Tuple[bool, str]:
    """
    If the JSON verse line ending is ) ", normalize to )", (no whitespace between paren and quote/comma).
    Returns (changed, updated_line).
    """
    if VERSE_KEY not in line:
        return False, line
    if END_GOOD.search(line):
        return False, line
    if END_BAD.search(line):
        upd = END_BAD.sub(')",', line.rstrip('\n')) + '\n'
        return (upd != line), upd
    return False, line


def fix_letters_only_final_parens(line: str, tag: str) -> Tuple[bool, str]:
    """
    If final parentheses contain letters only (allow spaces), replace that final (...) with (tag).
    Returns (changed, updated_line).
    """
    if VERSE_KEY not in line:
        return False, line

    info = extract_final_parens(line)
    if not info:
        return False, line

    inner, suffix, lparen_idx, rparen_idx = info
    inner_stripped = inner.strip()
    if not inner_stripped:
        return False, line

    if LETTERS_ONLY.match(inner_stripped):
        # Replace content in final (...) with the canonical tag
        before = line[:lparen_idx]
        after = line[rparen_idx + 1 :]  # includes suffix
        new_line = f'{before}({tag}){after}'
        return (new_line != line), new_line

    return False, line


def process_file(path: str, preview: bool, tag: str, fix_ending: bool) -> int:
    """
    Process one file:
    - Fix letters-only final parens to (tag)
    - Optionally normalize the end-of-line to )",
    - Print cur/upd pairs for each change
    - In non-preview mode, write file and .bak backup once.

    Returns count of changed lines.
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        print(f'[ERROR] Unable to read {path}: {e}', file=sys.stderr)
        return 0

    changed = 0
    updated_lines: List[str] = []
    reports: List[Tuple[str, str]] = []

    for line in lines:
        orig = line
        ch1, line = fix_letters_only_final_parens(line, tag)
        ch2 = False
        if fix_ending:
            ch2, line = normalize_ending(line)
        if ch1 or ch2:
            changed += 1
            reports.append((orig.rstrip('\n'), line.rstrip('\n')))
        updated_lines.append(line)

    if changed == 0:
        return 0

    # Report
    for cur, upd in reports:
        print(f'cur: {cur}')
        print(f'upd: {upd}')
        print('')

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
                f.writelines(updated_lines)
        except Exception as e:
            print(f'[ERROR] Cannot write {path}: {e}', file=sys.stderr)
            return 0

    return changed


def main():
    ap = argparse.ArgumentParser(
        description='Fix verse lines whose FINAL (...) contains letters only by replacing that (...) with a canonical tag (e.g., NIV). Optionally normalize line ending to )",. Prints cur/upd in preview; writes files with .bak backup otherwise.'
    )
    ap.add_argument('--preview', action='store_true', help='Preview changes only (no writes)')
    ap.add_argument(
        '--tag',
        default='NIV',
        help='Canonical tag to enforce in the final parentheses (default: NIV)',
    )
    ap.add_argument('--fix-ending', action='store_true', help='Also normalize end-of-line to )",')
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
        c = process_file(fp, preview=args.preview, tag=args.tag, fix_ending=args.fix_ending)
        if c > 0:
            print(f'-- {fp}: {c} line(s) {"would change" if args.preview else "changed"} --\n')
        total_changed += c

    if args.preview:
        print(f'Preview complete. {total_changed} line(s) would change.')
    else:
        print(f'Update complete. {total_changed} line(s) changed.')


if __name__ == '__main__':
    main()
