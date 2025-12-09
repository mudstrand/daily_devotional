#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
from typing import Any, List, Tuple, Iterable

LAST_PARENS = re.compile(r'\(([^()]*)\)(?!.*\([^()]*\))')


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


def extract_last_parens(text: str) -> str | None:
    m = LAST_PARENS.search(text)
    return m.group(1).strip() if m else None


def iter_verses(doc: Any) -> Iterable[str]:
    def walk(node: Any):
        if isinstance(node, dict):
            if 'verse' in node and isinstance(node['verse'], str):
                yield node['verse']
            for v in node.values():
                if isinstance(v, (dict, list)):
                    yield from walk(v)
        elif isinstance(node, list):
            for v in node:
                yield from walk(v)

    yield from walk(doc)


def process_file(path: str) -> int:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            doc = json.load(f)
    except Exception as e:
        print(f'[ERROR] Unable to read {path}: {e}', file=sys.stderr)
        return 0

    base = os.path.basename(path)
    count = 0

    for verse in iter_verses(doc):
        inner = extract_last_parens(verse)
        if inner is None:
            continue
        # print(f"{base}: {inner}")
        print(f'{inner}')
        count += 1

    return count


def main():
    ap = argparse.ArgumentParser(description='Extract final (...) content from the "verse" field in JSON documents.')
    ap.add_argument('paths', nargs='*', help='Files or directories (default: current directory)')
    args = ap.parse_args()

    files = find_json_files(args.paths)
    if not files:
        print('No JSON files found.', file=sys.stderr)
        sys.exit(1)

    total = 0
    for fp in files:
        total += process_file(fp)

    # If you truly want ONLY "<filename>: <content>" lines, comment out the next line.
    # print(f"Done. {total} item(s) found.")


if __name__ == '__main__':
    main()
