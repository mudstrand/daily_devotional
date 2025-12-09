#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple, Union

# --------------- Configuration ---------------
VERSE_FIELD = 'verse'
READING_FIELD = 'reading'

# Book name fixes (case-insensitive keys)
BOOK_FIXES = {
    'matth': 'Matthew',
    'matt': 'Matthew',
    'jn': 'John',
    'jhn': 'John',
    'ps': 'Psalm',
    'psa': 'Psalm',
    'psalm': 'Psalm',
    'psalms': 'Psalm',
    'prov': 'Proverbs',
    'song of songs': 'Song of Solomon',
    'song of solomon': 'Song of Solomon',
    'songs': 'Song of Solomon',
    '1cor': '1 Corinthians',
    '2cor': '2 Corinthians',
    '1thes': '1 Thessalonians',
    '2thes': '2 Thessalonians',
    '1tim': '1 Timothy',
    '2tim': '2 Timothy',
    '1pet': '1 Peter',
    '2pet': '2 Peter',
    '1john': '1 John',
    '2john': '2 John',
    '3john': '3 John',
    'rev': 'Revelation',
    'heb': 'Hebrews',
    'rom': 'Romans',
    'gal': 'Galatians',
    'eph': 'Ephesians',
    'phil': 'Philippians',
    'col': 'Colossians',
    'tit': 'Titus',
    'philem': 'Philemon',
    'gen': 'Genesis',
    'ex': 'Exodus',
    'deut': 'Deuteronomy',
    'eccl': 'Ecclesiastes',
    'lam': 'Lamentations',
}

# --------------- Regex helpers ---------------
REF_SPLIT_RE = re.compile(r'\s*,\s*')
PART_SUFFIX_RE = re.compile(r'^(\d+)([abc])$', re.IGNORECASE)

# Match Book Chapter:Verses
BOOK_CHAPTER_VERSES_RE = re.compile(r'^\s*(?P<book>[\dA-Za-z ]+?)\s+(?P<chapter>\d+):(?P<rest>.+?)\s*$')

# Match Book Chapter (whole chapter, no verses)
BOOK_WHOLE_CHAPTER_RE = re.compile(r'^\s*(?P<book>[\dA-Za-z ]+?)\s+(?P<chapter>\d+)\s*$')

TRAILING_JUNK_RE = re.compile(r"""[\'\"\.\s]+$""")
READING_AI_ANY = re.compile(r"""(^|\s)\bAI\b(\s|\.|,|;|:|$)""", re.IGNORECASE)

# Detect presence of a chapter ref (with or without verses), tolerant to simple wrappers
CHAPTER_PRESENT_RE = re.compile(
    r"""^\s*[\(\[\{"]?\s*([1-3]?\s*[A-Za-z][A-Za-z ]+?)\s+(\d+)(?::[\d,\-\sabc]+)?\s*[\)\]\}"]?\s*$""",
    re.IGNORECASE,
)


# --------------- Normalization core ---------------
def fix_book_name(raw_book: str) -> str:
    s = ' '.join(raw_book.split()).strip()
    return BOOK_FIXES.get(s.lower(), s)


def strip_outer_wrappers(s: str) -> str:
    s = s.strip()
    pairs = [('(', ')'), ('[', ']'), ('{', '}')]
    for l, r in pairs:
        if s.startswith(l) and s.endswith(r):
            return s[1:-1].strip()
    return s


def strip_part_suffix(token: str) -> str:
    m = PART_SUFFIX_RE.match(token.strip())
    return m.group(1) if m else token.strip()


def clean_token_strip_abc(token: str) -> str:
    t = TRAILING_JUNK_RE.sub('', token.strip())
    if not t:
        raise ValueError(f'Empty verse token after cleaning from {token!r}')
    if '-' in t:
        if t.count('-') != 1:
            raise ValueError(f'Invalid range (multiple hyphens) in token {token!r}')
        a, b = t.split('-', 1)
        a_num, b_num = strip_part_suffix(a), strip_part_suffix(b)
        if not a_num.isdigit() or not b_num.isdigit():
            raise ValueError(f'Range endpoints must be numeric in token {token!r}')
        if int(a_num) > int(b_num):
            raise ValueError(f'Range start > end in token {token!r}')
        return f'{int(a_num)}-{int(b_num)}'
    v = strip_part_suffix(t)
    if not v.isdigit():
        raise ValueError(f'Verse number must be numeric in token {token!r}')
    return str(int(v))


def has_descending_range_in_rest(rest: str) -> Union[str, None]:
    """
    Return the first descending range token like '27-20' if found, else None.
    Accepts suffix letters (a/b/c) but compares numeric parts.
    """
    for token in REF_SPLIT_RE.split(rest):
        t = token.strip()
        if '-' in t and t.count('-') == 1:
            a, b = t.split('-', 1)
            a_num = strip_part_suffix(a)
            b_num = strip_part_suffix(b)
            if a_num.isdigit() and b_num.isdigit() and int(a_num) > int(b_num):
                return t
    return None


