#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
from typing import Any, Iterable, Tuple


def find_line_number_for_subject(content: str, subject_value: str) -> int:
    """
    Return 1-based line number where "subject": "<subject_value>" appears.
    Works even when the subject key is followed by other keys on the same line.
    Falls back to a simpler substring search if the regex doesn't match.
    """
    escaped = re.escape(subject_value)
    # Match:   "subject": "value"   followed by comma/brace/bracket (same line)
    pattern_loose = re.compile(r'^\s*"subject"\s*:\s*"' + escaped + r'"\s*(?:,|}|])', re.MULTILINE)
    m = pattern_loose.search(content)
    if m:
        return content.count('\n', 0, m.start()) + 1

    # Fallback: line-wise search for the exact JSON snippet
    lines = content.splitlines()
    needle = f'"subject": "{subject_value}"'
    for idx, line in enumerate(lines, start=1):
        if needle in line:
            return idx
    return -1


def load_json(filepath: str) -> Tuple[Any, str]:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    return json.loads(content), content


def subject_matches(value: Any, query: str, case_sensitive: bool, use_regex: bool) -> bool:
    if not isinstance(value, str):
        return False
    if use_regex:
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            return re.search(query, value, flags) is not None
        except re.error as e:
            print(f"Invalid regex '{query}': {e}", file=sys.stderr)
            sys.exit(2)
    return (query in value) if case_sensitive else (query.lower() in value.lower())


def iter_targets(paths: Iterable[str], recursive: bool) -> Iterable[str]:
    """
    Yield absolute paths to .json files from provided files/dirs.
    Deduplicates results.
    """
    seen = set()
    for p in paths:
        if os.path.isfile(p) and p.endswith('.json'):
            ap = os.path.abspath(p)
            if ap not in seen:
                seen.add(ap)
                yield ap
        elif os.path.isdir(p):
            if recursive:
                for root, _, files in os.walk(p):
                    for name in files:
                        if name.endswith('.json'):
                            ap = os.path.abspath(os.path.join(root, name))
                            if ap not in seen:
                                seen.add(ap)
                                yield ap
            else:
                # Non-recursive: only the immediate directory
                try:
                    for name in os.listdir(p):
                        if name.endswith('.json'):
                            ap = os.path.abspath(os.path.join(p, name))
                            if ap not in seen:
                                seen.add(ap)
                                yield ap
                except FileNotFoundError:
                    continue


def handle_file(
    filepath: str,
    query: str,
    case_sensitive: bool,
    use_regex: bool,
    print_subject: bool,
) -> None:
    try:
        data, content = load_json(filepath)
    except Exception:
        return

    def emit(subject_str: str):
        line = find_line_number_for_subject(content, subject_str)
        if line != -1:
            fname = os.path.basename(filepath)
            if print_subject:
                print(f'{subject_str}: code -g {fname}:{line}')
            else:
                print(f'code -g {fname}:{line}')

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and 'subject' in item:
                val = item.get('subject')
                if subject_matches(val, query, case_sensitive, use_regex):
                    emit(val)
    elif isinstance(data, dict):
        val = data.get('subject')
        if subject_matches(val, query, case_sensitive, use_regex):
            emit(val)


def main():
    p = argparse.ArgumentParser(
        description='Search "subject" values in JSON files and print VS Code jump commands (filename only).'
    )
    p.add_argument('query', help='Substring or regex to search in subject')
    p.add_argument(
        'paths',
        nargs='*',
        default=['.'],
        help='Files or directories to search (default: current dir)',
    )
    p.add_argument('--regex', action='store_true', help='Treat query as a regular expression')
    p.add_argument(
        '--case-sensitive',
        action='store_true',
        help='Case-sensitive match (default: case-insensitive)',
    )
    p.add_argument('--recursive', '-r', action='store_true', help='Recurse into subdirectories')
    p.add_argument(
        '--no-subject',
        action='store_true',
        help="Only print 'code -g filename:line' (omit subject text)",
    )
    args = p.parse_args()

    any_json = False
    for fp in sorted(iter_targets(args.paths, args.recursive)):
        any_json = True
        handle_file(
            fp,
            args.query,
            args.case_sensitive,
            args.regex,
            print_subject=not args.no_subject,
        )

    if not any_json:
        print('No JSON files found in given paths', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
