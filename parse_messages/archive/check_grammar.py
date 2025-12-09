#!/usr/bin/env python3
import os
import json
import re
import sys
from typing import Dict, Optional, Tuple, List

# Defaults (override via CLI)
DEFAULT_FIELDS = ['verse', 'reflection', 'prayer']
DEFAULT_LANG_CODE = 'en-US'
DEFAULT_SERVER_URL = 'http://localhost:8010'

SEPARATOR = '=' * 72


def script_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def read_json_file(path: str) -> Optional[Tuple[object, str]]:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        return json.loads(content), content
    except Exception:
        return None


def find_line_number_for_field(content: str, key: str, value: str) -> int:
    """
    Try to find a sensible line to open for code -g.
    First try an exact one-line match of the field, then fall back to the first line containing the key.
    """
    escaped_key = re.escape(key)
    escaped_val = re.escape(value)
    pattern = re.compile(
        r'^\s*"' + escaped_key + r'"\s*:\s*"' + escaped_val + r'"\s*(?:,|}|])',
        re.MULTILINE,
    )
    m = pattern.search(content)
    if m:
        return content.count('\n', 0, m.start()) + 1
    exact = f'"{key}": "{value}"'
    for i, line in enumerate(content.splitlines(), start=1):
        if exact in line:
            return i
    for i, line in enumerate(content.splitlines(), start=1):
        if f'"{key}"' in line:
            return i
    return 1


def init_grammar(lang_code: str, server_url: str):
    try:
        import language_tool_python as lt_mod

        tool = lt_mod.LanguageTool(lang_code, remote_server=server_url)
        print(f'LT client: {type(tool).__name__}')
        print(f'LT server: {server_url}')
        return tool
    except Exception as e:
        print(
            f'Error: language_tool_python unavailable or server not reachable ({e}).',
            file=sys.stderr,
        )
        print('Tip: ensure the Docker LT server is running and the port matches --server.')
        return None


def match_span(m):
    """
    Return (offset, length) robustly across language_tool_python versions.
    """
    offset = getattr(m, 'offset', None)
    length = getattr(m, 'errorLength', None)
    if offset is None:
        offset = getattr(m, 'offsetInContext', 0)
    if length is None:
        try:
            ctx = getattr(m, 'context', None) or getattr(m, 'contextForSureMatch', None)
            length = len(str(ctx)) if ctx else 0
        except Exception:
            length = 0
    try:
        return int(offset), int(length)
    except Exception:
        return 0, 0


def match_rule_id(m) -> str:
    return getattr(m, 'ruleId', None) or getattr(m, 'rule', None) or ''


def match_category_name(m) -> str:
    """
    Try to get human-friendly category (Grammar, Punctuation, etc.).
    """
    cat = getattr(m, 'ruleCategory', None)
    name = getattr(cat, 'name', None) if cat else None
    if not name:
        name = getattr(m, 'category', None)
    return (name or '').strip()


def match_issue_type(m) -> str:
    """
    Try to fetch the issue type (e.g., TYPO). Not always available.
    """
    it = getattr(m, 'ruleIssueType', None)
    return str(it or '').strip()


def match_message(m) -> str:
    rid = match_rule_id(m) or 'RULE'
    msg = getattr(m, 'message', None) or 'Issue'
    return f'Grammar ({rid}): {msg}'


def match_replacements(m, max_n: int = 3) -> str:
    reps = getattr(m, 'replacements', None) or []
    if not reps:
        return ''
    shown = ', '.join(reps[:max_n])
    more = '' if len(reps) <= max_n else f' (+{len(reps) - max_n} more)'
    return f'suggest: {shown}{more}'


def normalize_list(strs: Optional[List[str]]) -> List[str]:
    return [s.strip().lower() for s in (strs or []) if s.strip()]


def match_rule_filters(
    m,
    type_filter: Optional[str],
    rules_exact: List[str],
    rules_like: List[str],
    categories: List[str],
) -> bool:
    """
    Return True if match m passes all active filters (AND semantics across groups).
    Within a group:
      - rules_exact: exact ruleId match (case-insensitive)
      - rules_like: substring match over ruleId
      - categories: substring match over category name
      - type_filter: substring match over ruleId, category, or issue type
    """
    rid = (match_rule_id(m) or '').lower()
    cat = (match_category_name(m) or '').lower()
    itype = (match_issue_type(m) or '').lower()

    # rules_exact (if provided, must match exactly)
    if rules_exact:
        if rid not in rules_exact:
            return False

    # rules_like (if provided, must match any substring)
    if rules_like:
        if not any(sub in rid for sub in rules_like):
            return False

    # categories (if provided, must match any substring)
    if categories:
        if not any(sub in cat for sub in categories):
            return False

    # type_filter (broad filter over rid/cat/itype)
    if type_filter:
        t = type_filter.lower()
        if t not in rid and t not in cat and t not in itype:
            return False

    return True