def normalize_reference_string(ref_line: str) -> str:
    s = ref_line.strip().strip('"').strip("'").strip()
    s = strip_outer_wrappers(s)
    if not s:
        raise ValueError('Reference is empty')
    m = BOOK_CHAPTER_VERSES_RE.match(s)
    if not m:
        raise ValueError(f'Cannot parse book/chapter/verses from: {ref_line!r}')
    book = fix_book_name(m.group('book'))
    chapter = m.group('chapter').strip()
    rest = m.group('rest').strip()
    if not rest:
        raise ValueError(f'No verse component after chapter in: {ref_line!r}')

    # Detect descending ranges early with a clear message
    bad = has_descending_range_in_rest(rest)
    if bad:
        raise ValueError(f'descending range {bad!r}')

    parts = [p for p in REF_SPLIT_RE.split(rest) if p.strip()]
    if not parts:
        raise ValueError(f'No verse parts detected in: {ref_line!r}')
    cleaned = [clean_token_strip_abc(p) for p in parts]
    return f'{book} {int(chapter)}:{",".join(cleaned)}'


# --------------- Reading helpers ---------------
def contains_ai_marker(value: Union[str, List[str]]) -> bool:
    if isinstance(value, str):
        return bool(READING_AI_ANY.search(value))
    if isinstance(value, list):
        return any(isinstance(v, str) and READING_AI_ANY.search(v or '') for v in value)
    return False


def contains_chapter_reference(value: Union[str, List[str]]) -> bool:
    def has_chapter(s: str) -> bool:
        s = s.strip()
        return bool(CHAPTER_PRESENT_RE.match(s))

    if isinstance(value, str):
        return has_chapter(value)
    if isinstance(value, list):
        return any(isinstance(v, str) and has_chapter(v) for v in value)
    return False


def is_whole_chapter(s: str) -> bool:
    core = strip_outer_wrappers(s.strip())
    return (':' not in core) and bool(BOOK_WHOLE_CHAPTER_RE.match(core))


def normalize_reading_value(
    value: Union[str, List[str]],
) -> Union[str, List[str], None]:
    """
    Normalize reading per rules:
    - Empty/whitespace -> None (skip)
    - Contains AI -> raise RuntimeError to be handled up the stack
    - If contains a chapter reference:
        * If whole chapter -> return original unchanged
        * If chapter:verses -> normalize
    - Else -> return original unchanged
    """
    if isinstance(value, str):
        raw = value
        if raw.strip() == '':
            return None  # skip
        if contains_ai_marker(raw):
            raise RuntimeError('reading contains AI marker')
        if contains_chapter_reference(raw):
            if is_whole_chapter(raw):
                return raw  # leave as-is
            # Normalize chapter:verses (may raise ValueError for descending ranges)
            return normalize_reference_string(raw)
        # Not a recognizable chapter ref: leave untouched
        return raw

    if isinstance(value, list):
        # Error on AI anywhere
        if any(isinstance(v, str) and contains_ai_marker(v) for v in value):
            raise RuntimeError('reading contains AI marker')
        # If all empty, skip
        if all((isinstance(v, str) and v.strip() == '') for v in value):
            return None
        out: List[str] = []
        changed = False
        for item in value:
            if not isinstance(item, str):
                continue
            if item.strip() == '':
                out.append(item)
                continue
            if contains_chapter_reference(item):
                if is_whole_chapter(item):
                    out.append(item)  # leave as-is
                else:
                    norm = normalize_reference_string(item)  # may raise ValueError for descending ranges
                    out.append(norm)
                    if norm != item:
                        changed = True
            else:
                out.append(item)  # leave untouched
        return out if changed else value

    # Non-string/list: leave unchanged
    return value


# --------------- File processing ---------------
def load_json_records(data: Any, filename: Path):
    if isinstance(data, list):
        return data, None, None
    if isinstance(data, dict):
        list_keys = [k for k, v in data.items() if isinstance(v, list)]
        if len(list_keys) == 1:
            return data[list_keys[0]], data, list_keys[0]
        raise ValueError(f'{filename}: expected a list or a dict with a single list of records')
    raise ValueError(f'{filename}: unsupported JSON structure')


