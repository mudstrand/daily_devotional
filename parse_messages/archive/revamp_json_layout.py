#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

SEPARATOR = '=' * 50

# >>> You can edit this list to add more allowed terminal characters for verse_text
VALID_VERSE_END_CHARS = [
    '.',  # period
    '"',  # straight double quote
    '?',
    '!',
    ',',
    ';',
    # Add more if needed: "”", "’", "!", "?", "…"
]

# Verse: text (reference) with optional trailing source token (NIV, ESV, etc.)
VERSE_PATTERN_WITH_SOURCE = re.compile(
    r"""^(?P<text>.*?)\s*[\(\[]\s*(?P<ref>[^()\[\]]+?)\s*[\)\]]\s*(?P<src>[A-Za-z][A-Za-z0-9\.\-\+/]*)?\.?\s*$""",
    re.DOTALL,
)

# Reading acceptance:
#   - Clean reading without AI suffix
#   - Or ends with ' AI' (case-insensitive) with optional trailing period
READING_AI_SUFFIX = re.compile(r"""^(?P<reading>.*?\S)\s+AI\.?\s*$""", re.IGNORECASE)
READING_CLEAN = re.compile(r"""^.*\S$""")

NEW_FIELDS = [
    'verse_text',
    'reading_text',
    'original_verse_text',
    'original_verse',
    'original_reflection_text',
    'original_reading_text',
    'original_subject',
    'verse_source',
    'original_verse_source',
    'reading_source',
    'original_reading',
]


def extract_verse_parts(verse_value: str) -> Tuple[str, str, str, bool]:
    """
    Split 'verse' into verse_text, reference, and optional source.
    Returns (verse_text, reference, source, matched)
    """
    if not isinstance(verse_value, str):
        return ('', '', '', False)
    candidate = verse_value.strip()
    m = VERSE_PATTERN_WITH_SOURCE.match(candidate)
    if not m:
        return ('', '', '', False)
    verse_text = (m.group('text') or '').strip()
    verse_ref = (m.group('ref') or '').strip()
    verse_src = (m.group('src') or '').strip()
    return (verse_text, verse_ref, verse_src, True)


def normalize_source_token(src: str) -> str:
    if not src:
        return ''
    s = src.strip().rstrip('.')
    return s.upper()


