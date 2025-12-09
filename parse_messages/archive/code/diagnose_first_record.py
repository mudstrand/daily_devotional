#!/usr/bin/env python3
import json
import re
import sys
import unicodedata

ZERO_WIDTHS = ''.join(
    [
        '\\u200b',
        '\\u200c',
        '\\u200d',
        '\\u2060',
        '\\ufeff',
    ]
)
ZW_RE = re.compile(f'[{re.escape(ZERO_WIDTHS)}]')

BIBLEISH_WITH_COLON = re.compile(r'^(?:[1-3]|I{1,3})?\\s*[A-Za-z][A-Za-z.\\s]*\\d+\\s*:\\s*\\d')
BIBLEISH_ANY_DIGIT = re.compile(r'^(?:[1-3]|I{1,3})?\\s*[A-Za-z][A-Za-z.\\s]*\\d')


def cp(s):
    return ' '.join(f'U+{ord(c):04X}' for c in s)


def sanitize(s: str) -> str:
    s = unicodedata.normalize('NFKC', s)
    s = ZW_RE.sub('', s)
    return s.strip()


def main():
    if len(sys.argv) != 2:
        print('Usage: diagnose_first_record.py file.json')
        sys.exit(2)
    path = sys.argv[1]
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    if content.startswith('\\ufeff'):
        print('[info] Leading BOM at file start found; stripping')
        content = content.lstrip('\\ufeff')
    try:
        data = json.loads(content)
    except Exception as e:
        print(f'[error] json.loads failed: {e}')
        sys.exit(1)

    # Pick first record
    if isinstance(data, list) and data:
        rec = data[0]
    elif isinstance(data, dict):
        rec = data
    else:
        print('[error] Unsupported top-level JSON')
        sys.exit(1)

    verse = rec.get('verse')
    print(f'[raw verse] type={type(verse).__name__}')
    if not isinstance(verse, str):
        print('[error] verse is not a string or missing')
        sys.exit(1)

    print('[raw verse text]')
    print(verse)
    print('[raw codepoints tail 64]')
    print(cp(verse[-64:]))

    s = sanitize(verse)
    print('[sanitized verse]')
    print(s)
    print('[sanitized codepoints tail 64]')
    print(cp(s[-64:]))

    groups = re.findall(r'\\(([^()]+)\\)', s)
    print(f'[paren groups found: {len(groups)}]')
    for i, g in enumerate(groups, 1):
        gs = sanitize(g)
        has_colon = bool(BIBLEISH_WITH_COLON.search(gs))
        has_digit = bool(BIBLEISH_ANY_DIGIT.search(gs))
        print(f"  [{i}] '{gs}'  colon={has_colon} digit={has_digit}  cps_tail={cp(gs[-32:])}")

    # Decision emulation
    ref = None
    for g in reversed(groups):
        gs = sanitize(g)
        if BIBLEISH_WITH_COLON.search(gs):
            ref = gs
            break
    if not ref:
        for g in reversed(groups):
            gs = sanitize(g)
            if BIBLEISH_ANY_DIGIT.search(gs):
                ref = gs
                break
    print(f'[decision] ref={ref!r}')


if __name__ == '__main__':
    main()