def inspect_record(
    tool,
    obj: Dict,
    file_content: str,
    filename: str,
    fields_to_check: List[str],
    type_filter: Optional[str],
    rules_exact: List[str],
    rules_like: List[str],
    categories: List[str],
    show_all_suggestions: bool,
    limit: Optional[int],
    counter: Dict[str, int],
) -> None:
    if limit is not None and counter['total'] >= limit:
        return

    for field in fields_to_check:
        if limit is not None and counter['total'] >= limit:
            return
        val = obj.get(field)
        if not isinstance(val, str):
            continue
        text = val
        try:
            matches = tool.check(text)
        except Exception:
            matches = []
        for m in matches:
            if limit is not None and counter['total'] >= limit:
                return

            if not match_rule_filters(
                m,
                type_filter=type_filter,
                rules_exact=rules_exact,
                rules_like=rules_like,
                categories=categories,
            ):
                continue

            offset, length = match_span(m)
            start = max(0, offset - 20)
            end = min(len(text), offset + max(1, length) + 20)
            context = text[start:end].replace('\n', ' ')

            msg = match_message(m)
            cat = match_category_name(m)
            itype = match_issue_type(m)
            line = find_line_number_for_field(file_content, field, text)

            print(SEPARATOR)
            extras = []
            if cat:
                extras.append(f'category: {cat}')
            if itype:
                extras.append(f'type: {itype}')
            extras_str = f' [{"; ".join(extras)}]' if extras else ''
            print(f'{msg}{extras_str}')

            if show_all_suggestions:
                reps = getattr(m, 'replacements', None) or []
                if reps:
                    print(f'suggest (all): {", ".join(reps)}')
            else:
                s = match_replacements(m, max_n=3)
                if s:
                    print(s)

            print(f'snippet: ...{context}...')
            print(f'field  : {field}')
            print(f'code   : code -g {filename}:{line}')

            counter['total'] += 1


def main():
    import argparse

    ap = argparse.ArgumentParser(
        description='Grammar check JSON fields via local LanguageTool server (Docker). Filters by rules, categories; shows suggestions; supports limiting output.'
    )
    ap.add_argument(
        '--type',
        dest='type_filter',
        default=None,
        help="Broad substring filter over ruleId/category/issue type (e.g., 'punctuation', 'typo', 'EN_QUOTES')",
    )
    ap.add_argument(
        '--rules',
        nargs='*',
        default=None,
        help='Exact ruleIds to include (case-insensitive exact match). Example: EN_QUOTES EN_UNPAIRED_QUOTES',
    )
    ap.add_argument(
        '--rules-like',
        nargs='*',
        default=None,
        help='Substring filters for ruleIds (case-insensitive). Example: QUOTES APOSTROPHE',
    )
    ap.add_argument(
        '--categories',
        nargs='*',
        default=None,
        help='Substring filters for category names (case-insensitive). Example: punctuation grammar typography',
    )
    ap.add_argument(
        '--show-all-suggestions',
        action='store_true',
        help='Print all suggested replacements (default prints top 3)',
    )
    ap.add_argument('--limit', type=int, default=None, help='Stop after printing this many issues')
    ap.add_argument(
        '--fields',
        nargs='*',
        default=DEFAULT_FIELDS,
        help='Fields to check (default: verse reflection prayer)',
    )
    ap.add_argument(
        '--server',
        default=DEFAULT_SERVER_URL,
        help=f'LanguageTool server URL (default: {DEFAULT_SERVER_URL})',
    )
    ap.add_argument(
        '--lang',
        default=DEFAULT_LANG_CODE,
        help=f'Language code (default: {DEFAULT_LANG_CODE})',
    )
    args = ap.parse_args()

    server_url = args.server
    fields_to_check = args.fields
    lang_code = args.lang

    rules_exact = normalize_list(args.rules)
    rules_like = normalize_list(args.rules_like)
    categories = normalize_list(args.categories)

    tool = init_grammar(lang_code, server_url)
    if not tool:
        sys.exit(1)

    base = script_dir()
    total_counter = {'total': 0}
    files_seen = 0

    for name in sorted(os.listdir(base)):
        if not name.endswith('.json'):
            continue
        files_seen += 1
        loaded = read_json_file(os.path.join(base, name))
        if not loaded:
            continue
        data, content = loaded

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    inspect_record(
                        tool,
                        item,
                        content,
                        name,
                        fields_to_check=fields_to_check,
                        type_filter=args.type_filter,
                        rules_exact=rules_exact,
                        rules_like=rules_like,
                        categories=categories,
                        show_all_suggestions=args.show_all_suggestions,
                        limit=args.limit,
                        counter=total_counter,
                    )
                    if args.limit is not None and total_counter['total'] >= args.limit:
                        break
        elif isinstance(data, dict):
            inspect_record(
                tool,
                data,
                content,
                name,
                fields_to_check=fields_to_check,
                type_filter=args.type_filter,
                rules_exact=rules_exact,
                rules_like=rules_like,
                categories=categories,
                show_all_suggestions=args.show_all_suggestions,
                limit=args.limit,
                counter=total_counter,
            )
        if args.limit is not None and total_counter['total'] >= args.limit:
            break

    if files_seen == 0:
        print('No JSON files found', file=sys.stderr)
        sys.exit(1)

    print(SEPARATOR)
    print(f'Total grammar issues shown: {total_counter["total"]}')


if __name__ == '__main__':
    main()