def handle_reading(rec: Dict[str, Any], changes: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Process 'reading' for AI suffix and populate fields.
    Returns (ok, error_message). ok=False indicates a parse failure.
    """
    reading_val = rec.get('reading', '')

    if not isinstance(reading_val, str):
        return (False, 'reading is not a string')

    reading = reading_val.strip()
    if reading == '':
        # Empty reading is acceptable; still set defaults
        if 'ai_reading' not in rec:
            rec['ai_reading'] = False
            changes['ai_reading'] = False
        if not rec.get('original_reading'):
            rec['original_reading'] = ''
            changes['original_reading'] = '(empty)'
        if not rec.get('original_reading_text'):
            rec['original_reading_text'] = ''
            changes['original_reading_text'] = '(empty)'
        return (True, '')

    m_ai = READING_AI_SUFFIX.match(reading)
    if m_ai:
        # AI-generated reading
        cleaned = m_ai.group('reading').strip()
        if cleaned != rec.get('reading'):
            rec['reading'] = cleaned
            changes['reading'] = cleaned
        if rec.get('ai_reading') is not True:
            rec['ai_reading'] = True
            changes['ai_reading'] = True
        if rec.get('reading_source') != 'AI':
            rec['reading_source'] = 'AI'
            changes['reading_source'] = 'AI'
        if not rec.get('original_reading_text'):
            rec['original_reading_text'] = reading_val
            changes['original_reading_text'] = '(copied from reading before AI cleanup)'
        return (True, '')

    # Must be clean reading without AI suffix
    if not READING_CLEAN.match(reading):
        return (False, 'reading failed to match expected pattern')

    # If the string contains ' AI ' internally or at start, flag as parse error
    # Accept only if no ' AI' token at end (already matched above)
    if re.search(r'\bAI\b', reading, flags=re.IGNORECASE):
        # Contains AI token but not in accepted suffix position -> parse error
        return (False, "reading contains misplaced 'AI' token")

    # Not AI: set fields
    if 'ai_reading' not in rec:
        rec['ai_reading'] = False
        changes['ai_reading'] = False
    if not rec.get('original_reading'):
        rec['original_reading'] = reading
        changes['original_reading'] = '(copied from reading)'
    if 'original_reading_text' not in rec or rec['original_reading_text'] == '':
        rec['original_reading_text'] = reading
        changes['original_reading_text'] = '(copied from reading)'

    return (True, '')


def verse_text_ends_with_valid_char(text: str) -> bool:
    """
    Return True if the trimmed verse_text ends with any character in VALID_VERSE_END_CHARS.
    """
    if not isinstance(text, str) or text.strip() == '':
        return False
    t = text.rstrip()
    return any(t.endswith(ch) for ch in VALID_VERSE_END_CHARS)


def update_record(
    rec: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], bool, bool, str, bool]:
    """
    Returns (updated_record, changes_summary, verse_ok, reading_ok, reading_error_msg, verse_text_end_ok)
    """
    rec = dict(rec)
    changes: Dict[str, Any] = {}

    # Ensure new fields exist with default ""
    for f in NEW_FIELDS:
        if f not in rec:
            rec[f] = ''
            changes[f] = '(added default)'

    # Copy subject to original_subject if available
    if 'subject' in rec:
        if rec.get('original_subject', '') != rec['subject']:
            rec['original_subject'] = rec['subject']
            changes['original_subject'] = rec['subject']

    # Preserve original reflection into original_reflection_text if present
    if 'reflection' in rec and not rec.get('original_reflection_text'):
        rec['original_reflection_text'] = rec['reflection'] or ''
        if rec['original_reflection_text']:
            changes['original_reflection_text'] = '(copied from reflection)'

    # Reading handling
    reading_ok, reading_err = handle_reading(rec, changes)

    # Verse handling
    verse_value = rec.get('verse', '')
    verse_text, verse_ref, verse_src, verse_ok = extract_verse_parts(verse_value)

    verse_text_end_ok = True
    if verse_ok:
        rec['verse_text'] = verse_text
        rec['original_verse_text'] = verse_text
        changes['verse_text'] = verse_text
        changes['original_verse_text'] = '(copied from verse_text)'

        rec['original_verse'] = verse_ref
        changes['original_verse'] = verse_ref

        rec['verse'] = verse_ref
        changes['verse'] = verse_ref

        norm_src = normalize_source_token(verse_src)
        if norm_src:
            rec['original_verse_source'] = norm_src
            rec['verse_source'] = norm_src
            changes['original_verse_source'] = norm_src
            changes['verse_source'] = norm_src

        # Validate final character of verse_text
        verse_text_end_ok = verse_text_ends_with_valid_char(verse_text)
    else:
        if isinstance(verse_value, str):
            orig = verse_value.strip()
            if rec.get('original_verse', '') != orig:
                rec['original_verse'] = orig
                changes['original_verse'] = '(kept original; pattern not matched)'
        # If verse didn't parse, skip end-char validation to avoid double error

    return rec, changes, verse_ok, reading_ok, reading_err, verse_text_end_ok


def process_file(path: Path, preview: bool) -> int:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception as e:
        print(f'[ERROR] {path}: failed to parse JSON: {e}')
        return 1

    # Identify the record list
    if isinstance(data, list):
        records = data
        container = None
        key_in_container = None
    elif isinstance(data, dict):
        list_keys = [k for k, v in data.items() if isinstance(v, list)]
        if len(list_keys) == 1:
            key_in_container = list_keys[0]
            records = data[key_in_container]
            container = data
        else:
            print(f'[ERROR] {path}: expected a list or a dict with a single list of records')
            return 1
    else:
        print(f'[ERROR] {path}: unsupported JSON structure')
        return 1

    if not isinstance(records, list):
        print(f'[ERROR] {path}: records is not a list')
        return 1

    updated_records: List[Dict[str, Any]] = []
    all_changes: List[Dict[str, Any]] = []
    verse_failures: List[int] = []
    reading_failures: List[Tuple[int, str]] = []
    verse_text_end_failures: List[int] = []

    for idx, rec in enumerate(records):
        if not isinstance(rec, dict):
            print(f'[WARN] {path}: record {idx + 1} is not an object; skipping')
            updated_records.append(rec)
            all_changes.append({'_note': 'skipped non-object'})
            continue

        upd, changes, verse_ok, reading_ok, reading_err, verse_text_end_ok = update_record(rec)
        updated_records.append(upd)
        all_changes.append(changes)

        if not verse_ok:
            verse_failures.append(idx + 1)
        if not reading_ok:
            reading_failures.append((idx + 1, reading_err))
        if verse_ok and not verse_text_end_ok:
            verse_text_end_failures.append(idx + 1)

    # Strict preview behavior: any failure => print and exit
    if preview and (verse_failures or reading_failures or verse_text_end_failures):
        for line_no in verse_failures:
            print(f"[PARSE ERROR] {path}:{line_no} verse did not match '<text> (<ref>) [source]'")
        for line_no, msg in reading_failures:
            print(f'[PARSE ERROR] {path}:{line_no} {msg}')
        for line_no in verse_text_end_failures:
            allowed = ', '.join(repr(ch) for ch in VALID_VERSE_END_CHARS)
            print(f'[PARSE ERROR] {path}:{line_no} verse_text must end with one of: {allowed}')
        return 2

    # Preview output
    if preview:
        print(f'\n=== Preview: {path} ===')
        for i, changes in enumerate(all_changes, start=1):
            print(SEPARATOR)
            print(f'Record {i}:')
            if changes:
                for k, v in changes.items():
                    display = v
                    if isinstance(v, str) and len(v) > 140:
                        display = v[:140] + ' …'
                    print(f'- {k}: {display}')
            else:
                print('- No changes')
        print(SEPARATOR)
        return 0

    # Write back changes (non-preview)
    if container is None:
        out_data = updated_records
    else:
        container[key_in_container] = updated_records
        out_data = container

    try:
        path.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'[OK] {path}: updated')
        return 0
    except Exception as e:
        print(f'[ERROR] {path}: failed to write updates: {e}')
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Update devotional JSON files with new fields and parsed verse/reading data. In --preview, stop on any parse failure and when verse_text's final char is invalid."
    )
    parser.add_argument('files', nargs='+', help='One or more JSON files (e.g., *.json)')
    parser.add_argument(
        '--preview',
        action='store_true',
        help='Show changes without modifying files. Any parse issue aborts with errors.',
    )
    args = parser.parse_args()

    exit_code = 0
    for file_arg in args.files:
        path = Path(file_arg)
        if not path.exists():
            print(f'[ERROR] {path}: not found')
            exit_code = max(exit_code, 1)
            continue
        rc = process_file(path, preview=args.preview)
        exit_code = max(exit_code, rc)
        if args.preview and rc != 0:
            break

    sys.exit(exit_code)


if __name__ == '__main__':
    main()