def update_record(
    rec: Dict[str, Any], preview: bool, continue_on_error: bool, path: Path, idx: int
) -> Tuple[Dict[str, Any], List[Tuple[str, Dict[str, str]]]]:
    rec_copy = dict(rec)
    preview_entries: List[Tuple[str, Dict[str, str]]] = []

    # Normalize verse
    if VERSE_FIELD in rec_copy and isinstance(rec_copy[VERSE_FIELD], str) and rec_copy[VERSE_FIELD].strip():
        before = rec_copy[VERSE_FIELD]
        try:
            after = normalize_reference_string(before)
        except ValueError as e:
            msg = f'{path}:{idx} invalid {VERSE_FIELD}: {e}'
            if preview and not continue_on_error:
                raise RuntimeError(msg)
            else:
                print(f'[ERROR] {msg}')
                if preview:
                    preview_entries.append((VERSE_FIELD, {'error': str(e), 'before': before}))
        else:
            if after != before:
                rec_copy[VERSE_FIELD] = after
                if preview:
                    preview_entries.append((VERSE_FIELD, {'before': before, 'after': after}))

    # Normalize reading per rules
    if READING_FIELD in rec_copy and isinstance(rec_copy[READING_FIELD], (str, list)):
        before_r = rec_copy[READING_FIELD]

        # Skip empty readings silently
        if (isinstance(before_r, str) and before_r.strip() == '') or (
            isinstance(before_r, list) and all((isinstance(v, str) and v.strip() == '') for v in before_r)
        ):
            pass
        else:
            try:
                norm_r = normalize_reading_value(before_r)
            except RuntimeError as e:
                # AI marker detected
                msg = f'{path}:{idx} {str(e)}'
                if preview and not continue_on_error:
                    raise RuntimeError(msg)
                else:
                    print(f'[ERROR] {msg}')
                    if preview:
                        before_str = (
                            before_r
                            if isinstance(before_r, str)
                            else '; '.join([v for v in before_r if isinstance(v, str)])
                        )
                        preview_entries.append((READING_FIELD, {'error': str(e), 'before': before_str}))
            except ValueError as e:
                # e.g., descending range
                msg = f'{path}:{idx} invalid {READING_FIELD}: {e}'
                if preview and not continue_on_error:
                    raise RuntimeError(msg)
                else:
                    print(f'[ERROR] {msg}')
                    if preview:
                        before_str = (
                            before_r
                            if isinstance(before_r, str)
                            else '; '.join([v for v in before_r if isinstance(v, str)])
                        )
                        preview_entries.append((READING_FIELD, {'error': str(e), 'before': before_str}))
            else:
                # None means skip; otherwise apply if changed
                if norm_r is not None and norm_r != before_r:
                    rec_copy[READING_FIELD] = norm_r
                    if preview:

                        def to_str(v: Union[str, List[str]]) -> str:
                            return v if isinstance(v, str) else '; '.join(v)

                        preview_entries.append(
                            (
                                READING_FIELD,
                                {'before': to_str(before_r), 'after': to_str(norm_r)},
                            )
                        )

    return rec_copy, preview_entries


def main():
    parser = argparse.ArgumentParser(
        description='Normalize "verse". For "reading": leave whole-chapter refs; normalize chapter:verses; fail on AI; clear error for descending ranges.'
    )
    parser.add_argument('files', nargs='+', help='One or more JSON files (e.g., *.json)')
    parser.add_argument(
        '--preview',
        action='store_true',
        help='Show changes without writing files (fail-fast).',
    )
    parser.add_argument(
        '--continue-on-error',
        action='store_true',
        help='In preview, log errors but continue.',
    )
    args = parser.parse_args()

    for file_arg in args.files:
        path = Path(file_arg)
        if not path.exists():
            print(f'[ERROR] Not found: {path}')
            sys.exit(2)

        try:
            raw = json.loads(path.read_text(encoding='utf-8'))
            records, container, key = load_json_records(raw, path)
        except Exception as e:
            print(f'[ERROR] {path}: cannot read/parse JSON: {e}')
            sys.exit(2)

        updated_records: List[Dict[str, Any]] = []
        file_preview: List[Tuple[int, List[Tuple[str, Dict[str, str]]]]] = []

        try:
            for idx, rec in enumerate(records, start=1):
                if not isinstance(rec, dict):
                    updated_records.append(rec)
                    continue
                upd, entries = update_record(rec, args.preview, args.continue_on_error, path, idx)
                updated_records.append(upd)
                if entries:
                    file_preview.append((idx, entries))
        except RuntimeError as e:
            print(f'[ERROR] {e}')
            sys.exit(2)

        if args.preview:
            if file_preview:
                print(f'\n=== Preview: {path} ===')
                sep = '=' * 50
                for idx, entries in file_preview:
                    print(sep)
                    print(f'Record {idx}:')
                    for field, payload in entries:
                        if 'error' in payload:
                            print(f'- {field}: ERROR: {payload["error"]}')
                            if 'before' in payload:
                                print(f'  before: {payload["before"]}')
                        else:
                            print(f'- {field}:')
                            print(f'  before: {payload["before"]}')
                            print(f'  after : {payload["after"]}')
                print(sep)
            continue

        try:
            if container is None:
                out = updated_records
            else:
                container[key] = updated_records
                out = container
            path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f'[OK] Updated: {path}')
        except Exception as e:
            print(f'[ERROR] {path}: failed to write output: {e}')
            sys.exit(2)


if __name__ == '__main__':
    main()
